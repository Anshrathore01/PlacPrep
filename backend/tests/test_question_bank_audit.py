import unittest

from scripts.audit_question_bank import (
    classify_mcq_issues,
    incomplete_option_question_count,
)


class QuestionBankAuditTests(unittest.TestCase):
    def test_incomplete_option_metric_counts_questions_not_bucket_keys(self):
        self.assertEqual(
            incomplete_option_question_count({0: 932, 2: 115, 3: 37, 4: 365, 5: 468}),
            152,
        )

    def _valid_options(self):
        return [
            {"option_key": key, "option_text": f"Option {key}"}
            for key in ("A", "B", "C", "D")
        ]

    def _valid_mapping(self):
        return [
            {
                "subtopic_id": 1,
                "topic_id": 1,
                "track_id": 1,
                "question_track_id": 1,
            }
        ]

    def test_audit_marks_structurally_valid_question(self):
        issues = classify_mcq_issues(
            question_text="Question?",
            correct_option_key="A",
            is_multiple_correct=False,
            difficulty="MEDIUM",
            options=self._valid_options(),
            mappings=self._valid_mapping(),
        )
        self.assertEqual(issues, [])

    def test_audit_detects_missing_and_incomplete_options(self):
        missing = classify_mcq_issues(
            question_text="Question?",
            correct_option_key=None,
            is_multiple_correct=False,
            difficulty="EASY",
            options=[],
            mappings=self._valid_mapping(),
        )
        self.assertIn("MISSING_OPTIONS", missing)
        self.assertIn("NULL_ANSWER_KEY", missing)

        incomplete = classify_mcq_issues(
            question_text="Question?",
            correct_option_key="A",
            is_multiple_correct=False,
            difficulty="EASY",
            options=self._valid_options()[:3],
            mappings=self._valid_mapping(),
        )
        self.assertIn("INCOMPLETE_OPTIONS", incomplete)

    def test_audit_detects_invalid_key_duplicates_difficulty_and_mapping(self):
        options = self._valid_options()
        options[-1]["option_text"] = options[0]["option_text"].upper()
        issues = classify_mcq_issues(
            question_text="Question?",
            correct_option_key="Z",
            is_multiple_correct=False,
            difficulty=None,
            options=options,
            mappings=[
                {
                    "subtopic_id": 2,
                    "topic_id": 2,
                    "track_id": 2,
                    "question_track_id": 1,
                }
            ],
            duplicate_content=True,
        )
        self.assertIn("INVALID_ANSWER_KEY", issues)
        self.assertIn("DUPLICATE_OPTIONS", issues)
        self.assertIn("DUPLICATE_CONTENT", issues)
        self.assertIn("MISSING_DIFFICULTY", issues)
        self.assertIn("INCONSISTENT_TRACK", issues)

    def test_audit_detects_unmapped_and_invalid_topic_rows(self):
        missing = classify_mcq_issues(
            question_text="Question?",
            correct_option_key="A",
            is_multiple_correct=False,
            difficulty="HARD",
            options=self._valid_options(),
            mappings=[],
        )
        self.assertIn("MISSING_SUBTOPIC", missing)

        invalid = classify_mcq_issues(
            question_text="Question?",
            correct_option_key="A",
            is_multiple_correct=False,
            difficulty="HARD",
            options=self._valid_options(),
            mappings=[
                {
                    "subtopic_id": None,
                    "topic_id": None,
                    "track_id": None,
                    "question_track_id": 1,
                }
            ],
        )
        self.assertIn("INVALID_SUBTOPIC", invalid)

        missing_topic = classify_mcq_issues(
            question_text="Question?",
            correct_option_key="A",
            is_multiple_correct=False,
            difficulty="HARD",
            options=self._valid_options(),
            mappings=[
                {
                    "subtopic_id": 2,
                    "topic_id": None,
                    "track_id": None,
                    "question_track_id": 1,
                }
            ],
        )
        self.assertIn("MISSING_TOPIC", missing_topic)


if __name__ == "__main__":
    unittest.main()
