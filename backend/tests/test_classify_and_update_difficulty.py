import unittest

from scripts.classify_and_update_difficulty import (
    _coding_profile,
    _mcq_profile,
    classify_question,
    validate_classifications,
)


class ClassifyAndUpdateDifficultyTests(unittest.TestCase):
    def test_direct_custom_percentage_is_easy(self):
        result = _mcq_profile(
            {
                "question_text": "What is 25% of 400?",
                "title": "What is 25% of 400?",
                "explanation": "25% of 400 = (25/100) × 400 = 100",
                "topic_name": "Quantitative Aptitude",
                "options": [
                    {"option_text": value}
                    for value in ("50", "75", "100", "125")
                ],
            }
        )

        self.assertEqual(result["difficulty"], "EASY")
        self.assertEqual(result["confidence"], "HIGH")
        self.assertIn("percentage", result["reason"].casefold())

    def test_direct_speed_calculation_is_easy(self):
        result = _mcq_profile(
            {
                "question_text": "If a train travels 120 km in 2 hours, what is its speed?",
                "title": "If a train travels 120 km in 2 hours, what is its speed?",
                "explanation": "Speed = Distance/Time = 120/2 = 60 km/h",
                "topic_name": "Quantitative Aptitude",
                "options": [{"option_text": value} for value in ("50", "60", "70", "80")],
            }
        )

        self.assertEqual(result["difficulty"], "EASY")
        self.assertIn("speed calculation", result["reason"])

    def test_letter_shift_is_not_hard_due_to_arrow_count(self):
        result = _mcq_profile(
            {
                "question_text": "If CODING is written as DPEJOH, how is MOTHER written?",
                "title": "If CODING is written as DPEJOH, how is MOTHER written?",
                "explanation": "Each letter shifts +1: M→N, O→P, T→U, H→I, E→F, R→S",
                "topic_name": "Logical Reasoning",
                "options": [{"option_text": value} for value in ("NPUIFS", "NPTIFS", "OPUIFS", "NPUIFS")],
            }
        )

        self.assertNotEqual(result["difficulty"], "HARD")

    def test_chained_calculation_is_medium(self):
        result = _mcq_profile(
            {
                "question_text": "What is 15% of 15% of 200?",
                "title": "What is 15% of 15% of 200?",
                "explanation": "15% of 200 = 30. Then 15% of 30 = 4.5",
                "topic_name": "Quantitative Aptitude",
                "options": [{"option_text": value} for value in ("3.5", "4", "4.5", "5")],
            }
        )

        self.assertEqual(result["difficulty"], "MEDIUM")

    def test_malformed_mcq_is_still_classified(self):
        result = _mcq_profile(
            {
                "question_text": "Choose the correct synonym for benevolent",
                "title": "Choose the correct synonym for benevolent",
                "explanation": "",
                "topic_name": "Verbal Ability",
                "options": [],
            }
        )

        self.assertIn(result["difficulty"], {"EASY", "MEDIUM", "HARD"})
        self.assertIn(result["confidence"], {"HIGH", "MEDIUM", "LOW"})

    def test_basic_array_reversal_is_easy_not_hard_by_title(self):
        result = _coding_profile(
            {
                "title": "Reverse an array using dynamic programming",
                "problem_statement": "Reverse the elements of an array in place.",
                "constraints_text": "1 <= N <= 100000. O(N) time and O(1) space.",
                "solution_pseudocode": (
                    "Set left and right pointers. While left < right, swap the "
                    "two values, then move both pointers inward."
                ),
                "time_complexity": "O(N)",
                "space_complexity": "O(1)",
            }
        )

        self.assertEqual(result["difficulty"], "EASY")

    def test_explicit_dp_state_and_subproblems_is_hard(self):
        result = _coding_profile(
            {
                "title": "Count optimal ways",
                "problem_statement": "Compute the optimum over all sequences.",
                "constraints_text": "N <= 100000.",
                "solution_pseudocode": (
                    "Define dp[i][state] from all prior subproblems. Memoize "
                    "states and take the best transition."
                ),
                "time_complexity": "O(N^2)",
                "space_complexity": "O(N^2)",
            }
        )

        self.assertEqual(result["difficulty"], "HARD")
        self.assertNotEqual(result["confidence"], "LOW")

    def test_edit_distance_with_three_dp_transitions_is_hard(self):
        result = _coding_profile(
            {
                "title": "Minimum edits between two strings",
                "problem_statement": (
                    "Find the minimum insertions, deletions, and replacements "
                    "to convert one string to another."
                ),
                "constraints_text": "Both strings may have length 500.",
                "solution_pseudocode": (
                    "Use DP where dp[i][j] is the minimum edits for prefixes. "
                    "Choose the minimum of insert, delete, and replace."
                ),
                "time_complexity": None,
                "space_complexity": None,
            }
        )

        self.assertEqual(result["difficulty"], "HARD")

    def test_n_queens_conflict_search_is_hard(self):
        result = _coding_profile(
            {
                "title": "N-Queens",
                "problem_statement": (
                    "Place N queens on an N by N board so no two queens attack "
                    "each other, and return all distinct solutions."
                ),
                "constraints_text": "1 <= N <= 9.",
                "solution_pseudocode": (
                    "Place one queen per row. Try columns not blocked by an "
                    "occupied column or diagonal, recurse, then undo."
                ),
                "time_complexity": None,
                "space_complexity": None,
            }
        )

        self.assertEqual(result["difficulty"], "HARD")

    def test_question_result_has_required_individual_fields(self):
        result = classify_question(
            {
                "question_id": 42,
                "question_type": "MCQ",
                "title": "What is 25% of 400?",
                "question_text": "What is 25% of 400?",
                "explanation": "25% of 400 = 100",
                "topic_name": "Quantitative Aptitude",
                "subtopic_name": "Percentages",
                "source_name": "Custom",
                "existing_difficulty": None,
                "options": [],
            }
        )

        self.assertEqual(
            set(("question_id", "question_type", "difficulty", "confidence", "reason"))
            - set(result),
            set(),
        )
        self.assertEqual(result["question_id"], 42)

    def test_validation_rejects_missing_or_duplicate_ids_and_bad_labels(self):
        questions = [{"question_id": 1}, {"question_id": 2}]
        valid = [
            {
                "question_id": 1,
                "difficulty": "EASY",
                "confidence": "HIGH",
                "reason": "One-step calculation.",
            },
            {
                "question_id": 2,
                "difficulty": "HARD",
                "confidence": "MEDIUM",
                "reason": "Advanced state-based algorithm.",
            },
        ]
        validate_classifications(questions, valid, expected_count=2)

        with self.assertRaises(ValueError):
            validate_classifications(
                questions,
                [valid[0]],
                expected_count=2,
            )
        with self.assertRaises(ValueError):
            validate_classifications(
                questions,
                [
                    valid[0],
                    {**valid[1], "question_id": 1},
                ],
                expected_count=2,
            )
        with self.assertRaises(ValueError):
            validate_classifications(
                questions,
                [
                    valid[0],
                    {**valid[1], "difficulty": None},
                ],
                expected_count=2,
            )


if __name__ == "__main__":
    unittest.main()
