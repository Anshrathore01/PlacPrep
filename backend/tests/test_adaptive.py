import unittest
import uuid
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.adaptive.rules import (
    CONFIG,
    preferred_difficulties,
    smoothed_accuracy,
)
from app.auth.dependencies import get_current_user
from app.database import engine
from app.main import app
from app.services.adaptive_service import (
    _candidate_pool,
    _ranked_pool,
    choose_candidates,
    score_candidate,
)
from app.services.mock_eligibility_service import is_mock_eligible


class AdaptiveRuleTests(unittest.TestCase):
    def test_cold_start_and_small_samples_keep_conservative_difficulty(self):
        self.assertEqual(preferred_difficulties(None, 0, None), ("EASY", "MEDIUM"))
        self.assertEqual(preferred_difficulties(99, 1, "EASY"), ("EASY", "MEDIUM"))
        self.assertEqual(preferred_difficulties(10, 2, "HARD"), ("EASY", "MEDIUM"))
        self.assertEqual(CONFIG.minimum_recent_sample, 5)

    def test_smoothed_accuracy_prevents_extreme_tiny_sample_signals(self):
        self.assertAlmostEqual(smoothed_accuracy(1, 1), 60.0)
        self.assertAlmostEqual(smoothed_accuracy(9, 10), 78.57142857)

    def test_stable_low_moderate_and_high_accuracy_choose_gradual_difficulty(self):
        self.assertEqual(preferred_difficulties(30, 10, "MEDIUM"), ("EASY", "MEDIUM"))
        self.assertEqual(preferred_difficulties(60, 10, "MEDIUM"), ("MEDIUM",))
        self.assertEqual(preferred_difficulties(90, 10, "MEDIUM"), ("MEDIUM", "HARD"))
        self.assertEqual(preferred_difficulties(90, 10, "EASY"), ("EASY", "MEDIUM"))

    def test_candidate_score_uses_topic_sample_time_and_trend(self):
        candidate = {
            "question_id": 11,
            "question_type": "MCQ",
            "difficulty": "MEDIUM",
            "topic_id": 1,
            "subtopic_id": 2,
            "expected_time_seconds": 30,
        }
        declining = {
            "topics": {
                1: {
                    "sample_size": 10,
                    "accuracy": 70,
                    "recent_accuracy": 40,
                    "trend": 30,
                    "recent_count": 4,
                    "average_time": 90,
                    "time_sample_size": 5,
                }
            },
            "subtopics": {2: {"accuracy": 60, "recent_accuracy": 60}},
            "recent_questions": set(),
            "preferred_difficulties": ("MEDIUM",),
            "coding_preferred_difficulties": ("EASY", "MEDIUM"),
        }
        improving = {
            **declining,
            "topics": {
                1: {
                    **declining["topics"][1],
                    "recent_accuracy": 80,
                    "trend": -40,
                }
            },
        }
        low_accuracy_score = score_candidate(candidate, declining)
        high_accuracy_score = score_candidate(candidate, improving)
        self.assertGreater(low_accuracy_score["priority"], high_accuracy_score["priority"])
        self.assertEqual(low_accuracy_score["components"]["time_signal"], 1.0)

    def test_candidate_selection_is_deterministic_exploratory_and_repeat_free(self):
        candidates = [
            {"question_id": 1, "priority": 0.9, "is_exploration": False, "subtopic_id": 1},
            {"question_id": 2, "priority": 0.8, "is_exploration": False, "subtopic_id": 1},
            {"question_id": 3, "priority": 0.7, "is_exploration": True, "subtopic_id": 2},
            {"question_id": 4, "priority": 0.6, "is_exploration": False, "subtopic_id": 1},
            {"question_id": 5, "priority": 0.5, "is_exploration": True, "subtopic_id": 3},
            {"question_id": 6, "priority": 0.4, "is_exploration": False, "subtopic_id": 1},
        ]
        first = choose_candidates(candidates, 5)
        second = choose_candidates(candidates, 5)
        self.assertEqual(
            [item["question_id"] for item in first],
            [item["question_id"] for item in second],
        )
        self.assertEqual(len({item["question_id"] for item in first}), 5)
        self.assertTrue(any(item["is_exploration"] for item in first))
        self.assertTrue(any(not item["is_exploration"] for item in first))
        streak = 0
        previous = None
        for item in first:
            if item["subtopic_id"] == previous:
                streak += 1
            else:
                previous = item["subtopic_id"]
                streak = 1
            self.assertLessEqual(streak, CONFIG.max_same_subtopic_streak)


class AdaptiveApiTests(unittest.TestCase):
    def setUp(self):
        self.user_ids = []
        self.question_ids = []
        self.mock_test_ids = []
        self.attempt_ids = []
        self.coding_submission_ids = []
        self.topic_ids = []
        self.subtopic_ids = []
        self.created_topic_ids = []
        self.created_subtopic_ids = []
        self.track_id = None
        self.multimapped_question_id = None
        self.null_difficulty_id = None
        self.invalid_coding_question_id = None
        self.client = TestClient(app)
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": 9_000_000_000_000_000_000,
            "role": "STUDENT",
        }
        self.addCleanup(self._restore_overrides)
        self.addCleanup(self._cleanup)
        self._create_fixtures()

    def _restore_overrides(self):
        app.dependency_overrides.clear()

    def _create_fixtures(self):
        suffix = uuid.uuid4().hex
        self.email_a = f"adaptive-{suffix}-a@example.test"
        self.email_b = f"adaptive-{suffix}-b@example.test"
        with engine.begin() as conn:
            self.track_id = int(
                conn.execute(
                    text("SELECT track_id FROM tracks ORDER BY track_id LIMIT 1")
                ).scalar_one()
            )
            selected_topics = []
            for topic_index in range(2):
                topic_id = int(
                    conn.execute(
                        text("""
                            INSERT INTO topics (track_id, topic_name, display_order)
                            VALUES (:track_id, :topic_name, :display_order)
                        """),
                        {
                            "track_id": self.track_id,
                            "topic_name": f"Adaptive Test Topic {topic_index} {suffix}",
                            "display_order": topic_index + 1,
                        },
                    ).lastrowid
                )
                self.created_topic_ids.append(topic_id)
                topic_rows = []
                subtopic_ids = []
                for subtopic_index in range(3):
                    subtopic_id = int(
                        conn.execute(
                            text("""
                                INSERT INTO subtopics (
                                    topic_id, subtopic_name, display_order
                                )
                                VALUES (:topic_id, :subtopic_name, :display_order)
                            """),
                            {
                                "topic_id": topic_id,
                                "subtopic_name": (
                                    f"Adaptive Test Subtopic {topic_index}-"
                                    f"{subtopic_index} {suffix}"
                                ),
                                "display_order": subtopic_index + 1,
                            },
                        ).lastrowid
                    )
                    self.created_subtopic_ids.append(subtopic_id)
                    subtopic_ids.append(subtopic_id)
                    topic_rows.append({
                        "track_id": self.track_id,
                        "subtopic_id": subtopic_id,
                    })
                selected_topics.append((topic_id, topic_rows))
                self.topic_ids.append(topic_id)
                self.subtopic_ids.append(subtopic_ids)
            source_id = int(
                conn.execute(
                    text("SELECT source_id FROM sources ORDER BY source_id LIMIT 1")
                ).scalar_one()
            )

            user_ids = []
            for email in (self.email_a, self.email_b):
                result = conn.execute(
                    text("""
                        INSERT INTO users (email, password_hash, display_name, role, is_active)
                        VALUES (:email, 'unused-test-hash', 'Adaptive Test', 'STUDENT', 1)
                    """),
                    {"email": email},
                )
                user_ids.append(int(result.lastrowid))
            self.user_ids = user_ids

            definitions = []
            for topic_index, (topic_id, rows) in enumerate(selected_topics):
                for index in range(7):
                    definitions.append(
                        {
                            "kind": "MCQ",
                            "difficulty": (
                                None
                                if topic_index == 0 and index == 5
                                else ("EASY", "MEDIUM", "HARD")[index % 3]
                            ),
                            "topic_id": topic_id,
                            "track_id": int(rows[0]["track_id"]),
                            "subtopic_id": int(rows[index % min(3, len(rows))]["subtopic_id"]),
                            "title": f"Adaptive fixture MCQ {topic_index}-{index} {suffix}",
                        }
                    )
            first_topic, first_rows = selected_topics[0]
            definitions.append(
                {
                    "kind": "CODING",
                    "difficulty": "EASY",
                    "topic_id": first_topic,
                    "track_id": int(first_rows[0]["track_id"]),
                    "subtopic_id": int(first_rows[0]["subtopic_id"]),
                    "title": f"Adaptive fixture coding {suffix}",
                }
            )
            definitions.append(
                {
                    "kind": "INVALID_CODING",
                    "difficulty": "EASY",
                    "topic_id": first_topic,
                    "track_id": int(first_rows[0]["track_id"]),
                    "subtopic_id": int(first_rows[0]["subtopic_id"]),
                    "title": f"Adaptive invalid coding fixture {suffix}",
                }
            )
            self.invalid_question_id = None
            definitions.append(
                {
                    "kind": "INVALID_MCQ",
                    "difficulty": "EASY",
                    "topic_id": first_topic,
                    "track_id": int(first_rows[0]["track_id"]),
                    "subtopic_id": int(first_rows[0]["subtopic_id"]),
                    "title": f"Adaptive invalid fixture {suffix}",
                }
            )

            for definition in definitions:
                question_type = (
                    "CODING"
                    if definition["kind"] in ("CODING", "INVALID_CODING")
                    else "MCQ"
                )
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
                        "source_id": source_id,
                        "question_type": question_type,
                        "track_id": definition["track_id"],
                        "title": definition["title"],
                        "difficulty": definition["difficulty"],
                        "content_hash": uuid.uuid4().hex + uuid.uuid4().hex,
                    },
                )
                question_id = int(result.lastrowid)
                self.question_ids.append(question_id)
                conn.execute(
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
                if definition["kind"] == "MCQ" and self.multimapped_question_id is None:
                    self.multimapped_question_id = question_id
                if definition["kind"] == "MCQ" and definition["difficulty"] is None:
                    self.null_difficulty_id = question_id
                if definition["kind"] == "INVALID_MCQ":
                    self.invalid_question_id = question_id
                if definition["kind"] == "INVALID_CODING":
                    self.invalid_coding_question_id = question_id
                if definition["kind"] == "CODING":
                    self.coding_id = question_id
                conn.execute(
                    text("""
                        INSERT INTO question_subtopics (question_id, subtopic_id, is_primary)
                        VALUES (:question_id, :subtopic_id, 1)
                    """),
                    {
                        "question_id": question_id,
                        "subtopic_id": definition["subtopic_id"],
                    },
                )
                if definition["kind"] in ("MCQ", "INVALID_MCQ"):
                    conn.execute(
                        text("""
                            INSERT INTO mcq_questions (
                                question_id, question_text, correct_option_key, is_multiple_correct
                            )
                            VALUES (:question_id, :question_text, 'A', 0)
                        """),
                        {
                            "question_id": question_id,
                            "question_text": f"{definition['title']}?",
                        },
                    )
                    count = 3 if definition["kind"] == "INVALID_MCQ" else 4
                    for option_no, option_key in enumerate(("A", "B", "C", "D")[:count], start=1):
                        conn.execute(
                            text("""
                                INSERT INTO mcq_options (
                                    question_id, option_key, option_text, display_order
                                )
                                VALUES (:question_id, :option_key, :option_text, :display_order)
                            """),
                            {
                                "question_id": question_id,
                                "option_key": option_key,
                                "option_text": f"Option {option_key}",
                                "display_order": option_no,
                            },
                        )
                elif definition["kind"] in ("CODING", "INVALID_CODING"):
                    conn.execute(
                        text("""
                            INSERT INTO coding_questions (
                                question_id, problem_statement, constraints_text,
                                input_format, output_format, starter_code
                            )
                            VALUES (
                                :question_id, 'Read an integer and print it.',
                                '1 <= n <= 100', 'One integer n', 'Print n',
                                '#include <iostream>\\nint main() { return 0; }'
                            )
                        """),
                        {"question_id": question_id},
                    )
                    conn.execute(
                        text("""
                            INSERT INTO question_examples (
                                question_id, example_number, input_data, output_data
                            )
                            VALUES (:question_id, 1, '1', '1')
                        """),
                        {"question_id": question_id},
                    )
                    conn.execute(
                        text("""
                            INSERT INTO coding_test_cases (
                                question_id, test_case_number, input_data, expected_output,
                                is_hidden, points
                            )
                            VALUES
                                (:question_id, 1, '1', '1', 0, 1),
                                (:question_id, 2, '2', '2', 1, :hidden_points)
                        """),
                        {
                            "question_id": question_id,
                            "hidden_points": (
                                0 if definition["kind"] == "INVALID_CODING" else 1
                            ),
                        },
                    )

            conn.execute(
                text("""
                    INSERT INTO question_subtopics (question_id, subtopic_id, is_primary)
                    VALUES (:question_id, :subtopic_id, 0)
                """),
                {
                    "question_id": self.multimapped_question_id,
                    "subtopic_id": self.subtopic_ids[0][1],
                },
            )
            self.mcq_ids = [
                question_id
                for question_id in self.question_ids
                if question_id != self.invalid_question_id
                and question_id != self.coding_id
            ]

    def _cleanup(self):
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
                    text("DELETE FROM question_examples WHERE question_id IN :question_ids"),
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
            if self.created_subtopic_ids:
                conn.execute(
                    text("DELETE FROM subtopics WHERE subtopic_id IN :subtopic_ids"),
                    {"subtopic_ids": tuple(self.created_subtopic_ids)},
                )
            if self.created_topic_ids:
                conn.execute(
                    text("DELETE FROM topics WHERE topic_id IN :topic_ids"),
                    {"topic_ids": tuple(self.created_topic_ids)},
                )

    def _as_student(self, index=0):
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": self.user_ids[index],
            "role": "STUDENT",
        }

    def _add_history(self, question_ids, correctness):
        with engine.begin() as conn:
            result = conn.execute(
                text("""
                    INSERT INTO mock_tests (
                        created_by, title, mode, selection_mode,
                        total_questions, status
                    )
                    VALUES (:user_id, 'Adaptive profile fixture', 'PRACTICE',
                            'FIXED_QUESTIONS', :total, 'PUBLISHED')
                """),
                {"user_id": self.user_ids[0], "total": len(question_ids)},
            )
            mock_id = int(result.lastrowid)
            self.mock_test_ids.append(mock_id)
            for sequence_no, question_id in enumerate(question_ids, start=1):
                conn.execute(
                    text("""
                        INSERT INTO mock_test_questions (
                            mock_test_id, question_id, sequence_no, points
                        )
                        VALUES (:mock_id, :question_id, :sequence_no, 1)
                    """),
                    {
                        "mock_id": mock_id,
                        "question_id": question_id,
                        "sequence_no": sequence_no,
                    },
                )
            result = conn.execute(
                text("""
                    INSERT INTO attempts (user_id, mock_test_id, started_at, submitted_at, status)
                    VALUES (:user_id, :mock_id, NOW(), NOW(), 'SUBMITTED')
                """),
                {"user_id": self.user_ids[0], "mock_id": mock_id},
            )
            attempt_id = int(result.lastrowid)
            self.attempt_ids.append(attempt_id)
            for index, (question_id, correct) in enumerate(
                zip(question_ids, correctness),
                start=1,
            ):
                conn.execute(
                    text("""
                        INSERT INTO attempt_answers (
                            attempt_id, question_id, selected_option_key, is_correct,
                            time_spent_seconds, answered_at
                        )
                        VALUES (:attempt_id, :question_id, 'A', :correct, 30,
                                DATE_SUB(NOW(), INTERVAL :seconds SECOND))
                    """),
                    {
                        "attempt_id": attempt_id,
                        "question_id": question_id,
                        "correct": int(correct),
                        "seconds": len(question_ids) - index,
                    },
                )

    def test_cold_start_next_recommendations_and_invalid_question_exclusion(self):
        self._as_student()
        response = self.client.get(
            f"/adaptive/next?user_id={self.user_ids[1]}"
        )
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["status"], "OK")
        question_id = data["question"]["question_id"]
        with engine.connect() as conn:
            self.assertTrue(is_mock_eligible(conn, question_id))
        self.assertNotIn("correct_option_key", data["question"])
        self.assertNotIn("explanation", data["question"])

        first = self.client.get("/adaptive/recommendations?limit=5")
        second = self.client.get("/adaptive/recommendations?limit=5")
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(
            [item["question_id"] for item in first.json()["items"]],
            [item["question_id"] for item in second.json()["items"]],
        )
        result_ids = [item["question_id"] for item in first.json()["items"]]
        self.assertEqual(len(result_ids), len(set(result_ids)))
        self.assertNotIn(self.invalid_question_id, result_ids)
        self.assertTrue(all("reason" in item for item in first.json()["items"]))

    def test_filters_and_no_candidate_response(self):
        self._as_student()
        topic_id = self.topic_ids[0]
        subtopic_id = self.subtopic_ids[0][0]

        topic_result = self.client.get(
            f"/adaptive/recommendations?limit=10&topic_id={topic_id}"
        )
        self.assertTrue(
            all(item["topic_id"] == topic_id for item in topic_result.json()["items"])
        )
        track_result = self.client.get(
            f"/adaptive/recommendations?limit=10&track_id={self.track_id}"
        )
        self.assertEqual(track_result.status_code, 200, track_result.text)
        topic_ids = {item["topic_id"] for item in track_result.json()["items"]}
        with engine.connect() as conn:
            track_topic_ids = set(
                conn.execute(
                    text("SELECT topic_id FROM topics WHERE track_id = :track_id"),
                    {"track_id": self.track_id},
                ).scalars().all()
            )
            invalid_track_id = int(
                conn.execute(
                    text("SELECT COALESCE(MAX(track_id), 0) + 1 FROM topics")
                ).scalar_one()
            )
        self.assertTrue(topic_ids.issubset(track_topic_ids))
        invalid_track = self.client.get(
            f"/adaptive/recommendations?track_id={invalid_track_id}"
        )
        self.assertEqual(invalid_track.status_code, 422)
        subtopic_result = self.client.get(
            f"/adaptive/recommendations?limit=10&topic_id={topic_id}&subtopic_id={subtopic_id}"
        )
        self.assertTrue(
            all(item["subtopic_id"] == subtopic_id for item in subtopic_result.json()["items"])
        )
        difficulty_result = self.client.get(
            "/adaptive/recommendations?limit=10&difficulty=HARD"
        )
        self.assertTrue(
            all(item["difficulty"] == "HARD" for item in difficulty_result.json()["items"])
        )

        other_topic = self.topic_ids[1]
        no_candidates = self.client.get(
            f"/adaptive/recommendations?topic_id={other_topic}&question_type=CODING"
        )
        self.assertEqual(no_candidates.status_code, 200)
        self.assertEqual(no_candidates.json()["status"], "NO_ELIGIBLE_QUESTIONS")
        self.assertEqual(no_candidates.json()["items"], [])

    def test_candidate_pool_excludes_null_difficulty_and_canonicalizes_multiple_mappings(self):
        with engine.connect() as conn:
            candidates = _candidate_pool(conn, "MCQ", self.topic_ids[0], None, None)
        matching = [
            candidate for candidate in candidates
            if candidate["question_id"] == self.multimapped_question_id
        ]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["subtopic_id"], self.subtopic_ids[0][0])
        null_difficulty = [
            candidate for candidate in candidates
            if candidate["question_id"] == self.null_difficulty_id
        ]
        self.assertEqual(null_difficulty, [])
        with engine.connect() as conn:
            coding_candidates = _candidate_pool(
                conn, "CODING", self.topic_ids[0], None, None
            )
        coding_ids = [item["question_id"] for item in coding_candidates]
        self.assertIn(self.coding_id, coding_ids)
        self.assertNotIn(self.invalid_coding_question_id, coding_ids)

    def test_recent_question_avoidance_and_gradual_profile_signal(self):
        self._as_student()
        self._add_history([self.mcq_ids[0]], [True])
        response = self.client.get("/adaptive/recommendations?limit=5")
        self.assertEqual(response.status_code, 200, response.text)
        selected = [item["question_id"] for item in response.json()["items"]]
        self.assertNotIn(self.mcq_ids[0], selected)

        stable_low_questions = self.mcq_ids[:6]
        self._add_history(stable_low_questions, [False] * len(stable_low_questions))
        low = self.client.get(
            f"/adaptive/recommendations?limit=10&topic_id={self.topic_ids[0]}"
        ).json()["items"]
        self.assertTrue(any(item["difficulty"] == "EASY" for item in low))

    def test_fallback_relaxes_recent_repetition_and_difficulty_only_after_need(self):
        self._as_student()
        first_topic_ids = [
            question_id
            for question_id in self.mcq_ids
            if question_id != self.null_difficulty_id
        ]
        self._add_history(
            first_topic_ids + [self.coding_id],
            [False] * (len(first_topic_ids) + 1),
        )
        response = self.client.get(
            f"/adaptive/recommendations?limit=6&topic_id={self.topic_ids[0]}"
        )
        self.assertEqual(response.status_code, 200, response.text)
        items = response.json()["items"]
        self.assertGreaterEqual(len(items), 6)
        self.assertTrue(all(item["reason"]["recently_seen"] for item in items))
        self.assertEqual(len({item["question_id"] for item in items}), len(items))
        with engine.connect() as conn:
            _, fallback_pool, fallback_stage = _ranked_pool(
                conn,
                self.user_ids[0],
                None,
                self.topic_ids[0],
                None,
                None,
                6,
            )
        self.assertEqual(fallback_stage, "RECENT_AND_DIFFICULTY_RELAXED")
        self.assertTrue(any(item["difficulty"] == "HARD" for item in fallback_pool))

    def test_coding_errors_drive_deterministic_coding_recommendation(self):
        self._as_student()
        with engine.begin() as conn:
            for status in ("COMPILE_ERROR", "COMPILE_ERROR"):
                result = conn.execute(
                    text("""
                        INSERT INTO coding_submissions (
                            attempt_id, user_id, question_id, language, source_code,
                            status, tests_passed, tests_total, score
                        )
                        VALUES (
                            NULL, :user_id, :question_id, 'C++17', 'temporary test',
                            :status, 0, 2, 0
                        )
                    """),
                    {
                        "user_id": self.user_ids[0],
                        "question_id": self.coding_id,
                        "status": status,
                    },
                )
                self.coding_submission_ids.append(int(result.lastrowid))
        response = self.client.get("/adaptive/recommendations?question_type=CODING")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["items"][0]["reason"]["recommendation_type"], "DEBUGGING_PRACTICE")

    def test_adaptive_session_reuses_normal_attempt_and_is_owner_scoped(self):
        self._as_student()
        response = self.client.post(
            "/adaptive/session",
            json={
                "number_of_questions": 2,
                "question_type": "MCQ",
                "topic_id": self.topic_ids[0],
                "target_difficulty": "MEDIUM",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["status"], "OK")
        self.assertEqual(data["mode"], "PRACTICE")
        self.assertEqual(len(data["questions"]), 2)
        question_ids = [item["question_id"] for item in data["questions"]]
        self.assertEqual(len(question_ids), len(set(question_ids)))
        self.assertTrue(
            all(item["difficulty"] == "MEDIUM" for item in data["questions"])
        )
        self.assertTrue(
            all("correct_option_key" not in item["content"] for item in data["questions"])
        )
        self.assertTrue(
            all("explanation" not in item["content"] for item in data["questions"])
        )
        self.attempt_ids.append(data["attempt_id"])
        self.mock_test_ids.append(data["mock_test_id"])

        with engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT a.user_id, a.status, mt.mode, mt.blueprint_id
                    FROM attempts a
                    JOIN mock_tests mt ON mt.mock_test_id = a.mock_test_id
                    WHERE a.attempt_id = :attempt_id
                """),
                {"attempt_id": data["attempt_id"]},
            ).mappings().one()
        self.assertEqual(int(row["user_id"]), self.user_ids[0])
        self.assertEqual(row["status"], "IN_PROGRESS")
        self.assertEqual(row["mode"], "PRACTICE")
        self.assertIsNone(row["blueprint_id"])

        retrieved = self.client.get(data["status_url"])
        self.assertEqual(retrieved.status_code, 200, retrieved.text)
        self.assertEqual(retrieved.json()["attempt_status"], "IN_PROGRESS")

        self._as_student(index=1)
        forbidden = self.client.get(data["status_url"])
        self.assertEqual(forbidden.status_code, 404)

    def test_insufficient_candidate_pool_relaxes_preferences_but_not_explicit_filters(self):
        self._as_student()
        response = self.client.post(
            "/adaptive/session",
            json={
                "number_of_questions": 50,
                "question_type": "MCQ",
                "topic_id": self.topic_ids[0],
                "target_difficulty": "EASY",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "OK")
        self.assertLessEqual(len(response.json()["questions"]), 50)
        self.assertTrue(
            all(
                item["question_type"] == "MCQ"
                and item["topic_id"] == self.topic_ids[0]
                and item["difficulty"] == "EASY"
                for item in response.json()["questions"]
            )
        )
        self.attempt_ids.append(response.json()["attempt_id"])
        self.mock_test_ids.append(response.json()["mock_test_id"])


if __name__ == "__main__":
    unittest.main()
