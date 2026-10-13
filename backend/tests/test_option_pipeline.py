import unittest

from app.services.option_text import canonical_option, normalize_option_text
from app.main import MCQOption
from scripts.import_tcs_full_length_papers import clean_question_text, parse_options


class OptionTextTests(unittest.TestCase):
    def test_normalizes_transport_artifacts_without_flattening_lines(self):
        value = " **First&nbsp;line\\nSecond line &amp; x &lt; y** "
        self.assertEqual(normalize_option_text(value), "First line\nSecond line & x < y")

    def test_keeps_math_and_code_like_characters(self):
        value = r"x <= y; path\\file; 50% (a / b)"
        self.assertEqual(normalize_option_text(value), value)

    def test_canonical_shape_uses_the_stored_label_once(self):
        option = canonical_option({
            "option_id": 7,
            "option_key": "b",
            "option_text": "B. is not a parser prefix in stored text",
            "display_order": 2,
        })
        self.assertEqual(option["id"], 7)
        self.assertEqual(option["label"], "B")
        self.assertEqual(option["text"], "is not a parser prefix in stored text")
        self.assertEqual(option["order"], 2)

    def test_question_response_keeps_canonical_fields_and_legacy_aliases(self):
        option = canonical_option({
            "option_id": 7,
            "option_key": "A",
            "option_text": "One half",
            "display_order": 1,
        })
        response = MCQOption.model_validate(option).model_dump()
        self.assertEqual((response["label"], response["text"], response["order"]), ("A", "One half", 1))
        self.assertEqual((response["option_key"], response["option_text"], response["display_order"]), ("A", "One half", 1))


class TcsOptionParserTests(unittest.TestCase):
    def test_parses_bulleted_options_and_multiline_continuations(self):
        lines = [
            "Question stem",
            "- A. First option",
            "  continued on the next source line",
            "- B) Second option",
            "- C. Third option",
            "- D. Fourth option",
            "**Answer:** B",
        ]
        options, answer = parse_options(lines)
        self.assertEqual(options, ["First option\ncontinued on the next source line", "Second option", "Third option", "Fourth option"])
        self.assertEqual(answer, "B")
        self.assertEqual(clean_question_text(lines), "Question stem")

    def test_uses_terminal_numbered_block_not_question_enumeration(self):
        lines = [
            "Which group is correct?",
            "1. First statement",
            "2. Second statement",
            "3. Third statement",
            "4. Fourth statement",
            "1) Choice one",
            "2) Choice two",
            "3) Choice three",
            "4) Choice four",
            "Answer: 3",
        ]
        options, _ = parse_options(lines)
        self.assertEqual(options, ["Choice one", "Choice two", "Choice three", "Choice four"])
        self.assertIn("First statement", clean_question_text(lines))
        self.assertNotIn("Choice one", clean_question_text(lines))

    def test_does_not_promote_incomplete_lists_to_mcq_options(self):
        options, _ = parse_options(["1. A fact", "2. Another fact", "Answer: 1"])
        self.assertEqual(options, [])
