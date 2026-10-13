import unittest
from contextlib import contextmanager
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.main import app
from app.routers import admin
from app.services import question_governance_service


class FakeMappings:
    def __init__(self, row=None, rows=None):
        self.row = row
        self.rows = rows or ([] if row is None else [row])

    def first(self):
        return self.row

    def all(self):
        return self.rows


class FakeResult:
    def __init__(self, row=None, rowcount=0, rows=None):
        self.row = row
        self.rowcount = rowcount
        self.rows = rows or []

    def mappings(self):
        return FakeMappings(self.row, self.rows)

    def scalars(self):
        return FakeScalars(self.rows)


class FakeScalars:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values


class FakeReviewConnection:
    def __init__(
        self,
        *,
        question_type="MCQ",
        status="REVIEW",
        decision="PENDING",
        notes="MCQ_RECONSTRUCTION_IMPORT:v1:42: import evidence",
        review_id=8,
        update_rowcount=1,
    ):
        self.question = {
            "question_id": 42,
            "question_type": question_type,
            "status": status,
            "source_question_number": 42,
            "source_metadata": {"source_question_number": 42},
        }
        self.review = {
            "review_id": review_id,
            "decision": decision,
            "notes": notes,
        }
        self.update_rowcount = update_rowcount
        self.statements = []
        self.status_history = []

    def execute(self, statement, params=None):
        query = str(statement)
        normalized = " ".join(query.split()).casefold()
        params = params or {}
        self.statements.append((normalized, params))

        if "from questions q join question_reviews qr" in normalized:
            return FakeResult(rows=[42])
        if "select question_id, question_type, status" in normalized:
            return FakeResult(dict(self.question))
        if "select review_id, decision, notes" in normalized:
            return FakeResult(dict(self.review))
        if "select question_id, status, source_question_number, source_metadata" in normalized:
            return FakeResult(dict(self.question))
        if "select decision, notes" in normalized:
            return FakeResult({
                "decision": self.review["decision"],
                "notes": self.review["notes"],
            })
        if "select question_id, status" in normalized:
            return FakeResult({
                "question_id": self.question["question_id"],
                "status": self.question["status"],
            })
        if "update question_reviews" in normalized:
            if self.update_rowcount:
                self.review.update(
                    decision=params["decision"],
                    reviewer_id=params["reviewer_id"],
                    notes=(
                        self.review["notes"]
                        + "\nREVIEW_DECISION:"
                        + params["decision"]
                        + "\nREVIEW_NOTES:"
                        + params["reviewer_notes"]
                    ),
                )
            return FakeResult(rowcount=self.update_rowcount)
        if "update questions set status" in normalized:
            previous = self.question["status"]
            self.question["status"] = params["status"]
            return FakeResult(rowcount=1)
        if "insert into question_status_history" in normalized:
            self.status_history.append(dict(params))
            return FakeResult(rowcount=1)
        if "select review_id, notes" in normalized:
            if "question_classification:" in normalized:
                return FakeResult({
                    "review_id": self.review["review_id"],
                    "notes": "QUESTION_CLASSIFICATION:test",
                })
            return FakeResult(dict(self.review))
        raise AssertionError(f"Unexpected query in isolated test: {query}")


class FakeDetailConnection:
    def execute(self, statement, _params=None):
        query = " ".join(str(statement).split()).casefold()
        if "select q.question_id, q.source_id, s.source_name" in query:
            return FakeResult({
                "question_id": 42,
                "source_id": 3,
                "source_name": "Reconstruction source",
                "source_type": "SCRAPED",
                "source_url": "https://example.test/source",
                "source_notes": "",
                "source_question_number": 42,
                "question_type": "MCQ",
                "track_id": 1,
                "title": "Example question",
                "difficulty": "MEDIUM",
                "status": "REVIEW",
                "content_hash": "test-hash",
                "source_metadata": {"source_question_number": 42},
                "created_at": None,
                "updated_at": None,
            })
        if "select question_text, explanation, correct_option_key" in query:
            return FakeResult({
                "question_text": "Example question?",
                "explanation": "Example explanation.",
                "correct_option_key": "A",
                "is_multiple_correct": False,
            })
        if "select option_key, option_text, display_order" in query:
            return FakeResult(rows=[
                {"option_key": "A", "option_text": "One", "display_order": 1},
                {"option_key": "B", "option_text": "Two", "display_order": 2},
                {"option_key": "C", "option_text": "Three", "display_order": 3},
                {"option_key": "D", "option_text": "Four", "display_order": 4},
            ])
        if "select t.topic_id, t.topic_name, st.subtopic_id" in query:
            return FakeResult(rows=[{
                "topic_id": 5,
                "topic_name": "Quantitative Aptitude",
                "subtopic_id": 8,
                "subtopic_name": "Percentages",
                "track_id": 1,
                "is_primary": True,
            }])
        if "select review_id, reviewer_id, decision, notes, reviewed_at" in query:
            return FakeResult({
                "review_id": 70,
                "reviewer_id": None,
                "decision": "PENDING",
                "notes": "MCQ_RECONSTRUCTION_IMPORT:v1:42:",
                "reviewed_at": None,
            })
        if "select h.previous_status, h.new_status, h.note" in query:
            return FakeResult(rows=[])
        if "from duplicate_matches dm" in query:
            return FakeResult(rows=[])
        if "select q.question_id, q.status" in query:
            return FakeResult({
                "question_id": 99,
                "status": "PUBLISHED",
                "latest_review_decision": "APPROVE",
            })
        if "select report_id, report_type, details, status" in query:
            return FakeResult(rows=[])
        raise AssertionError(f"Unexpected detail query: {statement}")


class ReconstructionReviewServiceTests(unittest.TestCase):
    def test_approval_records_admin_decision_without_publishing(self):
        connection = FakeReviewConnection()

        result = question_governance_service.decide_reconstruction_mcq_review(
            connection, 42, "APPROVE", 9001, "Content reviewed and approved."
        )

        self.assertEqual(result["decision"], "APPROVE")
        self.assertEqual(result["status"], "REVIEW")
        self.assertFalse(result["published"])
        self.assertEqual(connection.review["reviewer_id"], 9001)
        self.assertTrue(
            connection.review["notes"].startswith(
                "MCQ_RECONSTRUCTION_IMPORT:v1:42: import evidence"
            )
        )
        self.assertEqual(connection.status_history, [])
        self.assertFalse(
            any("update questions set status" in sql for sql, _ in connection.statements)
        )
        self.assertFalse(
            any("validate_question_for_publication" in sql for sql, _ in connection.statements)
        )

    def test_rejection_uses_existing_status_transition_history(self):
        connection = FakeReviewConnection()

        result = question_governance_service.decide_reconstruction_mcq_review(
            connection, 42, "REJECT", 9001, "The answer key needs correction."
        )

        self.assertEqual(result["status"], "REJECTED")
        self.assertEqual(connection.question["status"], "REJECTED")
        self.assertEqual(len(connection.status_history), 1)
        self.assertEqual(
            connection.status_history[0]["previous_status"],
            "REVIEW",
        )
        self.assertEqual(connection.status_history[0]["new_status"], "REJECTED")
        self.assertEqual(connection.status_history[0]["actor_user_id"], 9001)

    def test_detail_exposes_exact_canonical_blockers_and_governance_evidence(self):
        canonical_result = {
            "question_id": 42,
            "eligible": False,
            "blockers": [
                "Scraped-source authorization is not evidenced in source URL/notes.",
                "Question duplicates existing question 99.",
            ],
        }
        with patch(
            "app.routers.admin.evaluate_mock_eligibility",
            return_value=canonical_result,
        ):
            detail = admin._question_review_details(FakeDetailConnection(), 42)

        self.assertEqual(detail["content"]["correct_option_key"], "A")
        self.assertEqual(detail["options"][0]["option_key"], "A")
        self.assertEqual(detail["latest_review"]["decision"], "PENDING")
        self.assertEqual(detail["taxonomy"][0]["subtopic_name"], "Percentages")
        self.assertEqual(detail["mock_eligibility"], canonical_result)
        self.assertEqual(detail["provenance_state"], "AUTHORIZATION_NOT_EVIDENCED")
        self.assertEqual(detail["duplicate_state"], "UNRESOLVED")
        self.assertEqual(
            detail["publication_duplicate_blockers"][0]["question_id"],
            99,
        )
        self.assertIsNone(detail["publication_duplicate_blockers"][0]["resolution"])
        self.assertEqual(detail["publication_duplicate_blockers"][0]["matched_latest_review_decision"], "APPROVE")

    def test_pending_reconstruction_review_cannot_be_published(self):
        connection = FakeReviewConnection()

        with self.assertRaises(HTTPException) as raised:
            question_governance_service.transition_question_status(
                connection, 42, "PUBLISHED", 9001
            )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(connection.question["status"], "REVIEW")
        self.assertEqual(connection.status_history, [])

    def test_approved_reconstruction_review_uses_existing_publication_transition(self):
        connection = FakeReviewConnection()
        question_governance_service.decide_reconstruction_mcq_review(
            connection, 42, "APPROVE", 9001, "Content reviewed and approved."
        )

        with patch.object(
            question_governance_service,
            "validate_question_for_publication",
            return_value=[],
        ) as validate:
            result = question_governance_service.transition_question_status(
                connection, 42, "PUBLISHED", 9001
            )

        self.assertEqual(result["status"], "PUBLISHED")
        self.assertEqual(connection.question["status"], "PUBLISHED")
        validate.assert_called_once_with(connection, 42)
        self.assertEqual(connection.status_history[-1]["new_status"], "PUBLISHED")

    def test_non_mcq_cannot_use_reconstruction_review(self):
        connection = FakeReviewConnection(question_type="CODING")

        with self.assertRaises(HTTPException) as raised:
            question_governance_service.decide_reconstruction_mcq_review(
                connection, 42, "APPROVE", 9001, "Reviewed."
            )

        self.assertEqual(raised.exception.status_code, 409)

    def test_question_must_be_in_review_status(self):
        connection = FakeReviewConnection(status="ARCHIVED")

        with self.assertRaises(HTTPException) as raised:
            question_governance_service.decide_reconstruction_mcq_review(
                connection, 42, "APPROVE", 9001, "Reviewed."
            )

        self.assertEqual(raised.exception.status_code, 409)

    def test_non_reconstruction_or_already_decided_review_is_rejected(self):
        for review_decision, review_notes in (
            ("PENDING", "QUESTION_CLASSIFICATION:test"),
            ("APPROVE", "MCQ_RECONSTRUCTION_IMPORT:v1:42: reviewed"),
        ):
            with self.subTest(review_decision=review_decision):
                connection = FakeReviewConnection(
                    decision=review_decision,
                    notes=review_notes,
                )
                with self.assertRaises(HTTPException) as raised:
                    question_governance_service.decide_reconstruction_mcq_review(
                        connection, 42, "APPROVE", 9001, "Reviewed."
                    )
                self.assertEqual(raised.exception.status_code, 409)

    def test_concurrent_or_already_decided_update_is_rejected(self):
        connection = FakeReviewConnection(update_rowcount=0)

        with self.assertRaises(HTTPException) as raised:
            question_governance_service.decide_reconstruction_mcq_review(
                connection, 42, "APPROVE", 9001, "Reviewed."
            )

        self.assertEqual(raised.exception.status_code, 409)


class ReconstructionReviewRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.previous_overrides = dict(app.dependency_overrides)

    def tearDown(self):
        app.dependency_overrides.clear()
        app.dependency_overrides.update(self.previous_overrides)

    @staticmethod
    @contextmanager
    def _connection_context(connection):
        yield connection

    def test_student_cannot_submit_reconstruction_review(self):
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": 12,
            "role": "STUDENT",
            "is_active": True,
        }
        with patch("app.routers.admin.engine.begin") as begin:
            response = self.client.post(
                "/admin/questions/42/content-review",
                json={"decision": "APPROVE", "notes": "Reviewed and approved."},
            )

        self.assertEqual(response.status_code, 403)
        begin.assert_not_called()

    def test_admin_can_review_and_the_actor_is_taken_from_authentication(self):
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": 9001,
            "role": "ADMIN",
            "is_active": True,
        }
        connection = FakeReviewConnection()
        with patch(
            "app.routers.admin.engine.begin",
            return_value=self._connection_context(connection),
        ):
            response = self.client.post(
                "/admin/questions/42/content-review",
                json={"decision": "APPROVE", "notes": "Content reviewed and approved."},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["decision"], "APPROVE")
        self.assertFalse(response.json()["published"])
        self.assertEqual(connection.review["reviewer_id"], 9001)

    def test_admin_can_view_reconstruction_review_detail(self):
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": 9001,
            "role": "ADMIN",
            "is_active": True,
        }
        detail = {
            "question_id": 42,
            "latest_review": {
                "decision": "PENDING",
                "notes": "MCQ_RECONSTRUCTION_IMPORT:v1:42:",
            },
            "mock_eligibility": {
                "eligible": False,
                "blockers": ["Question status is REVIEW, not PUBLISHED."],
            },
        }
        with (
            patch("app.routers.admin._question_review_details", return_value=detail),
            patch(
                "app.routers.admin.engine.connect",
                return_value=self._connection_context(object()),
            ),
        ):
            response = self.client.get("/admin/questions/42")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["latest_review"]["decision"], "PENDING")
        self.assertFalse(response.json()["mock_eligibility"]["eligible"])

    def test_admin_can_read_the_reconstruction_queue(self):
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": 9001,
            "role": "ADMIN",
            "is_active": True,
        }
        connection = FakeReviewConnection()
        candidate = {
            "question_id": 42,
            "taxonomy": [{"topic_name": "Quantitative Aptitude"}],
            "difficulty": "MEDIUM",
            "source": {"source_type": "SCRAPED"},
            "provenance_state": "AUTHORIZATION_NOT_EVIDENCED",
            "source_traceability_state": "PRESENT",
            "duplicate_state": "UNRESOLVED",
            "duplicate_matches": [],
            "publication_duplicate_blockers": [],
            "mock_eligibility": {
                "eligible": False,
                "blockers": ["Scraped-source authorization is not evidenced."],
            },
        }
        with (
            patch(
                "app.routers.admin.engine.connect",
                return_value=self._connection_context(connection),
            ),
            patch(
                "app.routers.admin._question_review_details",
                return_value=candidate,
            ),
        ):
            response = self.client.get(
                "/admin/questions/reconstruction-review-queue"
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()[0]["question_id"], 42)
        self.assertEqual(
            response.json()[0]["provenance_state"],
            "AUTHORIZATION_NOT_EVIDENCED",
        )

    def test_existing_classification_review_route_still_accepts_its_queue(self):
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": 9001,
            "role": "ADMIN",
            "is_active": True,
        }
        connection = FakeReviewConnection(
            notes="QUESTION_CLASSIFICATION:test",
        )
        with patch(
            "app.routers.admin.engine.begin",
            return_value=self._connection_context(connection),
        ):
            response = self.client.post(
                "/admin/questions/42/difficulty-review",
                json={
                    "decision": "NEEDS_EDIT",
                    "reviewer_notes": "Please reassess the proposed difficulty.",
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["decision"], "NEEDS_EDIT")
        self.assertEqual(connection.question["status"], "REVIEW")


if __name__ == "__main__":
    unittest.main()
