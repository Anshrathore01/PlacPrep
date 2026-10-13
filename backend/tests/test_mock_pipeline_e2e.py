import hashlib
import json
import os
import unittest
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth.dependencies import get_current_user, get_optional_current_user
from app.database import engine
from app.main import app
from app.services import blueprint_service, question_governance_service
from app.services.mock_eligibility_service import (
    MOCK_ELIGIBLE_QUESTION_SQL,
    count_mock_eligible,
    evaluate_mock_eligibility,
)


class IsolatedMockPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.getenv("PLACEMENT_RUN_ISOLATED_PIPELINE") != "1":
            raise unittest.SkipTest("Run through the isolated MySQL pipeline runner.")
        if (
            engine.url.database != "placement_mock_pipeline_test"
            or engine.url.host not in {"127.0.0.1", "localhost", "::1"}
        ):
            raise RuntimeError(
                "Refusing integration tests outside loopback "
                "placement_mock_pipeline_test."
            )
        cls.client = TestClient(app)

    def setUp(self):
        self.previous_overrides = dict(app.dependency_overrides)
        self.suffix = uuid.uuid4().hex
        self.email = f"mock-pipeline-admin-{self.suffix}@example.test"
        self.blueprint_id = None
        self.mock_test_id = None
        with engine.begin() as connection:
            user_result = connection.execute(
                text("""
                    INSERT INTO users (
                        email, password_hash, display_name, role, is_active
                    )
                    VALUES (
                        :email, 'test-only-hash', 'Synthetic Pipeline Admin',
                        'ADMIN', TRUE
                    )
                """),
                {"email": self.email},
            )
            self.admin = {
                "user_id": int(user_result.lastrowid),
                "role": "ADMIN",
                "is_active": True,
            }
            track_result = connection.execute(
                text("INSERT INTO tracks (track_name) VALUES (:name)"),
                {"name": f"Pipeline Test Track {self.suffix}"},
            )
            self.track_id = int(track_result.lastrowid)
            topic_result = connection.execute(
                text("""
                    INSERT INTO topics (track_id, topic_name, display_order)
                    VALUES (:track_id, :name, 1)
                """),
                {
                    "track_id": self.track_id,
                    "name": f"Pipeline Test Topic {self.suffix}",
                },
            )
            self.topic_id = int(topic_result.lastrowid)
            subtopic_result = connection.execute(
                text("""
                    INSERT INTO subtopics (topic_id, subtopic_name, display_order)
                    VALUES (:topic_id, :name, 1)
                """),
                {
                    "topic_id": self.topic_id,
                    "name": f"Pipeline Test Subtopic {self.suffix}",
                },
            )
            self.subtopic_id = int(subtopic_result.lastrowid)
            source_result = connection.execute(
                text("""
                    INSERT INTO sources (source_name, source_type, source_notes)
                    VALUES (:name, 'CUSTOM', 'Synthetic test fixture only.')
                """),
                {"name": f"Pipeline Test Source {self.suffix}"},
            )
            self.source_id = int(source_result.lastrowid)

            question_text = "TEST ONLY: Which data structure uses FIFO ordering?"
            question_result = connection.execute(
                text("""
                    INSERT INTO questions (
                        source_id, source_question_number, question_type,
                        track_id, title, difficulty, status, content_hash,
                        source_metadata
                    )
                    VALUES (
                        :source_id, :source_question_number, 'MCQ',
                        :track_id, :title, 'EASY', 'DRAFT', :content_hash,
                        JSON_OBJECT('synthetic_test_fixture', TRUE)
                    )
                """),
                {
                    "source_id": self.source_id,
                    "source_question_number": 1,
                    "track_id": self.track_id,
                    "title": question_text,
                    "content_hash": hashlib.sha256(
                        (self.suffix + question_text).encode()
                    ).hexdigest(),
                },
            )
            self.question_id = int(question_result.lastrowid)
            connection.execute(
                text("""
                    INSERT INTO question_subtopics (
                        question_id, subtopic_id, is_primary
                    )
                    VALUES (:question_id, :subtopic_id, TRUE)
                """),
                {
                    "question_id": self.question_id,
                    "subtopic_id": self.subtopic_id,
                },
            )
            connection.execute(
                text("""
                    INSERT INTO mcq_questions (
                        question_id, question_text, explanation,
                        correct_option_key, is_multiple_correct
                    )
                    VALUES (
                        :question_id, :question_text, :explanation,
                        'A', FALSE
                    )
                """),
                {
                    "question_id": self.question_id,
                    "question_text": question_text,
                    "explanation": "A queue processes items in first-in, first-out order.",
                },
            )
            for order, (key, option_text) in enumerate(
                (
                    ("A", "Queue"),
                    ("B", "Stack"),
                    ("C", "Heap"),
                    ("D", "Hash table"),
                ),
                start=1,
            ):
                connection.execute(
                    text("""
                        INSERT INTO mcq_options (
                            question_id, option_key, option_text, display_order
                        )
                        VALUES (
                            :question_id, :option_key, :option_text, :display_order
                        )
                    """),
                    {
                        "question_id": self.question_id,
                        "option_key": key,
                        "option_text": option_text,
                        "display_order": order,
                    },
                )
            question_governance_service.transition_question_status(
                connection,
                self.question_id,
                "REVIEW",
                self.admin["user_id"],
                note="Synthetic test question queued for content review.",
            )
            review_result = connection.execute(
                text("""
                    INSERT INTO question_reviews (
                        question_id, reviewer_id, decision, notes
                    )
                    VALUES (
                        :question_id, :reviewer_id, 'PENDING', :notes
                    )
                """),
                {
                    "question_id": self.question_id,
                    "reviewer_id": self.admin["user_id"],
                    "notes": (
                        "MCQ_RECONSTRUCTION_IMPORT:v1:"
                        f"{self.question_id}: synthetic fixture"
                    ),
                },
            )
            self.review_id = int(review_result.lastrowid)

        app.dependency_overrides[get_current_user] = lambda: self.admin
        app.dependency_overrides[get_optional_current_user] = lambda: self.admin

    def tearDown(self):
        app.dependency_overrides.clear()
        app.dependency_overrides.update(self.previous_overrides)
        if engine.url.database != "placement_mock_pipeline_test":
            raise RuntimeError("Refusing integration fixture cleanup outside the test database.")
        with engine.begin() as connection:
            if self.mock_test_id is not None:
                connection.execute(
                    text("""
                        DELETE FROM mock_test_questions
                        WHERE mock_test_id = :mock_test_id
                    """),
                    {"mock_test_id": self.mock_test_id},
                )
                connection.execute(
                    text("""
                        DELETE FROM mock_tests WHERE mock_test_id = :mock_test_id
                    """),
                    {"mock_test_id": self.mock_test_id},
                )
            if self.blueprint_id is not None:
                connection.execute(
                    text("""
                        DELETE FROM test_blueprint_rules
                        WHERE blueprint_id = :blueprint_id
                    """),
                    {"blueprint_id": self.blueprint_id},
                )
                connection.execute(
                    text("""
                        DELETE FROM test_blueprints
                        WHERE blueprint_id = :blueprint_id
                    """),
                    {"blueprint_id": self.blueprint_id},
                )
            connection.execute(
                text("DELETE FROM question_reviews WHERE question_id = :id"),
                {"id": self.question_id},
            )
            connection.execute(
                text("DELETE FROM question_status_history WHERE question_id = :id"),
                {"id": self.question_id},
            )
            connection.execute(
                text("DELETE FROM question_reports WHERE question_id = :id"),
                {"id": self.question_id},
            )
            connection.execute(
                text("""
                    DELETE FROM duplicate_matches
                    WHERE question_id_a = :id OR question_id_b = :id
                """),
                {"id": self.question_id},
            )
            connection.execute(
                text("DELETE FROM mcq_options WHERE question_id = :id"),
                {"id": self.question_id},
            )
            connection.execute(
                text("DELETE FROM mcq_questions WHERE question_id = :id"),
                {"id": self.question_id},
            )
            connection.execute(
                text("DELETE FROM question_subtopics WHERE question_id = :id"),
                {"id": self.question_id},
            )
            connection.execute(
                text("DELETE FROM questions WHERE question_id = :id"),
                {"id": self.question_id},
            )
            connection.execute(
                text("DELETE FROM sources WHERE source_id = :id"),
                {"id": self.source_id},
            )
            connection.execute(
                text("DELETE FROM subtopics WHERE subtopic_id = :id"),
                {"id": self.subtopic_id},
            )
            connection.execute(
                text("DELETE FROM topics WHERE topic_id = :id"),
                {"id": self.topic_id},
            )
            connection.execute(
                text("DELETE FROM tracks WHERE track_id = :id"),
                {"id": self.track_id},
            )
            connection.execute(
                text("DELETE FROM users WHERE user_id = :id"),
                {"id": self.admin["user_id"]},
            )

    def _assert_negative_gate(self, statement, params, expected_blocker):
        with engine.connect() as connection:
            transaction = connection.begin()
            savepoint = connection.begin_nested()
            connection.execute(text(statement), params)
            result = evaluate_mock_eligibility(connection, self.question_id)
            self.assertFalse(result["eligible"])
            self.assertTrue(
                any(expected_blocker in blocker for blocker in result["blockers"]),
                result["blockers"],
            )
            savepoint.rollback()
            transaction.rollback()

    def _assert_governance_does_not_block(self, statement, params):
        with engine.connect() as connection:
            transaction = connection.begin()
            savepoint = connection.begin_nested()
            connection.execute(text(statement), params)
            result = evaluate_mock_eligibility(connection, self.question_id)
            self.assertTrue(result["eligible"], result["blockers"])
            savepoint.rollback()
            transaction.rollback()

    def test_synthetic_mcq_completes_governed_mock_pipeline(self):
        review_detail = self.client.get(f"/admin/questions/{self.question_id}")
        self.assertEqual(review_detail.status_code, 200, review_detail.text)
        self.assertEqual(
            review_detail.json()["latest_review"]["decision"], "PENDING"
        )
        self.assertEqual(
            review_detail.json()["content"]["question_text"],
            "TEST ONLY: Which data structure uses FIFO ordering?",
        )
        self.assertTrue(review_detail.json()["mock_eligibility"]["eligible"])
        with engine.connect() as connection:
            prepublication_selection = blueprint_service.select_filtered_questions(
                connection,
                "MCQ",
                self.track_id,
                "EASY",
                self.topic_id,
                self.subtopic_id,
                1,
            )
        self.assertEqual(prepublication_selection, [self.question_id])

        no_auth_overrides = dict(app.dependency_overrides)
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_optional_current_user, None)
        unauthenticated = self.client.post(
            f"/admin/questions/{self.question_id}/content-review",
            json={"decision": "APPROVE", "notes": "Reviewed synthetic content."},
        )
        app.dependency_overrides.clear()
        app.dependency_overrides.update(no_auth_overrides)
        self.assertIn(unauthenticated.status_code, {401, 403})

        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": self.admin["user_id"] + 10000,
            "role": "STUDENT",
            "is_active": True,
        }
        student_attempt = self.client.post(
            f"/admin/questions/{self.question_id}/content-review",
            json={"decision": "APPROVE", "notes": "Reviewed synthetic content."},
        )
        self.assertEqual(student_attempt.status_code, 403)
        app.dependency_overrides[get_current_user] = lambda: self.admin

        with engine.begin() as connection:
            connection.execute(
                text("""
                    UPDATE question_reviews
                    SET notes = 'QUESTION_CLASSIFICATION: synthetic wrong review'
                    WHERE review_id = :review_id
                """),
                {"review_id": self.review_id},
            )
        wrong_type = self.client.post(
            f"/admin/questions/{self.question_id}/content-review",
            json={"decision": "APPROVE", "notes": "Reviewed synthetic content."},
        )
        self.assertEqual(wrong_type.status_code, 409)
        with engine.begin() as connection:
            connection.execute(
                text("""
                    UPDATE question_reviews
                    SET notes = :notes
                    WHERE review_id = :review_id
                """),
                {
                    "review_id": self.review_id,
                    "notes": (
                        "MCQ_RECONSTRUCTION_IMPORT:v1:"
                        f"{self.question_id}: synthetic fixture"
                    ),
                },
            )

        pending_publish = self.client.post(
            f"/admin/questions/{self.question_id}/publish"
        )
        self.assertEqual(pending_publish.status_code, 409)

        approved = self.client.post(
            f"/admin/questions/{self.question_id}/content-review",
            json={
                "decision": "APPROVE",
                "notes": "Content manually reviewed and approved for publication.",
            },
        )
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual(approved.json()["decision"], "APPROVE")
        self.assertFalse(approved.json()["published"])
        self.assertEqual(approved.json()["status"], "REVIEW")

        with engine.connect() as connection:
            review = connection.execute(
                text("""
                    SELECT decision, reviewer_id, notes
                    FROM question_reviews
                    WHERE review_id = :review_id
                """),
                {"review_id": self.review_id},
            ).mappings().one()
            status = connection.execute(
                text("SELECT status FROM questions WHERE question_id = :id"),
                {"id": self.question_id},
            ).scalar_one()
            history_count = connection.execute(
                text("""
                    SELECT COUNT(*)
                    FROM question_status_history
                    WHERE question_id = :id
                """),
                {"id": self.question_id},
            ).scalar_one()
            errors = question_governance_service.validate_question_for_publication(
                connection, self.question_id
            )
        self.assertEqual(review["decision"], "APPROVE")
        self.assertEqual(review["reviewer_id"], self.admin["user_id"])
        self.assertIn("MCQ_RECONSTRUCTION_IMPORT:v1:", review["notes"])
        self.assertEqual(status, "REVIEW")
        self.assertEqual(history_count, 1)
        self.assertEqual(errors, [])

        with engine.begin() as connection:
            transition = question_governance_service.transition_question_status(
                connection,
                self.question_id,
                "PUBLISHED",
                self.admin["user_id"],
                note="Synthetic test publication after approved content review.",
            )
        self.assertEqual(transition["status"], "PUBLISHED")

        with engine.connect() as connection:
            evaluation = evaluate_mock_eligibility(connection, self.question_id)
            canonical_sql = connection.execute(
                text(f"""
                    SELECT EXISTS (
                        SELECT 1 FROM questions q
                        WHERE q.question_id = :question_id
                          AND ({MOCK_ELIGIBLE_QUESTION_SQL})
                    )
                """),
                {"question_id": self.question_id},
            ).scalar_one()
            eligible_count = count_mock_eligible(connection, "MCQ")
        self.assertTrue(evaluation["eligible"], evaluation["blockers"])
        self.assertTrue(canonical_sql)
        self.assertEqual(eligible_count, 1)

        with engine.connect() as connection:
            filtered_selection = blueprint_service.select_filtered_questions(
                connection,
                "MCQ",
                self.track_id,
                "EASY",
                self.topic_id,
                self.subtopic_id,
                1,
            )
        self.assertEqual(filtered_selection, [self.question_id])

        blueprint_response = self.client.post(
            "/admin/blueprints",
            json={
                "blueprint_name": f"TEST ONLY {self.suffix}",
                "track_id": self.track_id,
                "duration_seconds": 60,
            },
        )
        self.assertEqual(blueprint_response.status_code, 200, blueprint_response.text)
        blueprint_id = blueprint_response.json()["blueprint_id"]
        self.blueprint_id = blueprint_id
        rule_response = self.client.post(
            f"/admin/blueprints/{blueprint_id}/rules",
            json={
                "section_name": "Synthetic MCQ",
                "section_order": 1,
                "is_required": True,
                "track_id": self.track_id,
                "topic_id": self.topic_id,
                "subtopic_id": self.subtopic_id,
                "question_type": "MCQ",
                "difficulty": "EASY",
                "question_count": 1,
                "points": "1.00",
                "selection_strategy": "QUESTION_ID_ASC",
            },
        )
        self.assertEqual(rule_response.status_code, 200, rule_response.text)
        activation = self.client.post(
            f"/admin/blueprints/{blueprint_id}/activate"
        )
        self.assertEqual(activation.status_code, 200, activation.text)

        preview = self.client.get(
            f"/admin/blueprints/{blueprint_id}/preview"
        )
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertTrue(preview.json()["ready_for_mock"], preview.json()["errors"])
        self.assertEqual(preview.json()["rules"][0]["eligible_count"], 1)
        with engine.connect() as connection:
            selected_blueprint, selections = blueprint_service.select_blueprint_questions(
                connection, blueprint_id
            )
        self.assertEqual(selected_blueprint["blueprint_id"], blueprint_id)
        self.assertEqual(selections[0]["question_ids"], [self.question_id])

        with engine.begin() as connection:
            mock_test = blueprint_service.create_mock_test_from_blueprint(
                connection,
                blueprint_id,
                "Synthetic pipeline test",
                "MOCK",
                self.admin["user_id"],
            )
        mock_test_id = int(mock_test["mock_test_id"])
        self.mock_test_id = mock_test_id
        with engine.connect() as connection:
            persisted = connection.execute(
                text("""
                    SELECT sequence_no, question_id, points
                    FROM mock_test_questions
                    WHERE mock_test_id = :mock_test_id
                    ORDER BY sequence_no
                """),
                {"mock_test_id": mock_test_id},
            ).mappings().all()
        self.assertEqual(len(persisted), 1)
        self.assertEqual(int(persisted[0]["sequence_no"]), 1)
        self.assertEqual(int(persisted[0]["question_id"]), self.question_id)

        reopened_first = self.client.get(f"/mock-tests/{mock_test_id}")
        reopened_second = self.client.get(f"/mock-tests/{mock_test_id}")
        self.assertEqual(reopened_first.status_code, 200, reopened_first.text)
        self.assertEqual(reopened_second.status_code, 200, reopened_second.text)
        question_ids_first = [
            item["question_id"] for item in reopened_first.json()["questions"]
        ]
        question_ids_second = [
            item["question_id"] for item in reopened_second.json()["questions"]
        ]
        self.assertEqual(question_ids_first, [self.question_id])
        self.assertEqual(question_ids_second, question_ids_first)

        self._assert_governance_does_not_block(
            "UPDATE questions SET status = 'REVIEW' WHERE question_id = :id",
            {"id": self.question_id},
        )
        with engine.connect() as connection:
            transaction = connection.begin()
            savepoint = connection.begin_nested()
            connection.execute(
                text("""
                    UPDATE question_reviews
                    SET decision = 'PENDING', reviewed_at = NULL
                    WHERE review_id = :review_id
                """),
                {"review_id": self.review_id},
            )
            pending_result = evaluate_mock_eligibility(
                connection, self.question_id
            )
            self.assertTrue(pending_result["eligible"], pending_result["blockers"])
            savepoint.rollback()
            transaction.rollback()

        self._assert_governance_does_not_block(
            "UPDATE sources SET source_type = 'SCRAPED', "
            "source_url = 'https://example.test/synthetic', source_notes = '' "
            "WHERE source_id = :id",
            {"id": self.source_id},
        )

        with engine.connect() as connection:
            transaction = connection.begin()
            savepoint = connection.begin_nested()
            other = connection.execute(
                text("""
                    INSERT INTO questions (
                        source_id, question_type, track_id, title, difficulty,
                        status, content_hash
                    )
                    VALUES (
                        :source_id, 'MCQ', :track_id, 'Distinct duplicate peer',
                        'EASY', 'DRAFT', :content_hash
                    )
                """),
                {
                    "source_id": self.source_id,
                    "track_id": self.track_id,
                    "content_hash": hashlib.sha256(
                        (self.suffix + "peer").encode()
                    ).hexdigest(),
                },
            )
            connection.execute(
                text("""
                    INSERT INTO duplicate_matches (
                        question_id_a, question_id_b, similarity_score,
                        match_type, resolution
                    )
                    VALUES (:a, :b, 1.00000, 'EXACT', 'PENDING')
                """),
                {"a": self.question_id, "b": int(other.lastrowid)},
            )
            duplicate_result = evaluate_mock_eligibility(
                connection, self.question_id
            )
            self.assertTrue(duplicate_result["eligible"], duplicate_result["blockers"])
            savepoint.rollback()
            transaction.rollback()

        with engine.connect() as connection:
            transaction = connection.begin()
            savepoint = connection.begin_nested()
            connection.execute(
                text("""
                    DELETE FROM mcq_options
                    WHERE question_id = :question_id AND option_key = 'D'
                """),
                {"question_id": self.question_id},
            )
            option_result = evaluate_mock_eligibility(
                connection, self.question_id
            )
            self.assertFalse(option_result["eligible"])
            self.assertTrue(
                any(
                    "MCQs must have exactly 4 or 5 options." in blocker
                    for blocker in option_result["blockers"]
                ),
                option_result["blockers"],
            )
            savepoint.rollback()
            transaction.rollback()

        self._assert_negative_gate(
            "UPDATE mcq_questions SET correct_option_key = 'Z' "
            "WHERE question_id = :id",
            {"id": self.question_id},
            "correct option key must match an existing option",
        )

        with engine.connect() as connection:
            final_evaluation = evaluate_mock_eligibility(
                connection, self.question_id
            )
            self.assertTrue(
                final_evaluation["eligible"], final_evaluation["blockers"]
            )
            self.assertEqual(
                count_mock_eligible(connection, "MCQ"),
                1,
            )

        print("PIPELINE_FIXTURE_RESULT=" + json.dumps({
            "database": engine.url.database,
            "question_id": self.question_id,
            "lifecycle": [
                "REVIEW",
                "APPROVE",
                "PUBLISHED",
                "ELIGIBLE",
                "SELECTED",
                "MOCK_CREATED",
            ],
            "evaluator": evaluation["eligible"],
            "canonical_sql": bool(canonical_sql),
            "count": eligible_count,
            "generic_selector": filtered_selection,
            "blueprint_ready": preview.json()["ready_for_mock"],
            "blueprint_selection": selections[0]["question_ids"],
            "mock_test_id": mock_test_id,
            "persisted_order": [
                {
                    "sequence_no": int(row["sequence_no"]),
                    "question_id": int(row["question_id"]),
                }
                for row in persisted
            ],
            "reopen_same_questions": question_ids_second == question_ids_first,
            "negative_cases": {
                "review_status_ignored": True,
                "pending_review_ignored": True,
                "provenance_retained_but_not_blocking": True,
                "duplicate_governance_ignored": True,
                "invalid_options": True,
                "invalid_answer": True,
            },
        }, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
