import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.main import app
from app.services.coding_service import create_submission


class _Result:
    def __init__(self, *, first=None, all_rows=None, scalar=None, lastrowid=None):
        self._first = first
        self._all_rows = all_rows or []
        self._scalar = scalar
        self.lastrowid = lastrowid
        self.rowcount = 1

    def mappings(self):
        return self

    def first(self):
        return self._first

    def all(self):
        return self._all_rows

    def scalar_one(self):
        return self._scalar


class _SubmissionConnection:
    def __init__(
        self,
        *,
        attempt=None,
        question=None,
        cases=None,
        elapsed_microseconds=0,
    ):
        self.attempt = attempt
        self.question = question
        self.cases = cases or []
        self.elapsed_microseconds = elapsed_microseconds
        self.calls = []

    def execute(self, statement, parameters=None):
        query = str(statement)
        self.calls.append((query, parameters or {}))
        if "FROM attempts a" in query:
            return _Result(first=self.attempt)
        if "TIMESTAMPDIFF" in query:
            return _Result(scalar=self.elapsed_microseconds)
        if "FROM questions q" in query:
            return _Result(first=self.question)
        if "FROM coding_test_cases" in query:
            return _Result(all_rows=self.cases)
        if "INSERT INTO coding_submissions" in query:
            return _Result(lastrowid=9001)
        raise AssertionError(f"Unexpected query in test: {query}")


class CodingSubmissionRouteTests(unittest.TestCase):
    def setUp(self):
        self.previous_overrides = dict(app.dependency_overrides)
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        app.dependency_overrides.update(self.previous_overrides)

    def test_submission_requires_authenticated_user(self):
        response = self.client.post(
            "/coding-submissions",
            json={
                "attempt_id": 1,
                "question_id": 2,
                "language": "C++17",
                "source_code": "int main() {}",
            },
        )

        self.assertEqual(response.status_code, 401)

    def test_post_uses_authenticated_identity_and_returns_queued(self):
        principal = {"user_id": 42, "role": "STUDENT"}
        app.dependency_overrides[get_current_user] = lambda: principal
        transaction = MagicMock()
        transaction.__enter__.return_value = MagicMock()

        with (
            patch("app.judge.docker_sandbox.docker_is_ready", return_value=True),
            patch("app.main.engine.begin", return_value=transaction),
            patch(
                "app.services.coding_service.create_submission",
                return_value=9001,
            ) as create_submission,
        ):
            response = self.client.post(
                "/coding-submissions",
                json={
                    "attempt_id": 10,
                    "question_id": 20,
                    "language": "C++17",
                    "source_code": "int main() {}",
                    "user_id": 999,
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "QUEUED")
        self.assertEqual(create_submission.call_args.args[-1], principal)

    def test_post_fails_closed_when_docker_is_unavailable(self):
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": 42,
            "role": "STUDENT",
        }

        with (
            patch("app.judge.docker_sandbox.docker_is_ready", return_value=False),
            patch("app.main.engine.begin") as begin,
        ):
            response = self.client.post(
                "/coding-submissions",
                json={
                    "attempt_id": 10,
                    "question_id": 20,
                    "language": "C++17",
                    "source_code": "int main() {}",
                },
            )

        self.assertEqual(response.status_code, 503)
        begin.assert_not_called()

    def test_get_returns_safe_submission_result(self):
        principal = {"user_id": 42, "role": "STUDENT"}
        app.dependency_overrides[get_current_user] = lambda: principal
        connection = MagicMock()
        connection.__enter__.return_value = MagicMock()

        with (
            patch("app.main.engine.connect", return_value=connection),
            patch(
                "app.services.coding_service.get_submission",
                return_value={
                    "submission_id": 9001,
                    "question_id": 20,
                    "language": "C++17",
                    "status": "PASSED",
                    "tests_passed": 2,
                    "tests_total": 2,
                    "score": "10.00",
                    "submitted_at": None,
                    "completed_at": None,
                    "safe_error_message": None,
                },
            ),
        ):
            response = self.client.get("/coding-submissions/9001")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn("source_code", response.json())
        self.assertNotIn("user_id", response.json())
        self.assertNotIn("hidden_test_data", response.json())


class CodingSubmissionServiceAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.attempt = {
            "attempt_id": 10,
            "user_id": 42,
            "mock_test_id": 5,
            "status": "IN_PROGRESS",
            "started_at": datetime(2026, 1, 1),
            "duration_seconds": None,
        }
        self.question = {
            "question_type": "CODING",
            "status": "PUBLISHED",
            "coding_question_id": 20,
        }
        self.cases = [
            {
                "test_case_number": 1,
                "input_data": "1\n",
                "expected_output": "1\n",
                "points": 1,
            }
        ]
        self.user = {"user_id": 42, "role": "STUDENT"}

    def test_owner_can_queue_supported_submission(self):
        connection = _SubmissionConnection(
            attempt=self.attempt,
            question=self.question,
            cases=self.cases,
        )

        submission_id = create_submission(
            connection,
            10,
            20,
            "C++17",
            "#include <iostream>\nint main(){std::cout << 1;}\n",
            self.user,
        )

        self.assertEqual(submission_id, 9001)
        insert_query, insert_parameters = connection.calls[-1]
        self.assertIn("'QUEUED'", insert_query)
        self.assertEqual(insert_parameters["user_id"], 42)

    def test_another_students_attempt_is_rejected_before_insert(self):
        connection = _SubmissionConnection(
            attempt={**self.attempt, "user_id": 99},
            question=self.question,
            cases=self.cases,
        )

        with self.assertRaises(HTTPException) as raised:
            create_submission(
                connection,
                10,
                20,
                "C++17",
                "int main(){}",
                self.user,
            )

        self.assertEqual(raised.exception.status_code, 403)
        self.assertFalse(
            any("INSERT INTO coding_submissions" in query for query, _ in connection.calls)
        )

    def test_non_active_or_expired_attempt_is_rejected(self):
        inactive = _SubmissionConnection(
            attempt={**self.attempt, "status": "SUBMITTED"},
            question=self.question,
            cases=self.cases,
        )
        with self.assertRaises(HTTPException) as raised:
            create_submission(inactive, 10, 20, "C++17", "int main(){}", self.user)
        self.assertEqual(raised.exception.status_code, 409)

        expired = _SubmissionConnection(
            attempt={**self.attempt, "duration_seconds": 1},
            question=self.question,
            cases=self.cases,
            elapsed_microseconds=1_000_000,
        )
        with self.assertRaises(HTTPException) as raised:
            create_submission(expired, 10, 20, "C++17", "int main(){}", self.user)
        self.assertEqual(raised.exception.status_code, 409)

    def test_question_must_be_in_attempt_and_published_coding(self):
        missing = _SubmissionConnection(attempt=self.attempt)
        with self.assertRaises(HTTPException) as raised:
            create_submission(missing, 10, 20, "C++17", "int main(){}", self.user)
        self.assertEqual(raised.exception.status_code, 404)

        unpublished = _SubmissionConnection(
            attempt=self.attempt,
            question={**self.question, "status": "DRAFT"},
        )
        with self.assertRaises(HTTPException) as raised:
            create_submission(unpublished, 10, 20, "C++17", "int main(){}", self.user)
        self.assertEqual(raised.exception.status_code, 409)

    def test_test_configuration_and_language_are_validated(self):
        connection = _SubmissionConnection(
            attempt=self.attempt,
            question=self.question,
            cases=[],
        )
        with self.assertRaises(HTTPException) as raised:
            create_submission(connection, 10, 20, "Python", "print(1)", self.user)
        self.assertEqual(raised.exception.status_code, 422)

        with self.assertRaises(HTTPException) as raised:
            create_submission(connection, 10, 20, "C++17", "int main(){}", self.user)
        self.assertEqual(raised.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main()
