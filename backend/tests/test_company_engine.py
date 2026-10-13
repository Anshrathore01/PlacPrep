import unittest
import uuid
from datetime import date, datetime

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth.dependencies import get_current_user, get_optional_current_user
from app.database import engine
from app.main import app
from app.services import blueprint_service
from app.services import question_governance_service
from app.services.mock_eligibility_service import is_mock_eligible


class CompanyEngineEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.previous_overrides = dict(app.dependency_overrides)
        app.dependency_overrides[get_current_user] = lambda: self.current_user
        app.dependency_overrides[get_optional_current_user] = (
            lambda: self.current_user
        )
        self.company_ids = []
        self.blueprint_ids = []
        self.question_ids = []
        self.mock_test_ids = []
        self.attempt_ids = []
        self.user_ids = []
        self.addCleanup(self._cleanup)
        self._create_fixture_users()

    def _create_fixture_users(self):
        suffix = uuid.uuid4().hex
        self.student_email = f"company-student-{suffix}@example.test"
        self.admin_email = f"company-admin-{suffix}@example.test"
        with engine.begin() as connection:
            for email, role in (
                (self.student_email, "STUDENT"),
                (self.admin_email, "ADMIN"),
            ):
                result = connection.execute(
                    text("""
                        INSERT INTO users (
                            email, password_hash, display_name, role, is_active
                        )
                        VALUES (
                            :email, 'unused-test-hash', 'Company Engine Test',
                            :role, 1
                        )
                    """),
                    {"email": email, "role": role},
                )
                self.user_ids.append(int(result.lastrowid))
        self.student = {"user_id": self.user_ids[0], "role": "STUDENT"}
        self.admin = {"user_id": self.user_ids[1], "role": "ADMIN"}
        self.current_user = self.admin

    def _create_question(self, connection, source_id, topic_id, subtopic_id, title):
        track_id = connection.execute(
            text("SELECT track_id FROM topics WHERE topic_id = :topic_id"),
            {"topic_id": topic_id},
        ).scalar_one()
        result = connection.execute(
            text("""
                INSERT INTO questions (
                    source_id, question_type, track_id, title, difficulty,
                    status, content_hash
                )
                VALUES (
                    :source_id, 'MCQ', :track_id, :title, 'EASY',
                    'DRAFT', :content_hash
                )
            """),
            {
                "source_id": source_id,
                "track_id": track_id,
                "title": title,
                "content_hash": uuid.uuid4().hex + uuid.uuid4().hex,
            },
        )
        question_id = int(result.lastrowid)
        self.question_ids.append(question_id)
        connection.execute(
            text("""
                UPDATE questions
                SET source_question_number = :source_question_number,
                    source_metadata = JSON_OBJECT(
                        'test_fixture', TRUE,
                        'source_question_number', :source_question_number
                    )
                WHERE question_id = :question_id
            """),
            {
                "question_id": question_id,
                "source_question_number": question_id,
            },
        )
        connection.execute(
            text("""
                INSERT INTO question_subtopics (
                    question_id, subtopic_id, is_primary
                )
                VALUES (:question_id, :subtopic_id, 1)
            """),
            {"question_id": question_id, "subtopic_id": subtopic_id},
        )
        connection.execute(
            text("""
                INSERT INTO mcq_questions (
                    question_id, question_text, correct_option_key,
                    is_multiple_correct
                )
                VALUES (:question_id, :question_text, 'A', FALSE)
            """),
            {
                "question_id": question_id,
                "question_text": f"{title}?",
            },
        )
        for order, (key, option_text) in enumerate(
            (("A", "Correct"), ("B", "Option B"), ("C", "Option C"), ("D", "Option D")),
            start=1,
        ):
            connection.execute(
                text("""
                    INSERT INTO mcq_options (
                        question_id, option_key, option_text, display_order
                    )
                    VALUES (:question_id, :option_key, :option_text, :display_order)
                """),
                {
                    "question_id": question_id,
                    "option_key": key,
                    "option_text": option_text,
                    "display_order": order,
                },
            )
        return question_id

    def _cleanup(self):
        app.dependency_overrides.clear()
        app.dependency_overrides.update(self.previous_overrides)
        with engine.begin() as connection:
            if self.attempt_ids:
                connection.execute(
                    text("DELETE FROM attempt_answers WHERE attempt_id IN :ids"),
                    {"ids": tuple(self.attempt_ids)},
                )
                connection.execute(
                    text("DELETE FROM attempts WHERE attempt_id IN :ids"),
                    {"ids": tuple(self.attempt_ids)},
                )
            if self.mock_test_ids:
                connection.execute(
                    text("DELETE FROM mock_test_questions WHERE mock_test_id IN :ids"),
                    {"ids": tuple(self.mock_test_ids)},
                )
                connection.execute(
                    text("DELETE FROM mock_tests WHERE mock_test_id IN :ids"),
                    {"ids": tuple(self.mock_test_ids)},
                )
            if self.blueprint_ids:
                connection.execute(
                    text("DELETE FROM test_blueprint_rules WHERE blueprint_id IN :ids"),
                    {"ids": tuple(self.blueprint_ids)},
                )
                connection.execute(
                    text("DELETE FROM test_blueprints WHERE blueprint_id IN :ids"),
                    {"ids": tuple(self.blueprint_ids)},
                )
            if self.question_ids:
                connection.execute(
                    text("DELETE FROM question_reviews WHERE question_id IN :ids"),
                    {"ids": tuple(self.question_ids)},
                )
                connection.execute(
                    text("DELETE FROM question_status_history WHERE question_id IN :ids"),
                    {"ids": tuple(self.question_ids)},
                )
                connection.execute(
                    text("DELETE FROM question_subtopics WHERE question_id IN :ids"),
                    {"ids": tuple(self.question_ids)},
                )
                connection.execute(
                    text("DELETE FROM mcq_options WHERE question_id IN :ids"),
                    {"ids": tuple(self.question_ids)},
                )
                connection.execute(
                    text("DELETE FROM mcq_questions WHERE question_id IN :ids"),
                    {"ids": tuple(self.question_ids)},
                )
                connection.execute(
                    text("DELETE FROM questions WHERE question_id IN :ids"),
                    {"ids": tuple(self.question_ids)},
                )
            if self.company_ids:
                connection.execute(
                    text("DELETE FROM companies WHERE company_id IN :ids"),
                    {"ids": tuple(self.company_ids)},
                )
            if self.user_ids:
                connection.execute(
                    text("DELETE FROM users WHERE user_id IN :ids"),
                    {"ids": tuple(self.user_ids)},
                )

    def _set_student(self):
        self.current_user = self.student

    def _set_admin(self):
        self.current_user = self.admin

    def _start_answer_submit(self, mock_test_id, question_ids):
        started = self.client.post(
            "/attempts", json={"mock_test_id": mock_test_id}
        )
        self.assertEqual(started.status_code, 201, started.text)
        attempt_id = started.json()["attempt_id"]
        self.attempt_ids.append(attempt_id)
        for question_id in question_ids:
            with engine.connect() as connection:
                correct_option_key = connection.execute(
                    text("""
                        SELECT correct_option_key
                        FROM mcq_questions
                        WHERE question_id = :question_id
                    """),
                    {"question_id": question_id},
                ).scalar_one()
            saved = self.client.post(
                f"/attempts/{attempt_id}/answers",
                json={
                    "question_id": question_id,
                    "selected_option_key": correct_option_key,
                    "time_spent_seconds": 12,
                },
            )
            self.assertEqual(saved.status_code, 200, saved.text)
        submitted = self.client.post(f"/attempts/{attempt_id}/submit")
        self.assertEqual(submitted.status_code, 200, submitted.text)
        self.assertEqual(submitted.json()["attempt_id"], attempt_id)
        self.assertEqual(submitted.json()["status"], "SUBMITTED")
        self.assertIn("score", submitted.json())
        self.assertEqual(
            float(submitted.json()["attempt"]["score"]),
            float(len(question_ids)),
        )
        fetched = self.client.get(f"/attempts/{attempt_id}")
        self.assertEqual(fetched.status_code, 200, fetched.text)
        self.assertEqual(fetched.json()["attempt"]["attempt_id"], attempt_id)
        self.assertEqual(fetched.json()["attempt"]["status"], "SUBMITTED")
        return attempt_id

    def test_canonical_mock_eligibility_accepts_four_and_five_options_and_blocks_invalid_mcqs(self):
        suffix = uuid.uuid4().hex
        with engine.begin() as connection:
            taxonomy = connection.execute(
                text("""
                    SELECT t.topic_id, t.track_id, s.subtopic_id
                    FROM topics t
                    JOIN subtopics s ON s.topic_id = t.topic_id
                    WHERE t.topic_id = 1
                    ORDER BY s.subtopic_id
                    LIMIT 1
                """)
            ).mappings().one()
            source_id = int(
                connection.execute(
                    text("SELECT source_id FROM sources WHERE source_type = 'CUSTOM' ORDER BY source_id LIMIT 1")
                ).scalar_one()
            )

            valid_four = self._create_question(
                connection,
                source_id,
                int(taxonomy["topic_id"]),
                int(taxonomy["subtopic_id"]),
                f"Eligibility four option {suffix}",
            )
            valid_five = self._create_question(
                connection,
                source_id,
                int(taxonomy["topic_id"]),
                int(taxonomy["subtopic_id"]),
                f"Eligibility five option {suffix}",
            )
            connection.execute(
                text("""
                    INSERT INTO mcq_options (
                        question_id, option_key, option_text, display_order
                    )
                    VALUES (:question_id, 'E', 'Option E', 5)
                """),
                {"question_id": valid_five},
            )
            invalid_questions = {
                "missing_options": self._create_question(
                    connection, source_id, int(taxonomy["topic_id"]),
                    int(taxonomy["subtopic_id"]), f"Missing options {suffix}",
                ),
                "invalid_key": self._create_question(
                    connection, source_id, int(taxonomy["topic_id"]),
                    int(taxonomy["subtopic_id"]), f"Invalid answer key {suffix}",
                ),
                "missing_key": self._create_question(
                    connection, source_id, int(taxonomy["topic_id"]),
                    int(taxonomy["subtopic_id"]), f"Missing answer key {suffix}",
                ),
                "multiple_correct": self._create_question(
                    connection, source_id, int(taxonomy["topic_id"]),
                    int(taxonomy["subtopic_id"]), f"Multiple correct {suffix}",
                ),
                "missing_difficulty": self._create_question(
                    connection, source_id, int(taxonomy["topic_id"]),
                    int(taxonomy["subtopic_id"]), f"Missing difficulty {suffix}",
                ),
                "missing_mapping": self._create_question(
                    connection, source_id, int(taxonomy["topic_id"]),
                    int(taxonomy["subtopic_id"]), f"Missing mapping {suffix}",
                ),
                "archived": self._create_question(
                    connection, source_id, int(taxonomy["topic_id"]),
                    int(taxonomy["subtopic_id"]), f"Archived {suffix}",
                ),
                "open_report": self._create_question(
                    connection, source_id, int(taxonomy["topic_id"]),
                    int(taxonomy["subtopic_id"]), f"Open report {suffix}",
                ),
                "pending_review": self._create_question(
                    connection, source_id, int(taxonomy["topic_id"]),
                    int(taxonomy["subtopic_id"]), f"Pending review {suffix}",
                ),
                "unresolved_duplicate": self._create_question(
                    connection, source_id, int(taxonomy["topic_id"]),
                    int(taxonomy["subtopic_id"]), f"Unresolved duplicate {suffix}",
                ),
                "duplicate_hash": self._create_question(
                    connection, source_id, int(taxonomy["topic_id"]),
                    int(taxonomy["subtopic_id"]), f"Duplicate hash {suffix}",
                ),
                "duplicate_hash_peer": self._create_question(
                    connection, source_id, int(taxonomy["topic_id"]),
                    int(taxonomy["subtopic_id"]), f"Duplicate hash peer {suffix}",
                ),
                "duplicate_text": self._create_question(
                    connection, source_id, int(taxonomy["topic_id"]),
                    int(taxonomy["subtopic_id"]), f"Duplicate text {suffix}",
                ),
                "duplicate_text_peer": self._create_question(
                    connection, source_id, int(taxonomy["topic_id"]),
                    int(taxonomy["subtopic_id"]), f"Duplicate text peer {suffix}",
                ),
                "scraped_source": self._create_question(
                    connection, source_id, int(taxonomy["topic_id"]),
                    int(taxonomy["subtopic_id"]), f"Scraped source {suffix}",
                ),
            }
            for question_id in (valid_four, valid_five, *invalid_questions.values()):
                connection.execute(
                    text("""
                        UPDATE questions
                        SET status = 'PUBLISHED'
                        WHERE question_id = :question_id
                    """),
                    {"question_id": question_id},
                )
            connection.execute(
                text("DELETE FROM mcq_options WHERE question_id=:id AND option_key='D'"),
                {"id": invalid_questions["missing_options"]},
            )
            connection.execute(
                text("UPDATE mcq_questions SET correct_option_key='Z' WHERE question_id=:id"),
                {"id": invalid_questions["invalid_key"]},
            )
            connection.execute(
                text("UPDATE mcq_questions SET correct_option_key=NULL WHERE question_id=:id"),
                {"id": invalid_questions["missing_key"]},
            )
            connection.execute(
                text("UPDATE mcq_questions SET is_multiple_correct=TRUE WHERE question_id=:id"),
                {"id": invalid_questions["multiple_correct"]},
            )
            connection.execute(
                text("UPDATE questions SET difficulty=NULL WHERE question_id=:id"),
                {"id": invalid_questions["missing_difficulty"]},
            )
            connection.execute(
                text("DELETE FROM question_subtopics WHERE question_id=:id"),
                {"id": invalid_questions["missing_mapping"]},
            )
            connection.execute(
                text("UPDATE questions SET status='ARCHIVED' WHERE question_id=:id"),
                {"id": invalid_questions["archived"]},
            )
            connection.execute(
                text("""
                    UPDATE questions target
                    JOIN questions source
                      ON source.question_id = :source_id
                    SET target.content_hash = source.content_hash
                    WHERE target.question_id = :target_id
                """),
                {
                    "source_id": invalid_questions["duplicate_hash"],
                    "target_id": invalid_questions["duplicate_hash_peer"],
                },
            )
            connection.execute(
                text("""
                    UPDATE mcq_questions target
                    JOIN mcq_questions source
                      ON source.question_id = :source_id
                    SET target.question_text = source.question_text
                    WHERE target.question_id = :target_id
                """),
                {
                    "source_id": invalid_questions["duplicate_text"],
                    "target_id": invalid_questions["duplicate_text_peer"],
                },
            )
            connection.execute(
                text("""
                    INSERT INTO question_reports (question_id, user_id, report_type, details, status)
                    VALUES (:question_id, :user_id, 'BAD_QUESTION', 'Eligibility fixture', 'OPEN')
                """),
                {
                    "question_id": invalid_questions["open_report"],
                    "user_id": self.user_ids[0],
                },
            )
            connection.execute(
                text("""
                    INSERT INTO question_reviews (question_id, reviewer_id, decision, notes)
                    VALUES (:question_id, :reviewer_id, 'PENDING', 'Eligibility fixture')
                """),
                {
                    "question_id": invalid_questions["pending_review"],
                    "reviewer_id": self.user_ids[1],
                },
            )
            connection.execute(
                text("""
                    INSERT INTO duplicate_matches (
                        question_id_a, question_id_b, similarity_score, match_type, resolution
                    )
                    VALUES (:left_id, :right_id, 1.0, 'EXACT', 'PENDING')
                """),
                {
                    "left_id": invalid_questions["missing_options"],
                    "right_id": invalid_questions["unresolved_duplicate"],
                },
            )
            connection.execute(
                text("""
                    UPDATE questions
                    SET source_id = (
                        SELECT source_id FROM sources WHERE source_type='SCRAPED' LIMIT 1
                    )
                    WHERE question_id = :question_id
                """),
                {"question_id": invalid_questions["scraped_source"]},
            )

        with engine.connect() as connection:
            self.assertTrue(is_mock_eligible(connection, valid_four))
            self.assertTrue(is_mock_eligible(connection, valid_five))
            content_invalid = {
                "missing_options",
                "invalid_key",
                "missing_key",
                "multiple_correct",
                "missing_difficulty",
                "missing_mapping",
            }
            for name in content_invalid:
                question_id = invalid_questions[name]
                self.assertFalse(is_mock_eligible(connection, question_id))
            for name in set(invalid_questions) - content_invalid:
                self.assertTrue(
                    is_mock_eligible(connection, invalid_questions[name]),
                    name,
                )
            selected = blueprint_service.select_filtered_questions(
                connection,
                "MCQ",
                int(taxonomy["track_id"]),
                "EASY",
                int(taxonomy["topic_id"]),
                int(taxonomy["subtopic_id"]),
                2,
            )
            self.assertEqual(len(selected), 2)
            self.assertEqual(len(set(selected)), 2)
            self.assertTrue(all(is_mock_eligible(connection, item) for item in selected))

    def test_versioned_blueprint_drives_mock_adaptive_attempt_and_analytics(self):
        suffix = uuid.uuid4().hex
        with engine.begin() as connection:
            taxonomy = connection.execute(
                text("""
                    SELECT t.topic_id, t.track_id, s.subtopic_id
                    FROM topics t
                    JOIN tracks tr ON tr.track_id = t.track_id
                    JOIN subtopics s ON s.topic_id = t.topic_id
                    WHERE tr.track_name IN ('Aptitude', 'Technical')
                    ORDER BY tr.track_name, t.topic_id, s.subtopic_id
                """)
            ).mappings().all()
            by_track = {}
            for row in taxonomy:
                by_track.setdefault(int(row["track_id"]), dict(row))
            self.assertGreaterEqual(len(by_track), 2)
            topic_rows = list(by_track.values())[:2]
            source_id = int(
                connection.execute(
                    text("SELECT source_id FROM sources ORDER BY source_id LIMIT 1")
                ).scalar_one()
            )
            self.company_question_id = self._create_question(
                connection,
                source_id,
                int(topic_rows[0]["topic_id"]),
                int(topic_rows[0]["subtopic_id"]),
                f"Company-specific fixture {suffix}",
            )
            self.invalid_content_question_ids = {
                "null_key": self._create_question(
                    connection, source_id, int(topic_rows[0]["topic_id"]),
                    int(topic_rows[0]["subtopic_id"]),
                    f"Missing key fixture {suffix}",
                ),
                "invalid_key": self._create_question(
                    connection, source_id, int(topic_rows[0]["topic_id"]),
                    int(topic_rows[0]["subtopic_id"]),
                    f"Invalid key fixture {suffix}",
                ),
                "duplicate_option": self._create_question(
                    connection, source_id, int(topic_rows[0]["topic_id"]),
                    int(topic_rows[0]["subtopic_id"]),
                    f"Duplicate option fixture {suffix}",
                ),
                "duplicate_text": self._create_question(
                    connection, source_id, int(topic_rows[0]["topic_id"]),
                    int(topic_rows[0]["subtopic_id"]),
                    f"Duplicate text fixture {suffix}",
                ),
                "missing_difficulty": self._create_question(
                    connection, source_id, int(topic_rows[0]["topic_id"]),
                    int(topic_rows[0]["subtopic_id"]),
                    f"Missing difficulty fixture {suffix}",
                ),
            }
            connection.execute(
                text("""
                    UPDATE mcq_questions
                    SET correct_option_key = NULL
                    WHERE question_id = :question_id
                """),
                {"question_id": self.invalid_content_question_ids["null_key"]},
            )
            connection.execute(
                text("""
                    UPDATE mcq_questions
                    SET correct_option_key = 'Z'
                    WHERE question_id = :question_id
                """),
                {"question_id": self.invalid_content_question_ids["invalid_key"]},
            )
            connection.execute(
                text("""
                    UPDATE mcq_options target
                    JOIN mcq_options source
                      ON source.question_id = target.question_id
                     AND source.option_key = 'A'
                    SET target.option_text = source.option_text
                    WHERE target.question_id = :question_id
                      AND target.option_key = 'D'
                """),
                {
                    "question_id":
                        self.invalid_content_question_ids["duplicate_option"]
                },
            )
            connection.execute(
                text("""
                    UPDATE questions
                    SET difficulty = NULL
                    WHERE question_id = :question_id
                """),
                {
                    "question_id":
                        self.invalid_content_question_ids["missing_difficulty"]
                },
            )
            self.unpublished_question_ids = [
                self._create_question(
                    connection,
                    source_id,
                    int(topic_rows[0]["topic_id"]),
                    int(topic_rows[0]["subtopic_id"]),
                    f"Unpublished eligibility fixture {status} {suffix}",
                )
                for status in ("DRAFT", "REVIEW", "ARCHIVED")
            ]
            for question_id, status in zip(
                self.unpublished_question_ids,
                ("DRAFT", "REVIEW", "ARCHIVED"),
            ):
                connection.execute(
                    text("""
                        UPDATE questions
                        SET status = :status
                        WHERE question_id = :question_id
                    """),
                    {"status": status, "question_id": question_id},
                )
            self.other_company_question_id = self._create_question(
                connection,
                source_id,
                int(topic_rows[1]["topic_id"]),
                int(topic_rows[1]["subtopic_id"]),
                f"Company second-section fixture {suffix}",
            )
            outside_taxonomy = connection.execute(
                text("""
                    SELECT t.topic_id, s.subtopic_id
                    FROM topics t
                    JOIN subtopics s ON s.topic_id = t.topic_id
                    WHERE t.track_id NOT IN (:track_one, :track_two)
                    ORDER BY t.topic_id, s.subtopic_id
                    LIMIT 1
                """),
                {
                    "track_one": int(topic_rows[0]["track_id"]),
                    "track_two": int(topic_rows[1]["track_id"]),
                },
            ).mappings().one()
            self.outside_question_id = self._create_question(
                connection,
                source_id,
                int(outside_taxonomy["topic_id"]),
                int(outside_taxonomy["subtopic_id"]),
                f"Out-of-blueprint fixture {suffix}",
            )
            self.invalid_question_id = self._create_question(
                connection,
                source_id,
                int(outside_taxonomy["topic_id"]),
                int(outside_taxonomy["subtopic_id"]),
                f"Invalid activation fixture {suffix}",
            )
            connection.execute(
                text("""
                    DELETE FROM mcq_options
                    WHERE question_id = :question_id AND option_key = 'D'
                """),
                {"question_id": self.invalid_question_id},
            )

        self._set_admin()
        company_response = self.client.post(
            "/admin/companies",
            json={
                "company_name": f"Fixture Company {suffix}",
                "slug": f"fixture-company-{suffix}",
                "description": "Disposable Phase 9 integration fixture.",
            },
        )
        self.assertEqual(company_response.status_code, 201, company_response.text)
        company_id = company_response.json()["company_id"]
        self.company_ids.append(company_id)
        duplicate_company = self.client.post(
            "/admin/companies",
            json={
                "company_name": f"Fixture Company {suffix}",
                "slug": f"fixture-company-{suffix}",
                "description": "Duplicate creation must be rejected.",
            },
        )
        self.assertEqual(duplicate_company.status_code, 409)

        blueprint_payload = {
            "company_id": company_id,
            "blueprint_name": "Fixture Foundation",
            "program_name": "Fixture Program",
            "pattern_version": "test-2026",
            "effective_from": date.today().isoformat(),
            "source_name": "Disposable integration fixture",
            "source_url": "https://example.test/fixture-pattern",
            "source_type": "INTERNAL",
            "source_accessed_at": datetime.now().isoformat(timespec="seconds"),
            "source_notes": "Disposable test data; not a real exam pattern.",
            "pattern_details": {
                "sections": [
                    {
                        "section_name": "Quantitative Reasoning",
                        "section_order": 1,
                        "question_count": 1,
                        "selection_supported": True,
                    },
                    {
                        "section_name": "Verbal Ability",
                        "section_order": 2,
                        "question_count": 1,
                        "selection_supported": True,
                    },
                ],
            },
            "verification_status": "UNVERIFIED",
            "verification_notes": "Not a real company assessment pattern.",
            "track_id": None,
            "duration_seconds": 600,
        }
        blueprint_response = self.client.post(
            "/admin/blueprints",
            json=blueprint_payload,
        )
        self.assertEqual(
            blueprint_response.status_code, 200, blueprint_response.text
        )
        blueprint_id = blueprint_response.json()["blueprint_id"]
        self.blueprint_ids.append(blueprint_id)
        duplicate_version = self.client.post(
            "/admin/blueprints",
            json=blueprint_payload,
        )
        self.assertEqual(duplicate_version.status_code, 409)
        self.assertEqual(
            duplicate_version.json()["detail"]["code"],
            "DUPLICATE_PATTERN_VERSION",
        )
        rule_response = self.client.post(
            f"/admin/blueprints/{blueprint_id}/rules",
            json={
                "section_name": "Quantitative Reasoning",
                "section_order": 1,
                "is_required": True,
                "topic_id": int(topic_rows[0]["topic_id"]),
                "subtopic_id": int(topic_rows[0]["subtopic_id"]),
                "track_id": int(topic_rows[0]["track_id"]),
                "question_type": "MCQ",
                "question_count": 1,
                "points": "1.00",
            },
        )
        self.assertEqual(rule_response.status_code, 200, rule_response.text)
        second_rule_response = self.client.post(
            f"/admin/blueprints/{blueprint_id}/rules",
            json={
                "section_name": "Verbal Ability",
                "section_order": 2,
                "is_required": True,
                "topic_id": int(topic_rows[1]["topic_id"]),
                "subtopic_id": int(topic_rows[1]["subtopic_id"]),
                "track_id": int(topic_rows[1]["track_id"]),
                "question_type": "MCQ",
                "question_count": 1,
                "points": "1.00",
            },
        )
        self.assertEqual(
            second_rule_response.status_code, 200, second_rule_response.text
        )

        activation_with_unpublished_content = self.client.post(
            f"/admin/blueprints/{blueprint_id}/activate"
        )
        self.assertEqual(
            activation_with_unpublished_content.status_code, 200,
            activation_with_unpublished_content.text,
        )
        unpublished_content_mock = self.client.post(
            "/mock-tests",
            json={
                "title": "Unpublished fixture blueprint",
                "mode": "MOCK",
                "blueprint_id": blueprint_id,
            },
        )
        self.assertEqual(
            unpublished_content_mock.status_code, 200, unpublished_content_mock.text
        )
        self.mock_test_ids.append(
            unpublished_content_mock.json()["mock_test_id"]
        )

        for question_id in (
            self.company_question_id,
            self.other_company_question_id,
            self.outside_question_id,
        ):
            review = self.client.post(
                f"/admin/questions/{question_id}/review"
            )
            self.assertEqual(review.status_code, 200, review.text)
            publish = self.client.post(
                f"/admin/questions/{question_id}/publish"
            )
            self.assertEqual(publish.status_code, 200, publish.text)

        with engine.begin() as connection:
            connection.execute(
                text("""
                    UPDATE mcq_questions target
                    JOIN mcq_questions source
                      ON source.question_id = :source_question_id
                    SET target.question_text = source.question_text
                    WHERE target.question_id = :target_question_id
                """),
                {
                    "source_question_id": self.company_question_id,
                    "target_question_id":
                        self.invalid_content_question_ids["duplicate_text"],
                },
            )
        invalid_review = self.client.post(
            f"/admin/questions/{self.invalid_question_id}/review"
        )
        self.assertEqual(invalid_review.status_code, 200, invalid_review.text)
        invalid_publish = self.client.post(
            f"/admin/questions/{self.invalid_question_id}/publish"
        )
        self.assertEqual(invalid_publish.status_code, 422, invalid_publish.text)
        self.assertIn(
            "4 or 5 options",
            str(invalid_publish.json()["detail"]["errors"]),
        )
        expected_publication_errors = {
            "null_key": "A correct option is required.",
            "invalid_key": "The correct option key must match an existing option.",
            "duplicate_option": "MCQ options must have unique text.",
            "duplicate_text": "duplicates existing question",
            "missing_difficulty": "Question difficulty must be sourced or reviewed",
        }
        for kind, question_id in self.invalid_content_question_ids.items():
            review = self.client.post(
                f"/admin/questions/{question_id}/review"
            )
            self.assertEqual(review.status_code, 200, review.text)
            publish = self.client.post(
                f"/admin/questions/{question_id}/publish"
            )
            self.assertEqual(publish.status_code, 422, publish.text)
            self.assertIn(
                expected_publication_errors[kind],
                str(publish.json()["detail"]["errors"]),
            )
        with engine.begin() as connection:
            duplicate_text_title = connection.execute(
                text("SELECT title FROM questions WHERE question_id = :question_id"),
                {"question_id": self.invalid_content_question_ids["duplicate_text"]},
            ).scalar_one()
            connection.execute(
                text("""
                    UPDATE mcq_questions
                    SET question_text = :question_text
                    WHERE question_id = :question_id
                """),
                {
                    "question_id": self.invalid_content_question_ids["duplicate_text"],
                    "question_text": f"{duplicate_text_title}?",
                },
            )

        activation = self.client.post(
            f"/admin/blueprints/{blueprint_id}/activate"
        )
        self.assertEqual(activation.status_code, 200, activation.text)
        self.assertEqual(activation.json()["status"], "ACTIVE")
        self.assertIsNotNone(activation.json()["activated_at"])
        validation = self.client.post(
            f"/admin/blueprints/{blueprint_id}/validate"
        )
        self.assertEqual(validation.status_code, 200, validation.text)
        self.assertTrue(validation.json()["valid"])
        immutable = self.client.put(
            f"/admin/blueprints/{blueprint_id}",
            json={"program_name": "Changed after activation"},
        )
        self.assertEqual(immutable.status_code, 409, immutable.text)
        self.assertEqual(
            immutable.json()["detail"]["code"],
            "IMMUTABLE_PATTERN_VERSION",
        )
        health = self.client.get("/admin/content/activation-summary")
        self.assertEqual(health.status_code, 200, health.text)
        self.assertGreaterEqual(health.json()["eligible_mcq"], 3)

        self._set_student()
        forbidden_blueprint_edit = self.client.put(
            f"/admin/blueprints/{blueprint_id}",
            json={"description": "Student must not change this."},
        )
        self.assertEqual(forbidden_blueprint_edit.status_code, 403)
        forbidden_publish = self.client.post(
            f"/admin/questions/{self.company_question_id}/publish"
        )
        self.assertEqual(forbidden_publish.status_code, 403)
        listed_companies = self.client.get("/companies")
        self.assertEqual(listed_companies.status_code, 200, listed_companies.text)
        self.assertIn(
            company_id,
            {company["company_id"] for company in listed_companies.json()},
        )
        company_blueprints = self.client.get(
            f"/companies/{company_id}/blueprints"
        )
        self.assertEqual(
            company_blueprints.status_code, 200, company_blueprints.text
        )
        self.assertEqual(
            company_blueprints.json()[0]["pattern_version"], "test-2026"
        )
        nested_blueprint = self.client.get(
            f"/companies/{company_id}/blueprints/{blueprint_id}"
        )
        self.assertEqual(nested_blueprint.status_code, 200, nested_blueprint.text)
        self.assertEqual(
            nested_blueprint.json()["verification_status"], "UNVERIFIED"
        )

        mock_response = self.client.post(
            "/mock-tests",
            json={
                "title": "Fixture Company-Style Mock",
                "mode": "MOCK",
                "blueprint_id": blueprint_id,
            },
        )
        self.assertEqual(mock_response.status_code, 200, mock_response.text)
        mock = mock_response.json()
        self.mock_test_ids.append(mock["mock_test_id"])
        self.assertEqual(mock["company_id"], company_id)
        self.assertEqual(mock["program_name"], "Fixture Program")
        self.assertEqual(mock["pattern_version"], "test-2026")
        self.assertTrue(mock["title"].endswith("Company-Style Mock"))
        self.assertEqual(mock["total_questions"], 2)

        mock_detail = self.client.get(f"/mock-tests/{mock['mock_test_id']}")
        self.assertEqual(mock_detail.status_code, 200, mock_detail.text)
        questions = mock_detail.json()["questions"]
        self.assertEqual(len(questions), 2)
        self.assertEqual(
            [question["section_name"] for question in questions],
            ["Quantitative Reasoning", "Verbal Ability"],
        )
        self.assertTrue(
            all("correct_option_key" not in question for question in questions)
        )
        with engine.connect() as connection:
            generated_ids = connection.execute(
                text("""
                    SELECT question_id
                    FROM mock_test_questions
                    WHERE mock_test_id = :mock_test_id
                """),
                {"mock_test_id": mock["mock_test_id"]},
            ).scalars().all()
        self.assertEqual(
            [question["question_id"] for question in questions],
            generated_ids,
        )
        self.assertEqual(len(generated_ids), 2)
        self.assertEqual(len(set(generated_ids)), 2)
        self.assertNotIn(self.outside_question_id, generated_ids)
        self._start_answer_submit(mock["mock_test_id"], generated_ids)

        self._set_student()
        denied_admin_read = self.client.get("/admin/company-readiness")
        self.assertEqual(denied_admin_read.status_code, 403)
        self.assertEqual(
            self.client.get(
                f"/admin/companies/{company_id}/readiness"
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                "/admin/companies",
                json={"company_name": "Student must not create", "slug": "student-no"},
            ).status_code,
            403,
        )
        self._set_admin()
        readiness = self.client.get("/admin/company-readiness")
        self.assertEqual(readiness.status_code, 200, readiness.text)
        company_entry = next(
            item for item in readiness.json()
            if item["blueprint_id"] == blueprint_id
        )
        self.assertTrue(company_entry["ready_for_mock"])
        self.assertEqual(company_entry["required_questions"], 2)
        self.assertEqual(company_entry["verification_status"], "UNVERIFIED")
        self.assertEqual(len(company_entry["sections"]), 2)
        company_readiness = self.client.get(
            f"/admin/companies/{company_id}/readiness"
        )
        self.assertEqual(company_readiness.status_code, 200, company_readiness.text)
        self.assertEqual(
            company_readiness.json()["blueprints"][0]["pattern_version"],
            "test-2026",
        )

        self._set_student()
        wrong_count = self.client.post(
            "/adaptive/session",
            json={"blueprint_id": blueprint_id, "number_of_questions": 1},
        )
        self.assertEqual(wrong_count.status_code, 422, wrong_count.text)
        self.assertEqual(
            wrong_count.json()["detail"]["code"],
            "BLUEPRINT_COMPOSITION_MISMATCH",
        )
        adaptive = self.client.post(
            "/adaptive/session",
            json={"blueprint_id": blueprint_id, "number_of_questions": 2},
        )
        self.assertEqual(adaptive.status_code, 200, adaptive.text)
        adaptive_data = adaptive.json()
        self.mock_test_ids.append(adaptive_data["mock_test_id"])
        self.attempt_ids.append(adaptive_data["attempt_id"])
        self.assertEqual(adaptive_data["practice_mode"], "ADAPTIVE_PRACTICE")
        self.assertTrue(adaptive_data["title"].endswith("Company-Style Adaptive Practice"))
        self.assertEqual(adaptive_data["company_id"], company_id)
        self.assertEqual(adaptive_data["program"], "Fixture Program")
        self.assertEqual(adaptive_data["pattern_version"], "test-2026")
        adaptive_question_ids = [
            question["question_id"] for question in adaptive_data["questions"]
        ]
        self.assertEqual(len(adaptive_question_ids), 2)
        self.assertEqual(len(set(adaptive_question_ids)), 2)
        self.assertTrue(
            all(
                "correct_option_key" not in question["content"]
                for question in adaptive_data["questions"]
            )
        )
        self.assertEqual(
            [question["section_name"] for question in adaptive_data["questions"]],
            ["Quantitative Reasoning", "Verbal Ability"],
        )
        session_status = self.client.get(
            f"/adaptive/session/{adaptive_data['session_id']}"
        )
        self.assertEqual(session_status.status_code, 200, session_status.text)
        self.assertEqual(session_status.json()["company_id"], company_id)
        self.assertEqual(session_status.json()["blueprint_id"], blueprint_id)
        self.assertEqual(
            session_status.json()["questions"][0]["section_name"],
            "Quantitative Reasoning",
        )
        for question_id in adaptive_question_ids:
            saved = self.client.post(
                f"/attempts/{adaptive_data['attempt_id']}/answers",
                json={
                    "question_id": question_id,
                    "selected_option_key": "A",
                    "time_spent_seconds": 9,
                },
            )
            self.assertEqual(saved.status_code, 200, saved.text)
        submitted = self.client.post(
            f"/attempts/{adaptive_data['attempt_id']}/submit"
        )
        self.assertEqual(submitted.status_code, 200, submitted.text)

        analytics = self.client.get("/analytics/me/summary")
        self.assertEqual(analytics.status_code, 200, analytics.text)
        self.assertEqual(analytics.json()["completed_attempts"], 2)

        self._set_admin()
        archived = self.client.post(
            f"/admin/questions/{self.company_question_id}/archive"
        )
        self.assertEqual(archived.status_code, 200, archived.text)
        self._set_student()
        archived_content_mock = self.client.post(
            "/mock-tests",
            json={
                "title": "Remaining content stays eligible",
                "mode": "MOCK",
                "blueprint_id": blueprint_id,
            },
        )
        self.assertEqual(archived_content_mock.status_code, 200, archived_content_mock.text)
        self.mock_test_ids.append(archived_content_mock.json()["mock_test_id"])
        remaining_content_adaptive = self.client.post(
            "/adaptive/session",
            json={"blueprint_id": blueprint_id, "number_of_questions": 2},
        )
        self.assertEqual(
            remaining_content_adaptive.status_code,
            200,
            remaining_content_adaptive.text,
        )
        self.mock_test_ids.append(remaining_content_adaptive.json()["mock_test_id"])
        self.attempt_ids.append(remaining_content_adaptive.json()["attempt_id"])
        readiness_after_archive = self.client.get("/admin/company-readiness")
        self.assertEqual(readiness_after_archive.status_code, 403)
        self._set_admin()
        readiness_after_archive = self.client.get("/admin/company-readiness")
        self.assertEqual(
            readiness_after_archive.status_code, 200, readiness_after_archive.text
        )
        company_entry = next(
            item for item in readiness_after_archive.json()
            if item["blueprint_id"] == blueprint_id
        )
        self.assertTrue(company_entry["ready_for_mock"])

    def test_tcs_foundation_composition_with_disposable_eligible_content(self):
        suffix = uuid.uuid4().hex
        sections = (
            ("Numerical Ability", "Quantitative Aptitude", 20, 25 * 60),
            ("Verbal Ability", "Verbal Ability", 25, 26 * 60),
            ("Reasoning Ability", "Logical Reasoning", 20, 25 * 60),
        )
        with engine.begin() as connection:
            company = connection.execute(
                text("""
                    SELECT company_id
                    FROM companies
                    WHERE slug = 'tcs'
                """)
            ).scalar_one()
            source_id = int(connection.execute(
                text("""
                    SELECT source_id
                    FROM sources
                    WHERE source_name = 'Custom MCQ Bank — 310 Questions Detected'
                """)
            ).scalar_one())
            topics = connection.execute(
                text("""
                    SELECT t.topic_id, t.topic_name, s.subtopic_id
                    FROM topics t
                    JOIN tracks tr ON tr.track_id = t.track_id
                    JOIN subtopics s ON s.topic_id = t.topic_id
                    WHERE tr.track_name = 'Aptitude'
                      AND t.topic_name IN (
                        'Quantitative Aptitude',
                        'Verbal Ability',
                        'Logical Reasoning'
                      )
                    ORDER BY t.topic_id, s.subtopic_id
                """)
            ).mappings().all()
            taxonomy = {}
            for row in topics:
                taxonomy.setdefault(row["topic_name"], dict(row))
            self.assertEqual(
                set(taxonomy),
                {section[1] for section in sections},
            )

            created_questions = {}
            for section_name, topic_name, count, _ in sections:
                topic = taxonomy[topic_name]
                ids = []
                for index in range(count):
                    question_id = self._create_question(
                        connection,
                        source_id,
                        int(topic["topic_id"]),
                        int(topic["subtopic_id"]),
                        f"TCS fixture {suffix} {section_name} {index:02d}",
                    )
                    question_governance_service.transition_question_status(
                        connection,
                        question_id,
                        "REVIEW",
                        self.admin["user_id"],
                    )
                    question_governance_service.transition_question_status(
                        connection,
                        question_id,
                        "PUBLISHED",
                        self.admin["user_id"],
                    )
                    ids.append(question_id)
                created_questions[section_name] = ids

        blueprint_response = self.client.post(
            "/admin/blueprints",
            json={
                "company_id": company,
                "blueprint_name": f"TCS NQT Foundation fixture {suffix}",
                "program_name": f"TCS NQT Foundation fixture {suffix}",
                "pattern_version": f"fixture-{suffix}",
                "effective_from": date.today().isoformat(),
                "source_name": "Disposable Phase 10 integration fixture",
                "source_url": "https://example.test/tcs-fixture",
                "source_type": "INTERNAL",
                "source_accessed_at": datetime.now().isoformat(timespec="seconds"),
                "source_notes": (
                    "Disposable fixture only; this does not verify or reproduce "
                    "the reported TCS examination."
                ),
                "pattern_details": {
                    "exact_exam_reconstruction": False,
                    "sections": [
                        {
                            "section_name": name,
                            "section_order": order,
                            "question_count": count,
                            "question_types": ["MCQ"],
                            "selection_supported": True,
                        }
                        for order, (name, _, count, _) in enumerate(sections, 1)
                    ],
                },
                "verification_status": "UNVERIFIED",
                "verification_notes": "Disposable test fixture.",
                "duration_seconds": 76 * 60,
            },
        )
        self.assertEqual(
            blueprint_response.status_code, 200, blueprint_response.text
        )
        blueprint_id = blueprint_response.json()["blueprint_id"]
        self.blueprint_ids.append(blueprint_id)

        for order, (section_name, topic_name, count, duration) in enumerate(
            sections, 1
        ):
            rule_response = self.client.post(
                f"/admin/blueprints/{blueprint_id}/rules",
                json={
                    "section_name": section_name,
                    "section_order": order,
                    "track_id": 1,
                    "topic_id": taxonomy[topic_name]["topic_id"],
                    "question_type": "MCQ",
                    "question_count": count,
                    "time_allocation_seconds": duration,
                },
            )
            self.assertEqual(rule_response.status_code, 200, rule_response.text)

        activated = self.client.post(
            f"/admin/blueprints/{blueprint_id}/activate"
        )
        self.assertEqual(activated.status_code, 200, activated.text)
        self.assertEqual(activated.json()["verification_status"], "UNVERIFIED")
        readiness = self.client.get(
            f"/admin/companies/{company}/readiness"
        )
        self.assertEqual(readiness.status_code, 200, readiness.text)
        ready_blueprint = next(
            item for item in readiness.json()["blueprints"]
            if item["blueprint_id"] == blueprint_id
        )
        self.assertTrue(ready_blueprint["ready_for_mock"])
        company_response = self.client.get("/companies")
        self.assertEqual(company_response.status_code, 200, company_response.text)
        company_ids = {item["company_id"] for item in company_response.json()}
        self.assertIn(company, company_ids)

        self._set_student()
        mock_response = self.client.post(
            "/mock-tests",
            json={
                "title": "Disposable TCS Foundation composition test",
                "mode": "MOCK",
                "blueprint_id": blueprint_id,
            },
        )
        self.assertEqual(mock_response.status_code, 200, mock_response.text)
        mock = mock_response.json()
        self.mock_test_ids.append(mock["mock_test_id"])
        self.assertEqual(mock["company_id"], company)
        self.assertEqual(mock["total_questions"], 65)
        self.assertEqual(mock["duration_seconds"], 76 * 60)

        detail = self.client.get(f"/mock-tests/{mock['mock_test_id']}")
        self.assertEqual(detail.status_code, 200, detail.text)
        questions = detail.json()["questions"]
        question_ids = [question["question_id"] for question in questions]
        self.assertEqual(len(question_ids), 65)
        self.assertEqual(len(set(question_ids)), 65)
        with engine.connect() as connection:
            question_topics = connection.execute(
                text("""
                    SELECT qs.question_id, t.topic_name
                    FROM question_subtopics qs
                    JOIN subtopics s ON s.subtopic_id = qs.subtopic_id
                    JOIN topics t ON t.topic_id = s.topic_id
                    WHERE qs.question_id IN :question_ids
                """),
                {"question_ids": tuple(question_ids)},
            ).mappings().all()
        topics_by_question_id = {}
        for row in question_topics:
            topics_by_question_id.setdefault(
                int(row["question_id"]), set()
            ).add(row["topic_name"])
        self.assertTrue(set(question_ids).issubset(topics_by_question_id))
        for section_name, topic_name, count, _ in sections:
            section_questions = [
                question for question in questions
                if question["section_name"] == section_name
            ]
            self.assertEqual(len(section_questions), count)
            self.assertTrue(
                all(
                    topic_name in topics_by_question_id[question["question_id"]]
                    for question in section_questions
                )
            )
        self.assertTrue(
            all("correct_option_key" not in question for question in questions)
        )

    def test_reviewed_classification_can_be_published_through_governance(self):
        suffix = uuid.uuid4().hex
        with engine.begin() as connection:
            taxonomy = connection.execute(
                text("""
                    SELECT t.topic_id, s.subtopic_id
                    FROM topics t
                    JOIN tracks tr ON tr.track_id = t.track_id
                    JOIN subtopics s ON s.topic_id = t.topic_id
                    WHERE tr.track_name = 'Aptitude'
                      AND t.topic_name = 'Quantitative Aptitude'
                    ORDER BY s.subtopic_id
                    LIMIT 1
                """)
            ).mappings().one()
            source_id = int(
                connection.execute(
                    text("SELECT source_id FROM sources ORDER BY source_id LIMIT 1")
                ).scalar_one()
            )
            question_id = self._create_question(
                connection,
                source_id,
                int(taxonomy["topic_id"]),
                int(taxonomy["subtopic_id"]),
                f"Classification approval fixture {suffix}",
            )
            connection.execute(
                text("""
                    UPDATE questions
                    SET difficulty = NULL,
                        source_question_number = :source_number,
                        source_metadata = JSON_OBJECT(
                            'source_question_number', :source_number
                        )
                    WHERE question_id = :question_id
                """),
                {
                    "source_number": question_id + 100000,
                    "question_id": question_id,
                },
            )
            question_governance_service.transition_question_status(
                connection,
                question_id,
                "REVIEW",
                self.admin["user_id"],
            )
            connection.execute(
                text("""
                    INSERT INTO question_reviews (
                        question_id, reviewer_id, decision, quality_score, notes
                    )
                    VALUES (
                        :question_id, :reviewer_id, 'PENDING', 92.00,
                        'QUESTION_CLASSIFICATION:v1:{"proposed_difficulty":"EASY"}'
                    )
                """),
                {"question_id": question_id, "reviewer_id": self.admin["user_id"]},
            )

        decision = self.client.post(
            f"/admin/questions/{question_id}/difficulty-review",
            json={
                "decision": "APPROVE",
                "difficulty": "EASY",
                "reviewer_notes": "Verified the source answer and direct calculation.",
            },
        )
        self.assertEqual(decision.status_code, 200, decision.text)
        self.assertTrue(decision.json()["publication_ready"])
        with engine.connect() as connection:
            self.assertEqual(
                connection.execute(
                    text("SELECT difficulty FROM questions WHERE question_id=:id"),
                    {"id": question_id},
                ).scalar_one(),
                "EASY",
            )
            self.assertEqual(
                connection.execute(
                    text("SELECT decision FROM question_reviews WHERE question_id=:id"),
                    {"id": question_id},
                ).scalar_one(),
                "APPROVE",
            )

        published = self.client.post(f"/admin/questions/{question_id}/publish")
        self.assertEqual(published.status_code, 200, published.text)
        self.assertEqual(published.json()["status"], "PUBLISHED")

    def test_classification_approval_rejects_unresolved_question_errors(self):
        suffix = uuid.uuid4().hex
        with engine.begin() as connection:
            taxonomy = connection.execute(
                text("""
                    SELECT t.topic_id, s.subtopic_id
                    FROM topics t
                    JOIN tracks tr ON tr.track_id = t.track_id
                    JOIN subtopics s ON s.topic_id = t.topic_id
                    WHERE tr.track_name = 'Aptitude'
                      AND t.topic_name = 'Quantitative Aptitude'
                    ORDER BY s.subtopic_id
                    LIMIT 1
                """)
            ).mappings().one()
            source_id = int(
                connection.execute(
                    text("SELECT source_id FROM sources ORDER BY source_id LIMIT 1")
                ).scalar_one()
            )
            question_id = self._create_question(
                connection,
                source_id,
                int(taxonomy["topic_id"]),
                int(taxonomy["subtopic_id"]),
                f"Invalid classification fixture {suffix}",
            )
            connection.execute(
                text("""
                    UPDATE questions
                    SET difficulty = NULL,
                        source_question_number = :source_number,
                        source_metadata = JSON_OBJECT(
                            'source_question_number', :source_number
                        )
                    WHERE question_id = :question_id
                """),
                {
                    "source_number": question_id + 100000,
                    "question_id": question_id,
                },
            )
            connection.execute(
                text("""
                    UPDATE mcq_options target
                    JOIN mcq_options source
                      ON source.question_id = target.question_id
                     AND source.option_key = 'A'
                    SET target.option_text = source.option_text
                    WHERE target.question_id = :question_id
                      AND target.option_key = 'D'
                """),
                {"question_id": question_id},
            )
            question_governance_service.transition_question_status(
                connection,
                question_id,
                "REVIEW",
                self.admin["user_id"],
            )
            connection.execute(
                text("""
                    INSERT INTO question_reviews (
                        question_id, reviewer_id, decision, quality_score, notes
                    )
                    VALUES (
                        :question_id, :reviewer_id, 'PENDING', 92.00,
                        'QUESTION_CLASSIFICATION:v1:{"proposed_difficulty":"EASY"}'
                    )
                """),
                {"question_id": question_id, "reviewer_id": self.admin["user_id"]},
            )

        decision = self.client.post(
            f"/admin/questions/{question_id}/difficulty-review",
            json={
                "decision": "APPROVE",
                "difficulty": "EASY",
                "reviewer_notes": "Cannot approve until duplicate options are fixed.",
            },
        )
        self.assertEqual(decision.status_code, 422, decision.text)
        self.assertIn("unique text", decision.text)
        with engine.connect() as connection:
            self.assertIsNone(
                connection.execute(
                    text("SELECT difficulty FROM questions WHERE question_id=:id"),
                    {"id": question_id},
                ).scalar_one()
            )
            self.assertEqual(
                connection.execute(
                    text("SELECT decision FROM question_reviews WHERE question_id=:id"),
                    {"id": question_id},
                ).scalar_one(),
                "PENDING",
            )


if __name__ == "__main__":
    unittest.main()
