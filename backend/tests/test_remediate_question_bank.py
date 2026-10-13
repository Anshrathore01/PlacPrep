import unittest

from scripts.remediate_question_bank import (
    _category_codes,
    _coding_issue_codes,
    _filter_records,
    _mcq_issue_codes,
    build_final_records,
)


class RemediateQuestionBankTests(unittest.TestCase):
    def _mcq(self):
        return {
            "question_id": 12,
            "source_id": 1,
            "source_name": "Custom source",
            "source_type": "CUSTOM",
            "source_question_number": 4,
            "source_metadata": {"source_question_number": 4},
            "title": "Basic arithmetic",
            "question_type": "MCQ",
            "status": "DRAFT",
            "difficulty": "EASY",
            "track_id": 1,
            "topic_id": 2,
            "topic_name": "Math",
            "subtopic_id": 3,
            "subtopic_name": "Arithmetic",
            "taxonomy_track_id": 1,
            "question_text": "What is 2 + 2?",
            "correct_option_key": "A",
            "is_multiple_correct": False,
            "mcq_explanation": "2 + 2 = 4.",
            "options": [
                {"option_key": key, "option_text": value}
                for key, value in (("A", "4"), ("B", "3"), ("C", "5"), ("D", "6"))
            ],
            "duplicate_group": False,
            "duplicate_groups": [],
            "duplicate_matches": [],
            "input_format": None,
            "output_format": None,
            "constraints_text": None,
            "problem_statement": None,
            "solution_pseudocode": None,
            "solution_explanation": None,
            "time_complexity": None,
            "space_complexity": None,
            "public_test_case_count": 0,
            "hidden_test_case_count": 0,
            "example_count": 0,
            "test_case_count": 0,
        }

    def _coding(self):
        return {
            "question_id": 15,
            "problem_statement": "",
            "constraints_text": "",
            "input_format": "",
            "output_format": "",
            "starter_code": "",
            "solution_pseudocode": "Not enough to infer the task.",
            "complete_example_count": 0,
            "public_test_case_count": 0,
            "hidden_test_case_count": 0,
            "example_count": 0,
            "time_complexity": None,
            "space_complexity": None,
            "solution_explanation": None,
            "source_type": "CUSTOM",
            "source_id": 1,
            "source_name": "Custom coding source",
            "topic_id": 1,
            "subtopic_id": 2,
            "duplicate_group": False,
        }

    def test_mcq_key_is_never_claimed_verified_by_structure_alone(self):
        issues = _mcq_issue_codes(self._mcq())

        self.assertIn("MCQ_ANSWER_NOT_INDEPENDENTLY_VERIFIED", issues)
        self.assertIn(
            "MCQ_ANSWER_UNVERIFIED",
            _category_codes({"errors": issues}),
        )
        invalid_key_question = self._mcq()
        invalid_key_question["correct_option_key"] = "Z"
        invalid_key_issues = _mcq_issue_codes(invalid_key_question)
        self.assertIn(
            "MCQ_INVALID_ANSWER",
            _category_codes({"errors": invalid_key_issues}),
        )

    def test_coding_missing_data_and_judge_are_reported(self):
        issues = _coding_issue_codes(self._coding(), docker_ready=False)

        self.assertIn("CODING_MISSING_STATEMENT", issues)
        self.assertIn("CODING_MISSING_INPUT_FORMAT", issues)
        self.assertIn("CODING_MISSING_TEST_CASES", issues)
        self.assertIn("CODING_TEST_VALIDATION_FAILED", issues)
        categories = _category_codes({"errors": issues})
        self.assertIn("CODING_AMBIGUOUS_CONTRACT", categories)

    def test_no_record_is_publish_ready_without_individual_verification(self):
        question = self._mcq()
        audited = [
            {
                "question_id": 12,
                "governance_ready": True,
                "governance_errors": [],
            }
        ]

        records = build_final_records([question], docker_ready=True, governance_audit={"questions": audited})

        self.assertEqual(records[0]["new_status"], "REVIEW")
        self.assertFalse(records[0]["publish_ready"])
        self.assertFalse(records[0]["expected_outputs_verified"])
        self.assertEqual(records[0]["new_answer_key"], "A")

    def test_question_filters_apply_type_source_id_and_limit(self):
        records = [
            {"question_id": 1, "question_type": "MCQ", "source_id": 1},
            {"question_id": 2, "question_type": "CODING", "source_id": 1},
            {"question_id": 3, "question_type": "MCQ", "source_id": 2},
        ]

        selected = _filter_records(
            records,
            ids=None,
            types={"MCQ"},
            source_id=1,
            limit=1,
        )

        self.assertEqual([row["question_id"] for row in selected], [1])


if __name__ == "__main__":
    unittest.main()
