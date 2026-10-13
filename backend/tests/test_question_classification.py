import unittest

from scripts.audit_question_bank import (
    _governance_issue_code,
    classify_mcq_issues,
    has_source_traceability,
)
from scripts.classify_question_difficulty import (
    classify_difficulty,
    is_publication_ready,
    requires_review,
)


class QuestionDifficultyClassificationTests(unittest.TestCase):
    def test_direct_single_step_calculation_is_repeatable_and_explainable(self):
        inputs = {
            "question_text": "What is 25% of 400?",
            "explanation": "25% of 400 = (25/100) × 400 = 100",
            "topic_name": "Quantitative Aptitude",
            "source_metadata": {},
        }
        first = classify_difficulty(**inputs)
        second = classify_difficulty(**inputs)

        self.assertEqual(first, second)
        self.assertEqual(first["proposed_difficulty"], "EASY")
        self.assertGreaterEqual(first["confidence"], 0.9)
        self.assertIn("single direct calculation", first["classification_reason"])

    def test_direct_distance_time_formula_can_be_high_confidence(self):
        result = classify_difficulty(
            question_text="If a train travels 120 km in 2 hours, what is its speed?",
            explanation="Speed = Distance/Time = 120/2 = 60 km/h",
            topic_name="Quantitative Aptitude",
            source_metadata={},
        )

        self.assertEqual(result["proposed_difficulty"], "EASY")
        self.assertGreaterEqual(result["confidence"], 0.9)

    def test_multiple_solution_steps_remain_below_high_confidence_threshold(self):
        result = classify_difficulty(
            question_text=(
                "The average of 5 numbers is 20. If one is excluded, "
                "the average becomes 15. What was excluded?"
            ),
            explanation=(
                "Sum of 5 numbers = 5 × 20 = 100. "
                "Sum of 4 numbers = 4 × 15 = 60. "
                "Excluded number = 100 - 60 = 40."
            ),
            topic_name="Quantitative Aptitude",
            source_metadata={},
        )

        self.assertEqual(result["proposed_difficulty"], "MEDIUM")
        self.assertLess(result["confidence"], 0.9)
        self.assertTrue(requires_review(result["confidence"], result["proposed_difficulty"], 0.9))

    def test_chained_percentages_are_not_treated_as_single_step(self):
        result = classify_difficulty(
            question_text="What is 15% of 15% of 200?",
            explanation="15% of 200 = 30. Then 15% of 30 = 4.5",
            topic_name="Quantitative Aptitude",
            source_metadata={},
        )

        self.assertEqual(result["proposed_difficulty"], "MEDIUM")
        self.assertLess(result["confidence"], 0.9)

    def test_multiple_interacting_conditions_are_only_a_low_confidence_hard_signal(self):
        result = classify_difficulty(
            question_text=(
                "If A is true, either B or C applies, both D and E must hold, "
                "unless F is false. Determine the result."
            ),
            explanation="Step 1: x = 1; Step 2: y = 2; Step 3: z = 3; Therefore w = 4.",
            topic_name="Logical Reasoning",
            source_metadata={},
        )

        self.assertEqual(result["proposed_difficulty"], "HARD")
        self.assertLess(result["confidence"], 0.9)
        self.assertIn("expert review", result["classification_reason"])

    def test_unrecognized_question_does_not_receive_an_inferred_label(self):
        result = classify_difficulty(
            question_text="Which statement best describes this concept?",
            explanation=None,
            topic_name="Technical Concepts",
            source_metadata={},
        )

        self.assertIsNone(result["proposed_difficulty"])
        self.assertLess(result["confidence"], 0.9)
        self.assertTrue(requires_review(result["confidence"], None, 0.9))

    def test_existing_valid_difficulty_is_preserved(self):
        result = classify_difficulty(
            question_text="What is 25% of 400?",
            explanation="25% of 400 = 100",
            topic_name="Quantitative Aptitude",
            source_metadata={},
            current_difficulty="MEDIUM",
        )

        self.assertEqual(result["proposed_difficulty"], "MEDIUM")
        self.assertEqual(result["confidence"], 1.0)

    def test_source_difficulty_is_used_only_when_explicitly_present(self):
        result = classify_difficulty(
            question_text="A question",
            explanation="An explanation",
            topic_name="Quantitative Aptitude",
            source_metadata={"difficulty": "HARD", "difficulty_source": "Editorial tag"},
        )

        self.assertEqual(result["proposed_difficulty"], "HARD")
        self.assertEqual(result["confidence"], 0.99)
        self.assertIn("Editorial tag", result["classification_reason"])

    def test_audit_flags_invalid_options_answer_key_mapping_and_duplicates(self):
        issues = classify_mcq_issues(
            question_text="Question?",
            correct_option_key="Z",
            is_multiple_correct=False,
            difficulty="INVALID",
            options=[
                {"option_key": "A", "option_text": "Same"},
                {"option_key": "A", "option_text": "Same"},
            ],
            mappings=[],
            duplicate_content=True,
        )

        self.assertIn("INCOMPLETE_OPTIONS", issues)
        self.assertIn("DUPLICATE_OPTION_KEYS", issues)
        self.assertIn("DUPLICATE_OPTIONS", issues)
        self.assertIn("INVALID_ANSWER_KEY", issues)
        self.assertIn("INVALID_DIFFICULTY", issues)
        self.assertIn("MISSING_SUBTOPIC", issues)
        self.assertIn("DUPLICATE_CONTENT", issues)

    def test_governance_errors_from_published_questions_are_classified(self):
        self.assertEqual(
            _governance_issue_code(
                "Question difficulty must be sourced or reviewed as EASY, MEDIUM, or HARD."
            ),
            "MISSING_DIFFICULTY",
        )
        self.assertEqual(
            _governance_issue_code(
                "Every question subtopic must belong to its question track."
            ),
            "INCONSISTENT_TRACK",
        )

    def test_invalid_structure_or_missing_source_trace_blocks_publication(self):
        self.assertFalse(
            is_publication_ready(
                governance_errors=[],
                audit_issues={"INVALID_ANSWER_KEY"},
                duplicate_content=False,
                source_traceable=True,
            )
        )
        self.assertFalse(
            is_publication_ready(
                governance_errors=[],
                audit_issues=set(),
                duplicate_content=False,
                source_traceable=False,
            )
        )
        self.assertTrue(
            is_publication_ready(
                governance_errors=[],
                audit_issues=set(),
                duplicate_content=False,
                source_traceable=True,
            )
        )

    def test_source_traceability_requires_a_specific_record_reference(self):
        self.assertTrue(
            has_source_traceability(
                source_id=2,
                source_name="Custom MCQ Bank",
                source_question_number=12,
                source_metadata="{}",
            )
        )
        self.assertTrue(
            has_source_traceability(
                source_id=2,
                source_name="Custom MCQ Bank",
                source_question_number=None,
                source_metadata='{"source_section":"Verbal","source_question_number":12}',
            )
        )
        self.assertFalse(
            has_source_traceability(
                source_id=2,
                source_name="Custom MCQ Bank",
                source_question_number=None,
                source_metadata="{}",
            )
        )


if __name__ == "__main__":
    unittest.main()
