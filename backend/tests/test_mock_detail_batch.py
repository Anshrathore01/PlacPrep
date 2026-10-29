import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.services.question_service import get_question_detail_student


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return self.rows


class _MockDetailConnection:
    def __init__(self):
        self.calls = []
        self.mock = {
            "mock_test_id": 1735,
            "blueprint_id": None,
            "company_id": None,
            "company_name": None,
            "program_name": None,
            "pattern_version": None,
            "verification_status": None,
            "title": "AI easy practice",
            "mode": "PRACTICE",
            "selection_mode": "FIXED_QUESTIONS",
            "duration_seconds": 1800,
            "total_questions": 10,
            "status": "PUBLISHED",
        }
        self.assignments = [
            {"sequence_no": index, "points": 1, "question_id": 1000 + index}
            for index in range(1, 11)
        ]
        self.questions = [
            {
                "question_id": 1000 + index,
                "title": f"Practice question {index}",
                "question_type": "MCQ",
                "difficulty": "EASY",
                "status": "PUBLISHED",
                "source_metadata": json.dumps({"section": "Aptitude"}),
            }
            for index in range(1, 11)
        ]
        self.mcqs = [
            {
                "question_id": row["question_id"],
                "question_text": f"Question text {index}",
                "is_multiple_correct": 0,
            }
            for index, row in enumerate(self.questions, start=1)
        ]
        self.options = [
            {
                "question_id": row["question_id"],
                "option_id": row["question_id"] * 10 + order,
                "option_key": chr(64 + order),
                "option_text": f"Option {order}",
                "display_order": order,
            }
            for row in self.questions
            for order in range(1, 5)
        ]
        self.coding_questions = [{
            "question_id": 1001,
            "problem_statement": "Write a function that sums two integers.",
            "constraints_text": "Integers fit in 32 bits.",
            "input_format": "Two integers.",
            "output_format": "Their sum.",
            "starter_code": "",
            "solution_pseudocode": "Return a + b.",
            "solution_explanation": "Add the inputs.",
        }]
        self.examples = [{
            "question_id": 1001,
            "example_number": 1,
            "input_data": "2 3",
            "output_data": "5",
            "explanation": "2 + 3 = 5",
        }]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, statement, params=None):
        sql = str(statement)
        params = params or {}
        self.calls.append((sql, params))

        if "FROM mock_tests mt" in sql:
            rows = [self.mock]
        elif "FROM mock_test_questions" in sql:
            rows = self.assignments
        elif "FROM questions q" in sql:
            ids = params.get("question_ids", [params.get("question_id")])
            rows = [row for row in self.questions if row["question_id"] in ids]
        elif "FROM mcq_questions" in sql:
            ids = params.get("question_ids", [params.get("question_id")])
            rows = [row for row in self.mcqs if row["question_id"] in ids]
        elif "FROM mcq_options" in sql:
            ids = params.get("question_ids", [params.get("question_id")])
            rows = sorted(
                (row for row in self.options if row["question_id"] in ids),
                key=lambda row: (row["question_id"], row["display_order"]),
            )
        elif "FROM coding_questions" in sql:
            ids = params.get("question_ids", [params.get("question_id")])
            rows = [row for row in self.coding_questions if row["question_id"] in ids]
            if "question_ids" not in params:
                rows = [
                    {key: value for key, value in row.items() if key != "question_id"}
                    for row in rows
                ]
        elif "FROM question_examples" in sql:
            ids = params.get("question_ids", [params.get("question_id")])
            rows = [row for row in self.examples if row["question_id"] in ids]
            if "question_ids" not in params:
                rows = [
                    {key: value for key, value in row.items() if key != "question_id"}
                    for row in rows
                ]
        else:
            raise AssertionError(f"Unexpected mock-detail query: {sql}")
        return _Result(rows)


class MockDetailBatchTests(unittest.TestCase):
    def _assert_mock_detail_equivalent(self, connection):
        legacy_questions = [
            get_question_detail_student(connection, row["question_id"])
            for row in connection.assignments
        ]
        self.assertEqual(len(connection.calls), 30)
        self.assertEqual(2 + len(connection.calls), 32)

        expected_questions = []
        for row, question in zip(connection.assignments, legacy_questions):
            expected_questions.append({
                **question,
                "sequence_no": row["sequence_no"],
                "points": float(row["points"]),
            })
        expected = {**connection.mock, "questions": expected_questions}
        legacy_response_bytes = json.dumps(expected, separators=(",", ":")).encode()

        optimized_connection = _MockDetailConnection()
        optimized_connection.questions = [
            dict(question) for question in connection.questions
        ]
        with patch("app.main.engine.connect", return_value=optimized_connection):
            response = TestClient(app).get("/mock-tests/1735")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), expected)
        expected_batched_queries = 3
        if any(question["question_type"] == "MCQ" for question in connection.questions):
            expected_batched_queries += 2
        if any(question["question_type"] == "CODING" for question in connection.questions):
            expected_batched_queries += 2
        self.assertEqual(len(optimized_connection.calls), expected_batched_queries)
        self.assertEqual(len(response.content), len(legacy_response_bytes))
        self.assertEqual(response.content, legacy_response_bytes)
        self.assertNotIn(b"correct_option_key", response.content)

    def test_ten_mcq_mock_detail_is_equivalent_with_bounded_query_count(self):
        self._assert_mock_detail_equivalent(_MockDetailConnection())

    def test_mixed_coding_and_mcq_mock_detail_preserves_existing_fields(self):
        connection = _MockDetailConnection()
        connection.questions[0]["question_type"] = "CODING"
        self._assert_mock_detail_equivalent(connection)


if __name__ == "__main__":
    unittest.main()
