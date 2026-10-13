import unittest
import uuid
from datetime import datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from fastapi import HTTPException
from sqlalchemy import text

from app.auth.dependencies import get_current_user
from app.database import engine
from app.main import app
from app.services import attempt_service
from app.services.analytics_service import (
    aggregate_question_metrics,
    choose_canonical_subtopics,
    coding_submission_metrics,
    select_best_coding_submission,
)


class AnalyticsHelperTests(unittest.TestCase):
    def test_zero_denominators_are_reported_as_zero_percent(self):
        self.assertEqual(coding_submission_metrics([])["success_rate"], 0.0)

    def test_primary_subtopic_is_the_only_mapping_and_fallback_is_deterministic(self):
        mappings = [
            {"question_id": 10, "subtopic_id": 3, "is_primary": 0, "subtopic_name": "Fallback", "topic_id": 7, "topic_name": "Topic"},
            {"question_id": 10, "subtopic_id": 8, "is_primary": 1, "subtopic_name": "Primary", "topic_id": 7, "topic_name": "Topic"},
            {"question_id": 11, "subtopic_id": 9, "is_primary": 0, "subtopic_name": "Higher", "topic_id": 7, "topic_name": "Topic"},
            {"question_id": 11, "subtopic_id": 2, "is_primary": 0, "subtopic_name": "Lowest", "topic_id": 7, "topic_name": "Topic"},
        ]
        canonical = choose_canonical_subtopics(mappings)
        self.assertEqual(canonical[10]["subtopic_id"], 8)
        self.assertEqual(canonical[11]["subtopic_id"], 2)

        question_rows = [
            {
                "question_id": 10,
                "question_type": "MCQ",
                "selected_option_key": "A",
                "is_correct": 1,
                "time_spent_seconds": 25,
                "final_submission_count": 0,
                "coding_solved": 0,
                "difficulty": "EASY",
            }
        ]
        result = aggregate_question_metrics(question_rows, canonical, "subtopic")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["subtopic_id"], 8)
        self.assertEqual(result[0]["questions_attempted"], 1)

    def test_coding_submissions_count_problems_once_and_solve_once(self):
        rows = [
            {"question_id": 1, "status": "FAILED", "score": Decimal("4"), "tests_passed": 1, "tests_total": 3},
            {"question_id": 1, "status": "PASSED", "score": Decimal("10"), "tests_passed": 3, "tests_total": 3},
            {"question_id": 1, "status": "FAILED", "score": Decimal("10"), "tests_passed": 3, "tests_total": 3},
        ]
        metrics = coding_submission_metrics(rows)
        self.assertEqual(metrics["total_submissions"], 3)
        self.assertEqual(metrics["problems_attempted"], 1)
        self.assertEqual(metrics["problems_solved"], 1)
        self.assertEqual(metrics["success_rate"], 100.0)
        self.assertEqual(
            select_best_coding_submission(
                [
                    {"submission_id": 1, "status": "PASSED", "score": Decimal("10")},
                    {"submission_id": 2, "status": "FAILED", "score": Decimal("10")},
                ]
            )["submission_id"],
            2,
        )

    def test_pending_and_terminal_coding_statuses_are_counted_without_fake_scores(self):
        rows = [
            {"question_id": 1, "status": "QUEUED", "score": 0, "tests_passed": 0, "tests_total": 0},
            {"question_id": 2, "status": "COMPILE_ERROR", "score": 0, "tests_passed": 0, "tests_total": 3},
            {"question_id": 3, "status": "RUNTIME_ERROR", "score": 0, "tests_passed": 0, "tests_total": 3},
            {"question_id": 4, "status": "TIME_LIMIT", "score": 0, "tests_passed": 1, "tests_total": 3},
            {"question_id": 5, "status": "FAILED", "score": 1, "tests_passed": 1, "tests_total": 3},
        ]
        metrics = coding_submission_metrics(rows)
        self.assertEqual(metrics["total_submissions"], 5)
        self.assertEqual(metrics["problems_attempted"], 5)
        self.assertEqual(metrics["problems_solved"], 0)
        self.assertEqual(metrics["scored_submission_count"], 4)
        self.assertEqual(metrics["compile_error_count"], 1)
        self.assertEqual(metrics["runtime_error_count"], 1)
        self.assertEqual(metrics["time_limit_count"], 1)
        self.assertEqual(metrics["wrong_answer_count"], 1)


class AnalyticsApiTests(unittest.TestCase):
    def setUp(self):
        self.user_ids = []
        self.question_ids = []
        self.attempt_ids = []
        self.mock_test_ids = []
        self.mock_test_id = None
        self.client = TestClient(app)
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": 9_000_000_000_000_000_000,
            "role": "STUDENT",
        }
        self.addCleanup(self._restore_overrides)
        self.addCleanup(self._remove_fixtures)
        self._create_fixture()

    def _restore_overrides(self):
        app.dependency_overrides.clear()

    def _create_fixture(self):
        suffix = uuid.uuid4().hex
        self.email_a = f"analytics-{suffix}-a@example.test"
        self.email_b = f"analytics-{suffix}-b@example.test"
        with engine.begin() as conn:
            base = conn.execute(
                text("""
                    SELECT tr.track_id, src.source_id
                    FROM tracks tr
                    CROSS JOIN sources src
                    ORDER BY tr.track_id, src.source_id
                    LIMIT 1
                """)
            ).mappings().one()
            topic = conn.execute(
                text("""
                    SELECT t.topic_id, t.topic_name, t.track_id,
                           s.subtopic_id, s.subtopic_name
                    FROM topics t
                    JOIN subtopics s ON s.topic_id = t.topic_id
                    WHERE t.topic_id = (
                        SELECT topic_id
                        FROM subtopics
                        GROUP BY topic_id
                        HAVING COUNT(*) >= 2
                        ORDER BY topic_id
                        LIMIT 1
                    )
                    ORDER BY s.subtopic_id
                """)
            ).mappings().all()
            self.assertGreaterEqual(len(topic), 2)

            user_ids = []
            for email in (self.email_a, self.email_b):
                result = conn.execute(
                    text("""
                        INSERT INTO users (email, password_hash, display_name, role, is_active)
                        VALUES (:email, 'test-only-unused-hash', 'Analytics Test', 'STUDENT', 1)
                    """),
                    {"email": email},
                )
                user_ids.append(int(result.lastrowid))
            self.user_ids = user_ids
            user_a, user_b = user_ids

            result = conn.execute(
                text("""
                    INSERT INTO mock_tests (
                        created_by, title, mode, selection_mode, duration_seconds,
                        total_questions, status
                    )
                    VALUES (:created_by, :title, 'MOCK', 'FIXED_QUESTIONS', NULL, 4, 'PUBLISHED')
                """),
                {"created_by": user_a, "title": f"Analytics test {suffix}"},
            )
            self.mock_test_id = int(result.lastrowid)
            self.mock_test_ids.append(self.mock_test_id)

            questions = []
            definitions = [
                ("MCQ", "EASY", "MCQ one"),
                ("MCQ", None, "MCQ null difficulty"),
                ("CODING", "MEDIUM", "Coding problem"),
                ("MCQ", "HARD", "Unanswered question"),
            ]
            for question_type, difficulty, title in definitions:
                result = conn.execute(
                    text("""
                        INSERT INTO questions (
                            source_id, source_question_number, question_type, track_id,
                            title, difficulty, status, content_hash
                        )
                        VALUES (
                            :source_id, NULL, :question_type, :track_id,
                            :title, :difficulty, 'PUBLISHED', :content_hash
                        )
                    """),
                    {
                        "source_id": int(base["source_id"]),
                        "question_type": question_type,
                        "track_id": int(topic[0]["track_id"]),
                        "title": f"{title} {suffix}",
                        "difficulty": difficulty,
                        "content_hash": uuid.uuid4().hex + uuid.uuid4().hex,
                    },
                )
                questions.append(int(result.lastrowid))
            self.question_ids = questions
            q1, q2, q3, q4 = questions

            conn.execute(
                text("""
                    INSERT INTO coding_questions (question_id, problem_statement)
                    VALUES (:question_id, 'Test fixture problem')
                """),
                {"question_id": q3},
            )
            for question_id in (q1, q2, q4):
                conn.execute(
                    text("""
                        INSERT INTO mcq_questions (
                            question_id, question_text, correct_option_key, is_multiple_correct
                        )
                        VALUES (:question_id, 'Analytics regression question', 'A', 0)
                    """),
                    {"question_id": question_id},
                )
                conn.execute(
                    text("""
                        INSERT INTO mcq_options (
                            question_id, option_key, option_text, display_order
                        )
                        VALUES
                            (:question_id, 'A', 'Option A', 1),
                            (:question_id, 'B', 'Option B', 2),
                            (:question_id, 'C', 'Option C', 3),
                            (:question_id, 'D', 'Option D', 4)
                    """),
                    {"question_id": question_id},
                )
            conn.execute(
                text("""
                    INSERT INTO mock_test_questions (mock_test_id, question_id, sequence_no, points)
                    VALUES
                        (:mock_id, :q1, 1, 10),
                        (:mock_id, :q2, 2, 10),
                        (:mock_id, :q3, 3, 10),
                        (:mock_id, :q4, 4, 10)
                """),
                {"mock_id": self.mock_test_id, "q1": q1, "q2": q2, "q3": q3, "q4": q4},
            )

            subtopic_low, subtopic_high = int(topic[0]["subtopic_id"]), int(topic[1]["subtopic_id"])
            conn.execute(
                text("""
                    INSERT INTO question_subtopics (question_id, subtopic_id, is_primary)
                    VALUES
                        (:q1, :low, 0),
                        (:q1, :high, 1),
                        (:q2, :low, 1),
                        (:q3, :low, 1)
                """),
                {"q1": q1, "q2": q2, "q3": q3, "low": subtopic_low, "high": subtopic_high},
            )

            result = conn.execute(
                text("""
                    INSERT INTO mock_tests (
                        created_by, title, mode, selection_mode, duration_seconds,
                        total_questions, status
                    )
                    VALUES (:created_by, :title, 'MOCK', 'FIXED_QUESTIONS', 1, 1, 'PUBLISHED')
                """),
                {"created_by": user_a, "title": f"Analytics second mock {suffix}"},
            )
            second_mock_id = int(result.lastrowid)
            self.mock_test_ids.append(second_mock_id)
            conn.execute(
                text("""
                    INSERT INTO mock_test_questions (mock_test_id, question_id, sequence_no, points)
                    VALUES (:mock_id, :question_id, 1, 10)
                """),
                {"mock_id": second_mock_id, "question_id": q4},
            )

            dated_attempts = [
                (user_a, "SUBMITTED", datetime(2026, 9, 25, 9), datetime(2026, 9, 25, 10), 30),
                (user_a, "SUBMITTED", datetime(2026, 9, 26, 9), datetime(2026, 9, 26, 10), 10),
                (user_a, "EXPIRED", datetime(2026, 9, 24, 9), datetime(2026, 9, 24, 10), 0),
                (user_a, "ABANDONED", datetime(2026, 9, 23, 9), None, 0),
                (user_a, "IN_PROGRESS", datetime(2026, 9, 27, 9), None, 0),
                (user_b, "SUBMITTED", datetime(2026, 9, 25, 9), datetime(2026, 9, 25, 10), 20),
            ]
            attempt_ids = []
            for user_id, status, started, submitted, score in dated_attempts:
                result = conn.execute(
                    text("""
                        INSERT INTO attempts (
                            user_id, mock_test_id, started_at, submitted_at,
                            status, score, max_score, accuracy, time_spent_seconds
                        )
                        VALUES (
                            :user_id, :mock_id, :started, :submitted,
                            :status, :score, 40, NULL, 100
                        )
                    """),
                    {
                        "user_id": user_id,
                        "mock_id": self.mock_test_id,
                        "started": started,
                        "submitted": submitted,
                        "status": status,
                        "score": score,
                    },
                )
                attempt_ids.append(int(result.lastrowid))
            result = conn.execute(
                text("""
                    INSERT INTO attempts (
                        user_id, mock_test_id, started_at, submitted_at,
                        status, score, max_score, accuracy, time_spent_seconds
                    )
                    VALUES (
                        :user_id, :mock_id, :started, :submitted,
                        'SUBMITTED', 10, 10, NULL, 20
                    )
                """),
                {
                    "user_id": user_b,
                    "mock_id": second_mock_id,
                    "started": datetime(2026, 9, 26, 11),
                    "submitted": datetime(2026, 9, 26, 12),
                },
            )
            second_b_attempt_id = int(result.lastrowid)
            attempt_ids.append(second_b_attempt_id)
            conn.execute(
                text("""
                    INSERT INTO attempt_answers (
                        attempt_id, question_id, selected_option_key, is_correct,
                        points_awarded, time_spent_seconds, answered_at
                    )
                    VALUES (:attempt_id, :question_id, 'A', 1, 10, 20, NOW())
                """),
                {"attempt_id": second_b_attempt_id, "question_id": q4},
            )
            self.attempt_ids = attempt_ids
            attempt_a1, attempt_a2, _, _, _, attempt_b = attempt_ids[:6]

            answers = [
                (attempt_a1, q1, "A", 1, 30),
                (attempt_a1, q2, "B", 0, 0),
                (attempt_a2, q1, "B", 0, 50),
                (attempt_a2, q2, "B", 0, None),
                (attempt_b, q1, "A", 1, 40),
            ]
            for attempt_id, question_id, option, correct, seconds in answers:
                conn.execute(
                    text("""
                        INSERT INTO attempt_answers (
                            attempt_id, question_id, selected_option_key, is_correct,
                            points_awarded, time_spent_seconds, answered_at
                        )
                        VALUES (:attempt_id, :question_id, :option, :correct, 0, :seconds, NOW())
                    """),
                    {
                        "attempt_id": attempt_id,
                        "question_id": question_id,
                        "option": option,
                        "correct": correct,
                        "seconds": seconds,
                    },
                )

            coding_results = [
                ("FAILED", 7, 1, 3, datetime(2026, 9, 25, 10, 5)),
                ("PASSED", 10, 3, 3, datetime(2026, 9, 25, 10, 10)),
                ("PASSED", 10, 3, 3, datetime(2026, 9, 25, 10, 15)),
            ]
            for status, score, passed, total, submitted in coding_results:
                conn.execute(
                    text("""
                        INSERT INTO coding_submissions (
                            attempt_id, user_id, question_id, language, source_code,
                            status, tests_passed, tests_total, score, submitted_at
                        )
                        VALUES (
                            :attempt_id, :user_id, :question_id, 'C++17', 'test fixture',
                            :status, :passed, :total, :score, :submitted
                        )
                    """),
                    {
                        "attempt_id": attempt_a1,
                        "user_id": user_a,
                        "question_id": q3,
                        "status": status,
                        "passed": passed,
                        "total": total,
                        "score": score,
                        "submitted": submitted,
                    },
                )

    def _remove_fixtures(self):
        with engine.begin() as conn:
            if self.user_ids:
                conn.execute(
                    text("DELETE FROM coding_submissions WHERE user_id IN :user_ids"),
                    {"user_ids": tuple(self.user_ids)},
                )
                if self.attempt_ids:
                    conn.execute(
                        text("DELETE FROM attempt_answers WHERE attempt_id IN :attempt_ids"),
                        {"attempt_ids": tuple(self.attempt_ids)},
                    )
                    conn.execute(
                        text("DELETE FROM attempts WHERE attempt_id IN :attempt_ids"),
                        {"attempt_ids": tuple(self.attempt_ids)},
                    )
            if self.mock_test_ids:
                conn.execute(
                    text("DELETE FROM mock_test_questions WHERE mock_test_id IN :mock_ids"),
                    {"mock_ids": tuple(self.mock_test_ids)},
                )
                conn.execute(
                    text("DELETE FROM mock_tests WHERE mock_test_id IN :mock_ids"),
                    {"mock_ids": tuple(self.mock_test_ids)},
                )
            if self.question_ids:
                conn.execute(
                    text("DELETE FROM question_subtopics WHERE question_id IN :question_ids"),
                    {"question_ids": tuple(self.question_ids)},
                )
                conn.execute(
                    text("DELETE FROM mcq_options WHERE question_id IN :question_ids"),
                    {"question_ids": tuple(self.question_ids)},
                )
                conn.execute(
                    text("DELETE FROM mcq_questions WHERE question_id IN :question_ids"),
                    {"question_ids": tuple(self.question_ids)},
                )
                conn.execute(
                    text("DELETE FROM coding_test_cases WHERE question_id IN :question_ids"),
                    {"question_ids": tuple(self.question_ids)},
                )
                conn.execute(
                    text("DELETE FROM coding_questions WHERE question_id IN :question_ids"),
                    {"question_ids": tuple(self.question_ids)},
                )
                conn.execute(
                    text("DELETE FROM questions WHERE question_id IN :question_ids"),
                    {"question_ids": tuple(self.question_ids)},
                )
            if self.user_ids:
                conn.execute(
                    text("DELETE FROM users WHERE user_id IN :user_ids"),
                    {"user_ids": tuple(self.user_ids)},
                )

    def _use_student_a(self):
        user_id = self.user_ids[0]
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": user_id,
            "role": "STUDENT",
        }

    def test_zero_data_user_receives_valid_empty_responses(self):
        endpoints = [
            "/analytics/me/summary",
            "/analytics/me/attempts",
            "/analytics/me/topics",
            "/analytics/me/subtopics",
            "/analytics/me/difficulty",
            "/analytics/me/question-types",
            "/analytics/me/coding",
            "/analytics/me/coding/problems",
            "/analytics/me/mocks",
            "/analytics/me/progress",
            "/analytics/me/time",
        ]
        for endpoint in endpoints:
            response = self.client.get(endpoint)
            self.assertEqual(response.status_code, 200, (endpoint, response.text))
        summary = self.client.get("/analytics/me/summary").json()
        self.assertEqual(summary["total_attempts"], 0)
        self.assertEqual(summary["questions_attempted"], 0)
        self.assertEqual(summary["average_accuracy"], 0)
        self.assertEqual(summary["topics"], [])

    def test_student_summary_is_scoped_to_authenticated_user_not_query_user_id(self):
        self._use_student_a()
        response = self.client.get(
            f"/analytics/me/summary?user_id={self.user_ids[1]}"
        )
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["total_attempts"], 5)
        self.assertEqual(data["completed_attempts"], 2)
        self.assertEqual(data["questions_assigned"], 8)
        self.assertEqual(data["questions_attempted"], 5)
        self.assertEqual(data["questions_correct"], 2)
        self.assertEqual(data["questions_skipped"], 3)
        self.assertEqual(data["mcq_questions_attempted"], 4)
        self.assertEqual(data["mcq_questions_correct"], 1)
        self.assertEqual(data["average_accuracy"], 25)
        self.assertEqual(data["average_score_percentage"], 50)
        self.assertEqual(data["highest_score_percentage"], 75)
        self.assertEqual(data["lowest_score_percentage"], 25)
        self.assertEqual(data["average_time_per_question"], 40)
        self.assertEqual(data["time_sample_size"], 2)
        self.assertEqual(data["coding_submissions"], 3)
        self.assertEqual(data["coding_problems_attempted"], 1)
        self.assertEqual(data["coding_problems_solved"], 1)
        self.assertEqual(data["coding_success_rate"], 100)

        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": self.user_ids[1],
            "role": "STUDENT",
        }
        other_student = self.client.get("/analytics/me/summary").json()
        self.assertEqual(other_student["total_attempts"], 2)
        self.assertEqual(other_student["questions_assigned"], 5)
        self.assertEqual(other_student["coding_submissions"], 0)
        self._use_student_a()

    def test_status_policy_topics_subtopics_and_null_difficulty(self):
        self._use_student_a()
        summary = self.client.get("/analytics/me/summary").json()
        self.assertEqual(summary["expired_attempts"], 1)
        self.assertEqual(summary["abandoned_attempts"], 1)

        topic_metrics = self.client.get("/analytics/me/topics").json()
        self.assertEqual(len(topic_metrics), 1)
        self.assertEqual(topic_metrics[0]["questions_attempted"], 5)
        self.assertEqual(topic_metrics[0]["questions_correct"], 2)

        subtopic_metrics = self.client.get("/analytics/me/subtopics").json()
        self.assertEqual(sum(item["questions_attempted"] for item in subtopic_metrics), 5)
        self.assertEqual(sum(item["questions_correct"] for item in subtopic_metrics), 2)

        difficulty = self.client.get("/analytics/me/difficulty").json()
        unknown = next(item for item in difficulty if item["difficulty"] is None)
        self.assertEqual(unknown["questions_attempted"], 2)
        self.assertEqual(unknown["questions_correct"], 0)

    def test_coding_attempts_are_distinct_problems_and_best_score_tie_uses_latest(self):
        self._use_student_a()
        coding = self.client.get("/analytics/me/coding").json()
        self.assertEqual(coding["total_submissions"], 3)
        self.assertEqual(coding["problems_attempted"], 1)
        self.assertEqual(coding["problems_solved"], 1)
        self.assertEqual(coding["average_score"], 9)

        problems = self.client.get("/analytics/me/coding/problems?page=1&page_size=1")
        self.assertEqual(problems.status_code, 200, problems.text)
        result = problems.json()
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["submission_count"], 3)
        self.assertTrue(result["items"][0]["solved"])
        self.assertEqual(result["items"][0]["best_score"], 10)
        self.assertEqual(result["items"][0]["best_final_status"], "PASSED")

        types = self.client.get("/analytics/me/question-types").json()
        coding_type = next(item for item in types if item["question_type"] == "CODING")
        self.assertEqual(coding_type["problems_attempted"], 1)
        self.assertEqual(coding_type["problems_solved"], 1)

    def test_history_mocks_progress_time_and_pagination(self):
        self._use_student_a()
        history = self.client.get("/analytics/me/attempts?page=1&page_size=2").json()
        self.assertEqual(history["total"], 5)
        self.assertEqual(len(history["items"]), 2)
        submitted = self.client.get("/analytics/me/attempts?page=3&page_size=2").json()
        self.assertEqual(len(submitted["items"]), 1)
        self.assertTrue(
            all(
                item["score"] is None
                for item in history["items"]
                if item["status"] != "SUBMITTED"
            )
        )

        mocks = self.client.get("/analytics/me/mocks?page=1&page_size=1").json()
        self.assertEqual(mocks["total"], 1)
        self.assertEqual(mocks["items"][0]["attempt_count"], 2)
        self.assertEqual(mocks["items"][0]["latest_score_percentage"], 25)
        self.assertEqual(mocks["items"][0]["best_score_percentage"], 75)

        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": self.user_ids[1],
            "role": "STUDENT",
        }
        student_b_page_one = self.client.get(
            "/analytics/me/mocks?page=1&page_size=1"
        ).json()
        student_b_page_two = self.client.get(
            "/analytics/me/mocks?page=2&page_size=1"
        ).json()
        self.assertEqual(student_b_page_one["total"], 2)
        self.assertEqual(len(student_b_page_one["items"]), 1)
        self.assertEqual(len(student_b_page_two["items"]), 1)
        self.assertNotEqual(
            student_b_page_one["items"][0]["mock_test_id"],
            student_b_page_two["items"][0]["mock_test_id"],
        )
        self._use_student_a()

        daily = self.client.get("/analytics/me/progress?granularity=day").json()
        self.assertEqual(len(daily["items"]), 2)
        self.assertEqual(sum(item["attempt_count"] for item in daily["items"]), 2)
        weekly = self.client.get("/analytics/me/progress?granularity=week").json()
        self.assertEqual(len(weekly["items"]), 1)
        self.assertEqual(weekly["items"][0]["period"], "2026-09-21")

        timing = self.client.get("/analytics/me/time").json()
        self.assertEqual(timing["timed_question_count"], 2)
        self.assertEqual(timing["average_time_per_question"], 40)
        self.assertEqual(timing["average_time_correct"], 30)
        self.assertEqual(timing["average_time_incorrect"], 50)
        self.assertEqual(timing["timed_correct_count"], 1)
        self.assertEqual(timing["timed_incorrect_count"], 1)

    def test_admin_analytics_requires_admin_and_returns_overview_for_admin(self):
        self._use_student_a()
        denied = self.client.get("/admin/analytics/overview")
        self.assertEqual(denied.status_code, 403)

        admin_id = self.user_ids[0]
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": admin_id,
            "role": "ADMIN",
        }
        allowed = self.client.get("/admin/analytics/overview")
        self.assertEqual(allowed.status_code, 200, allowed.text)
        self.assertGreaterEqual(allowed.json()["total_students"], 1)

    def test_phase_one_scoring_and_phase_three_answer_update_timeout_and_double_submit(self):
        self._use_student_a()
        q1, q2, _, q4 = self.question_ids
        started = datetime(2026, 9, 27, 9)
        with engine.begin() as conn:
            result = conn.execute(
                text("""
                    INSERT INTO attempts (user_id, mock_test_id, started_at, status)
                    VALUES (:user_id, :mock_id, :started_at, 'IN_PROGRESS')
                """),
                {
                    "user_id": self.user_ids[0],
                    "mock_id": self.mock_test_id,
                    "started_at": started,
                },
            )
            attempt_id = int(result.lastrowid)
            self.attempt_ids.append(attempt_id)
            attempt_service.save_answer(
                conn, attempt_id, self.user_ids[0], q1, "B", None, 10
            )
            attempt_service.save_answer(
                conn, attempt_id, self.user_ids[0], q1, "A", None, 20
            )
            attempt_service.save_answer(
                conn, attempt_id, self.user_ids[0], q2, "B", None, 30
            )
            final_result = attempt_service.submit_attempt(
                conn, attempt_id, self.user_ids[0]
            )

        self.assertEqual(float(final_result["attempt"]["score"]), 10)
        self.assertEqual(float(final_result["attempt"]["max_score"]), 40)
        self.assertEqual(final_result["mcq_answered"], 2)
        self.assertEqual(final_result["mcq_correct"], 1)
        with self.assertRaises(HTTPException) as duplicate:
            with engine.begin() as conn:
                attempt_service.submit_attempt(conn, attempt_id, self.user_ids[0])
        self.assertEqual(duplicate.exception.status_code, 400)

        with engine.begin() as conn:
            result = conn.execute(
                text("""
                    INSERT INTO attempts (user_id, mock_test_id, started_at, status)
                    VALUES (:user_id, :mock_id, :started_at, 'IN_PROGRESS')
                """),
                {
                    "user_id": self.user_ids[0],
                    "mock_id": self.mock_test_ids[1],
                    "started_at": datetime(2026, 9, 27, 9),
                },
            )
            expired_attempt_id = int(result.lastrowid)
            self.attempt_ids.append(expired_attempt_id)
        response = self.client.post(
            f"/attempts/{expired_attempt_id}/answers",
            json={"question_id": q4, "selected_option_key": "A"},
        )
        self.assertEqual(response.status_code, 400, response.text)
        with engine.connect() as conn:
            status = conn.execute(
                text("SELECT status FROM attempts WHERE attempt_id = :attempt_id"),
                {"attempt_id": expired_attempt_id},
            ).scalar_one()
        self.assertEqual(status, "EXPIRED")

    def test_submit_route_returns_top_level_attempt_and_allows_unanswered_questions(self):
        self._use_student_a()
        started = self.client.post(
            "/attempts",
            json={"mock_test_id": self.mock_test_id},
        )
        self.assertEqual(started.status_code, 201, started.text)
        attempt_id = started.json()["attempt_id"]
        self.attempt_ids.append(attempt_id)

        submitted = self.client.post(f"/attempts/{attempt_id}/submit")
        self.assertEqual(submitted.status_code, 200, submitted.text)
        data = submitted.json()
        self.assertEqual(data["attempt_id"], attempt_id)
        self.assertEqual(data["mock_test_id"], self.mock_test_id)
        self.assertEqual(data["status"], "SUBMITTED")
        self.assertIsNotNone(data["submitted_at"])
        self.assertEqual(float(data["score"]), 0)
        self.assertEqual(data["attempt"]["attempt_id"], attempt_id)

        result = self.client.get(f"/attempts/{attempt_id}")
        self.assertEqual(result.status_code, 200, result.text)
        result_attempt = result.json()["attempt"]
        self.assertEqual(result_attempt["status"], "SUBMITTED")
        self.assertIsNotNone(result_attempt["submitted_at"])
        self.assertEqual(float(result_attempt["score"]), 0)

        repeated = self.client.post(f"/attempts/{attempt_id}/submit")
        self.assertEqual(repeated.status_code, 400)

        missing = self.client.post("/attempts/999999999999999999/submit")
        self.assertEqual(missing.status_code, 404)

        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": self.user_ids[1],
            "role": "STUDENT",
        }
        unauthorized = self.client.post(f"/attempts/{attempt_id}/submit")
        self.assertEqual(unauthorized.status_code, 403)
        self._use_student_a()


if __name__ == "__main__":
    unittest.main()
