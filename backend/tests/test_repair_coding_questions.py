import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts.repair_coding_questions import _review_reason, write_report


class CodingQuestionRepairAuditTests(unittest.TestCase):
    def test_missing_problem_statement_is_incomplete_not_reconstructed(self):
        category, errors, _ = _review_reason(
            {
                "problem_statement": "",
                "solution_pseudocode": "Compute the answer.",
                "complete_example_count": 0,
                "public_test_case_count": 0,
                "hidden_test_case_count": 0,
                "example_count": 0,
            }
        )

        self.assertEqual(category, "C_AMBIGUOUS_OR_INCOMPLETE")
        self.assertIn(
            "Problem statement is empty; intended task and I/O semantics cannot be established.",
            errors,
        )

    def test_present_statement_is_not_claimed_semantically_verified(self):
        category, _, warnings = _review_reason(
            {
                "problem_statement": "Reverse the input array.",
                "solution_pseudocode": "Swap elements from both ends.",
                "complete_example_count": 0,
                "public_test_case_count": 0,
                "hidden_test_case_count": 0,
                "example_count": 0,
            }
        )

        self.assertEqual(category, "B_WELL_DEFINED_CANDIDATE_MISSING_METADATA")
        self.assertTrue(
            any("semantic agreement has not been independently established" in item
                for item in warnings)
        )

    def test_report_contains_every_record_and_csv_traceability_fields(self):
        result = {
            "question_id": 1,
            "question_type": "CODING",
            "source_id": 3,
            "source_name": "Coding bank",
            "source_url": None,
            "source_question_number": 1,
            "title": "Reverse an array",
            "topic_name": "Arrays",
            "subtopic_name": "Array Reversal",
            "track_name": "Coding",
            "difficulty": "EASY",
            "old_status": "DRAFT",
            "new_status": "REVIEW",
            "problem_statement": "Reverse the input array.",
            "constraints_text": None,
            "old_input_format": None,
            "new_input_format": None,
            "old_output_format": None,
            "new_output_format": None,
            "starter_code_created": False,
            "examples_created": 0,
            "test_cases_created": 0,
            "public_test_cases": 0,
            "hidden_test_cases": 0,
            "reference_solution_valid": False,
            "starter_code_compiles": False,
            "test_cases_verified": False,
            "judge_validation_passed": False,
            "governance_ready": False,
            "publish_ready": False,
            "classification": "B_WELL_DEFINED_CANDIDATE_MISSING_METADATA",
            "errors": ["No test cases."],
            "warnings": [],
            "review_reason": "Review required.",
            "existing_metadata": {"test_case_count": 0},
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            json_path = Path(temporary_directory) / "report.json"
            csv_path = Path(temporary_directory) / "report.csv"
            write_report([result], json_path, csv_path)

            data = json.loads(json_path.read_text(encoding="utf-8"))
            with csv_path.open(encoding="utf-8", newline="") as report_file:
                csv_rows = list(csv.DictReader(report_file))

        self.assertEqual(data["question_total"], 1)
        self.assertEqual(data["results"][0]["question_id"], 1)
        self.assertEqual(len(csv_rows), 1)
        self.assertEqual(csv_rows[0]["source_name"], "Coding bank")
        self.assertEqual(csv_rows[0]["topic_name"], "Arrays")
        self.assertEqual(csv_rows[0]["publish_ready"], "False")


if __name__ == "__main__":
    unittest.main()
