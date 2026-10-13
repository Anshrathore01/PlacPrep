"""Deterministic practice selection using analytics and eligible question-bank data."""

import logging
import time
from collections import defaultdict

from fastapi import HTTPException
from sqlalchemy import bindparam, text

from app.adaptive.rules import (
    CONFIG,
    DIFFICULTY_ORDER,
    preferred_difficulties,
    smoothed_accuracy,
)
from app.judge.config import MAX_CASE_BYTES, MAX_TEST_CASES, MAX_TOTAL_CASE_BYTES
from app.services import attempt_service, blueprint_service, question_service

logger = logging.getLogger(__name__)

ADAPTIVE_CODING_CASE_ELIGIBILITY_SQL = """
    (
        q.question_type <> 'CODING'
        OR (
            (
                SELECT COUNT(*)
                FROM coding_test_cases tc
                WHERE tc.question_id = q.question_id
            ) BETWEEN 1 AND :max_test_cases
            AND NOT EXISTS (
                SELECT 1
                FROM coding_test_cases tc
                WHERE tc.question_id = q.question_id
                  AND (tc.points IS NULL OR tc.points <= 0)
            )
            AND NOT EXISTS (
                SELECT 1
                FROM coding_test_cases tc
                WHERE tc.question_id = q.question_id
                  AND LENGTH(tc.input_data) + LENGTH(tc.expected_output) > :max_case_bytes
            )
            AND (
                SELECT COALESCE(SUM(LENGTH(tc.input_data) + LENGTH(tc.expected_output)), 0)
                FROM coding_test_cases tc
                WHERE tc.question_id = q.question_id
            ) <= :max_total_case_bytes
        )
    )
"""

NO_QUESTIONS = {
    "status": "NO_ELIGIBLE_QUESTIONS",
    "message": "No eligible practice questions are currently available.",
}


def _profile(connection, user_id: int) -> dict:
    answer_rows = connection.execute(
        text("""
            WITH mapping_ranked AS (
                SELECT
                    qs.question_id,
                    s.subtopic_id,
                    s.subtopic_name,
                    t.topic_id,
                    t.topic_name,
                    ROW_NUMBER() OVER (
                        PARTITION BY qs.question_id
                        ORDER BY qs.is_primary DESC, qs.subtopic_id
                    ) AS mapping_rank
                FROM question_subtopics qs
                JOIN subtopics s ON s.subtopic_id = qs.subtopic_id
                JOIN topics t ON t.topic_id = s.topic_id
            )
            SELECT
                q.question_id,
                q.question_type,
                q.difficulty,
                mr.topic_id,
                mr.topic_name,
                mr.subtopic_id,
                mr.subtopic_name,
                aa.is_correct,
                aa.time_spent_seconds,
                aa.answered_at,
                aa.attempt_answer_id
            FROM attempt_answers aa
            JOIN attempts a ON a.attempt_id = aa.attempt_id
            JOIN questions q ON q.question_id = aa.question_id
            LEFT JOIN mapping_ranked mr
              ON mr.question_id = q.question_id
             AND mr.mapping_rank = 1
            WHERE a.user_id = :user_id
              AND a.status = 'SUBMITTED'
              AND q.question_type = 'MCQ'
              AND aa.selected_option_key IS NOT NULL
            ORDER BY aa.answered_at DESC, aa.attempt_answer_id DESC
            LIMIT :history_limit
        """),
        {
            "user_id": user_id,
            "history_limit": max(
                CONFIG.recent_answer_window * 10,
                CONFIG.minimum_topic_sample * 10,
            ),
        },
    ).mappings().all()
    answers = [dict(row) for row in answer_rows]

    topic_history: dict[int, list[dict]] = defaultdict(list)
    subtopic_history: dict[int, list[dict]] = defaultdict(list)
    recent_answers = answers[:CONFIG.recent_answer_window]
    topic_coverage_counts: dict[int, int] = defaultdict(int)
    for answer in recent_answers:
        if answer["topic_id"] is not None:
            topic_coverage_counts[int(answer["topic_id"])] += 1
    for answer in answers:
        if answer["topic_id"] is not None:
            topic_history[int(answer["topic_id"])].append(answer)
        if answer["subtopic_id"] is not None:
            subtopic_history[int(answer["subtopic_id"])].append(answer)

    topics = {}
    for topic_id, rows in topic_history.items():
        recent = rows[:CONFIG.recent_topic_window]
        correct = sum(row["is_correct"] in (True, 1) for row in rows)
        recent_correct = sum(row["is_correct"] in (True, 1) for row in recent)
        historical = rows[CONFIG.recent_topic_window:]
        historical_accuracy = (
            smoothed_accuracy(
                sum(row["is_correct"] in (True, 1) for row in historical),
                len(historical),
            )
            if len(historical) >= CONFIG.minimum_recent_sample
            else None
        )
        recent_accuracy = (
            smoothed_accuracy(recent_correct, len(recent)) if recent else None
        )
        trend = (
            historical_accuracy - recent_accuracy
            if historical_accuracy is not None
            and recent_accuracy is not None
            and len(recent) >= CONFIG.minimum_recent_sample
            else 0.0
        )
        times = [
            float(row["time_spent_seconds"])
            for row in recent
            if row["time_spent_seconds"] is not None
            and float(row["time_spent_seconds"]) > 0
        ]
        topics[topic_id] = {
            "topic_name": rows[0]["topic_name"],
            "sample_size": len(rows),
            "accuracy": smoothed_accuracy(correct, len(rows)),
            "recent_sample_size": len(recent),
            "recent_accuracy": recent_accuracy,
            "historical_accuracy": historical_accuracy,
            "trend": trend,
            "recent_count": topic_coverage_counts.get(topic_id, 0),
            "average_time": sum(times) / len(times) if times else None,
            "time_sample_size": len(times),
        }

    subtopics = {}
    for subtopic_id, rows in subtopic_history.items():
        recent = rows[:CONFIG.recent_topic_window]
        correct = sum(row["is_correct"] in (True, 1) for row in rows)
        subtopics[subtopic_id] = {
            "subtopic_name": rows[0]["subtopic_name"],
            "topic_id": int(rows[0]["topic_id"]),
            "sample_size": len(rows),
            "accuracy": smoothed_accuracy(correct, len(rows)),
            "recent_sample_size": len(recent),
            "recent_accuracy": (
                smoothed_accuracy(
                    sum(row["is_correct"] in (True, 1) for row in recent),
                    len(recent),
                )
                if recent else None
            ),
            "recent_count": len(recent),
        }

    overall_recent_accuracy = (
        smoothed_accuracy(
            sum(row["is_correct"] in (True, 1) for row in recent_answers),
            len(recent_answers),
        )
        if recent_answers else None
    )
    current_difficulty = next(
        (row["difficulty"] for row in recent_answers if row["difficulty"] is not None),
        None,
    )
    preferred = preferred_difficulties(
        overall_recent_accuracy,
        len(recent_answers),
        current_difficulty,
    )

    coding_rows = connection.execute(
        text("""
            SELECT cs.question_id, q.difficulty, cs.status, cs.score,
                   cs.tests_passed, cs.tests_total, cs.submission_id
            FROM coding_submissions cs
            JOIN questions q ON q.question_id = cs.question_id
            WHERE cs.user_id = :user_id
            ORDER BY cs.submitted_at DESC, cs.submission_id DESC
            LIMIT :history_limit
        """),
        {"user_id": user_id, "history_limit": CONFIG.recent_question_window * 10},
    ).mappings().all()
    coding = [dict(row) for row in coding_rows]
    finalized_coding = [
        row
        for row in coding
        if row["status"] in (
            "PASSED",
            "FAILED",
            "COMPILE_ERROR",
            "RUNTIME_ERROR",
            "TIME_LIMIT",
        )
    ]
    coding_errors = {
        status: sum(row["status"] == status for row in finalized_coding)
        for status in ("COMPILE_ERROR", "RUNTIME_ERROR", "FAILED", "TIME_LIMIT")
    }
    coding_by_problem: dict[int, list[dict]] = defaultdict(list)
    for row in finalized_coding:
        coding_by_problem[int(row["question_id"])].append(row)
    recent_coding_problems = []
    for problem_rows in coding_by_problem.values():
        best = max(
            problem_rows,
            key=lambda row: (
                float(row["score"] or 0),
                int(row["submission_id"]),
            ),
        )
        ratio = (
            float(best["tests_passed"]) / float(best["tests_total"])
            if best["tests_total"] and float(best["tests_total"]) > 0
            else None
        )
        recent_coding_problems.append(
            {
                "solved": any(row["status"] == "PASSED" for row in problem_rows),
                "difficulty": problem_rows[0]["difficulty"],
                "submission_count": len(problem_rows),
                "best_score": float(best["score"] or 0),
                "best_test_ratio": ratio,
                "latest_submission_id": max(
                    int(row["submission_id"]) for row in problem_rows
                ),
            }
        )
    recent_coding_problems.sort(
        key=lambda row: row["latest_submission_id"],
        reverse=True,
    )
    recent_coding_problems = recent_coding_problems[:CONFIG.recent_question_window]
    recent_coding_solved = sum(row["solved"] for row in recent_coding_problems)
    coding_accuracy = (
        smoothed_accuracy(recent_coding_solved, len(recent_coding_problems))
        if recent_coding_problems else None
    )
    if (
        len(recent_coding_problems) >= CONFIG.minimum_recent_sample
        and coding_accuracy is not None
    ):
        recent_levels = [
            DIFFICULTY_ORDER.index(row["difficulty"])
            for row in recent_coding_problems
            if row["difficulty"] in DIFFICULTY_ORDER
        ]
        if coding_accuracy < CONFIG.low_accuracy_threshold:
            preferred_coding = tuple(
                DIFFICULTY_ORDER[max(0, max(recent_levels or [1]) - 1):
                                 max(recent_levels or [1]) + 1]
            )
        elif coding_accuracy > CONFIG.high_accuracy_threshold:
            latest_level = recent_levels[0] if recent_levels else 0
            next_level = min(len(DIFFICULTY_ORDER) - 1, latest_level + 1)
            preferred_coding = (DIFFICULTY_ORDER[next_level],)
        else:
            preferred_coding = ("MEDIUM",)
    else:
        preferred_coding = ("EASY", "MEDIUM")

    seen_rows = connection.execute(
        text("""
            SELECT question_id, MAX(last_seen) AS last_seen
            FROM (
                SELECT mtq.question_id, MAX(a.started_at) AS last_seen
                FROM attempts a
                JOIN mock_test_questions mtq ON mtq.mock_test_id = a.mock_test_id
                WHERE a.user_id = :user_id
                GROUP BY mtq.question_id
                UNION ALL
                SELECT cs.question_id, MAX(cs.submitted_at) AS last_seen
                FROM coding_submissions cs
                WHERE cs.user_id = :user_id
                GROUP BY cs.question_id
            ) seen_questions
            GROUP BY question_id
            ORDER BY last_seen DESC, question_id DESC
            LIMIT :window_size
        """),
        {"user_id": user_id, "window_size": CONFIG.recent_question_window},
    ).scalars().all()

    return {
        "topics": topics,
        "subtopics": subtopics,
        "recent_questions": {int(row) for row in seen_rows},
        "recent_accuracy": overall_recent_accuracy,
        "recent_sample_size": len(recent_answers),
        "current_difficulty": current_difficulty,
        "preferred_difficulties": preferred,
        "coding_preferred_difficulties": preferred_coding,
        "coding_errors": coding_errors,
        "recent_coding_sample_size": len(recent_coding_problems),
        "coding_best_score_mean": (
            sum(row["best_score"] for row in recent_coding_problems)
            / len(recent_coding_problems)
            if recent_coding_problems else None
        ),
        "coding_best_test_ratio_mean": (
            sum(
                row["best_test_ratio"]
                for row in recent_coding_problems
                if row["best_test_ratio"] is not None
            )
            / sum(
                row["best_test_ratio"] is not None
                for row in recent_coding_problems
            )
            if any(row["best_test_ratio"] is not None for row in recent_coding_problems)
            else None
        ),
        "coding_submission_count": len(finalized_coding),
        "coding_problems_attempted": len(coding_by_problem),
        "coding_problems_solved": sum(
            any(row["status"] == "PASSED" for row in problem_rows)
            for problem_rows in coding_by_problem.values()
        ),
    }


def score_candidate(candidate: dict, profile: dict) -> dict:
    topic = profile["topics"].get(int(candidate["topic_id"])) if candidate["topic_id"] else None
    subtopic = profile["subtopics"].get(int(candidate["subtopic_id"])) if candidate["subtopic_id"] else None
    preferred = (
        profile["coding_preferred_difficulties"]
        if candidate["question_type"] == "CODING"
        else profile["preferred_difficulties"]
    )

    topic_need = (
        1.0 - (float(topic["recent_accuracy"] or topic["accuracy"]) / 100.0)
        if topic else CONFIG.unknown_dimension_need
    )
    if (
        candidate["question_type"] == "CODING"
        and profile["recent_coding_sample_size"] >= CONFIG.minimum_recent_sample
        and profile["coding_best_test_ratio_mean"] is not None
    ):
        topic_need = 1.0 - profile["coding_best_test_ratio_mean"]
    if topic and topic["sample_size"] >= CONFIG.minimum_topic_sample:
        topic_need += max(
            -CONFIG.trend_adjustment_limit,
            min(CONFIG.trend_adjustment_limit, float(topic["trend"]) / 100.0),
        )
    subtopic_need = (
        1.0 - (float(subtopic["recent_accuracy"] or subtopic["accuracy"]) / 100.0)
        if subtopic else CONFIG.unknown_dimension_need
    )
    if candidate["difficulty"] is None:
        difficulty_fit = CONFIG.unknown_difficulty_fit
    elif candidate["difficulty"] in preferred:
        difficulty_fit = 1.0
    else:
        difficulty_fit = CONFIG.unknown_difficulty_fit
    recently_seen = int(candidate["question_id"]) in profile["recent_questions"]
    novelty = 0.0 if recently_seen else 1.0
    topic_recent_count = topic["recent_count"] if topic else 0
    coverage = 1.0 / (1.0 + topic_recent_count)

    time_signal = CONFIG.unknown_dimension_need
    if (
        candidate["question_type"] == "MCQ"
        and topic
        and topic["time_sample_size"] >= CONFIG.minimum_time_sample
        and topic["average_time"] is not None
        and candidate["expected_time_seconds"]
        and candidate["expected_time_seconds"] > 0
    ):
        ratio = topic["average_time"] / float(candidate["expected_time_seconds"])
        time_signal = min(
            1.0,
            max(
                0.0,
                (ratio - CONFIG.time_baseline_ratio) / CONFIG.time_signal_range,
            ),
        )

    components = {
        "topic_need": min(1.0, max(0.0, topic_need)),
        "subtopic_need": min(1.0, max(0.0, subtopic_need)),
        "difficulty_fit": difficulty_fit,
        "novelty": novelty,
        "coverage": min(1.0, max(0.0, coverage)),
        "time_signal": time_signal,
    }
    priority = sum(
        components[name] * weight
        for name, weight in CONFIG.candidate_weights
    )
    has_evidence = bool(topic and topic["sample_size"] >= CONFIG.minimum_topic_sample)
    underrepresented = topic is None or topic_recent_count == 0
    is_exploration = not has_evidence or underrepresented

    return {
        **candidate,
        "priority": round(min(1.0, max(0.0, priority)), 4),
        "components": components,
        "topic_profile": topic,
        "subtopic_profile": subtopic,
        "recently_seen": recently_seen,
        "is_exploration": is_exploration,
    }


def choose_candidates(
    ranked_candidates: list[dict],
    limit: int,
    *,
    max_same_subtopic_streak: int = CONFIG.max_same_subtopic_streak,
    exploration_ratio: float = CONFIG.exploration_ratio,
) -> list[dict]:
    """Choose a repeat-free set with a deterministic exploration proportion."""
    if limit <= 0:
        return []
    candidates = sorted(
        ranked_candidates,
        key=lambda item: (-item["priority"], int(item["question_id"])),
    )
    exploration = [item for item in candidates if item["is_exploration"]]
    exploitation = [item for item in candidates if not item["is_exploration"]]
    exploration_target = round(limit * exploration_ratio)
    desired = []
    desired.extend(exploration[:exploration_target])
    desired.extend(exploitation[:limit - len(desired)])
    desired.extend(candidates)

    selected = []
    selected_ids = set()
    last_subtopic = None
    streak = 0
    for item in desired:
        question_id = int(item["question_id"])
        if question_id in selected_ids:
            continue
        subtopic_id = item.get("subtopic_id")
        if (
            subtopic_id is not None
            and subtopic_id == last_subtopic
            and streak >= max_same_subtopic_streak
        ):
            continue
        selected.append(item)
        selected_ids.add(question_id)
        if subtopic_id is None:
            last_subtopic = None
            streak = 0
        elif subtopic_id == last_subtopic:
            streak += 1
        else:
            last_subtopic = subtopic_id
            streak = 1
        if len(selected) == limit:
            return selected

    # If diversity alone prevented filling the requested count, fill remaining
    # slots from the unused valid pool rather than silently dropping questions.
    for item in candidates:
        question_id = int(item["question_id"])
        if question_id not in selected_ids:
            selected.append(item)
            selected_ids.add(question_id)
            if len(selected) == limit:
                break
    return selected


def _validate_filters(
    connection,
    topic_id: int | None,
    subtopic_id: int | None,
    track_id: int | None,
) -> None:
    if track_id is not None:
        track_exists = connection.execute(
            text("SELECT 1 FROM topics WHERE track_id = :track_id LIMIT 1"),
            {"track_id": track_id},
        ).scalar_one_or_none()
        if track_exists is None:
            raise HTTPException(status_code=422, detail="Track does not exist.")
    if topic_id is not None:
        topic_track = connection.execute(
            text("SELECT track_id FROM topics WHERE topic_id = :topic_id"),
            {"topic_id": topic_id},
        ).scalar_one_or_none()
        if topic_track is None:
            raise HTTPException(status_code=422, detail="Topic does not exist.")
        if track_id is not None and int(topic_track) != track_id:
            raise HTTPException(
                status_code=422,
                detail="Topic does not belong to the supplied track.",
            )
    if subtopic_id is not None:
        subtopic = connection.execute(
            text("""
                SELECT st.topic_id, t.track_id
                FROM subtopics st
                JOIN topics t ON t.topic_id = st.topic_id
                WHERE st.subtopic_id = :subtopic_id
            """),
            {"subtopic_id": subtopic_id},
        ).mappings().first()
        if subtopic is None:
            raise HTTPException(status_code=422, detail="Subtopic does not exist.")
        if topic_id is not None and int(subtopic["topic_id"]) != topic_id:
            raise HTTPException(
                status_code=422,
                detail="Subtopic does not belong to the supplied topic.",
            )
        if track_id is not None and int(subtopic["track_id"]) != track_id:
            raise HTTPException(
                status_code=422,
                detail="Subtopic does not belong to the supplied track.",
            )


def _candidate_pool(
    connection,
    question_type: str | None,
    topic_id: int | None,
    subtopic_id: int | None,
    difficulty: str | None,
    track_id: int | None = None,
    eligible_question_ids: list[int] | None = None,
) -> list[dict]:
    _validate_filters(connection, topic_id, subtopic_id, track_id)
    if eligible_question_ids is not None and not eligible_question_ids:
        return []
    filters = [
        blueprint_service.ELIGIBLE_QUESTION_SQL,
        ADAPTIVE_CODING_CASE_ELIGIBILITY_SQL,
    ]
    params = {
        "pool_limit": CONFIG.max_candidate_pool,
        "max_test_cases": MAX_TEST_CASES,
        "max_case_bytes": MAX_CASE_BYTES,
        "max_total_case_bytes": MAX_TOTAL_CASE_BYTES,
    }
    if question_type is not None:
        filters.append("q.question_type = :question_type")
        params["question_type"] = question_type
    if track_id is not None:
        filters.append("q.track_id = :track_id")
        params["track_id"] = track_id
    if eligible_question_ids is not None:
        filters.append("q.question_id IN :eligible_question_ids")
        params["eligible_question_ids"] = eligible_question_ids
    if topic_id is not None:
        filters.append("""
            EXISTS (
                SELECT 1
                FROM question_subtopics qs
                JOIN subtopics st ON st.subtopic_id = qs.subtopic_id
                WHERE qs.question_id = q.question_id
                  AND st.topic_id = :topic_id
            )
        """)
        params["topic_id"] = topic_id
    if subtopic_id is not None:
        filters.append("""
            EXISTS (
                SELECT 1
                FROM question_subtopics qs
                WHERE qs.question_id = q.question_id
                  AND qs.subtopic_id = :subtopic_id
            )
        """)
        params["subtopic_id"] = subtopic_id
    if difficulty is not None:
        filters.append("q.difficulty = :difficulty")
        params["difficulty"] = difficulty

    statement = text(f"""
            WITH mapping_ranked AS (
                SELECT
                    qs.question_id,
                    qs.subtopic_id,
                    s.subtopic_name,
                    t.topic_id,
                    t.topic_name,
                    ROW_NUMBER() OVER (
                        PARTITION BY qs.question_id
                        ORDER BY qs.is_primary DESC, qs.subtopic_id
                    ) AS mapping_rank
                FROM question_subtopics qs
                JOIN subtopics s ON s.subtopic_id = qs.subtopic_id
                JOIN topics t ON t.topic_id = s.topic_id
            )
            SELECT
                q.question_id,
                q.title,
                q.question_type,
                q.difficulty,
                q.expected_time_seconds,
                q.track_id,
                mr.topic_id,
                mr.topic_name,
                mr.subtopic_id,
                mr.subtopic_name
            FROM questions q
            JOIN mapping_ranked mr
              ON mr.question_id = q.question_id
             AND mr.mapping_rank = 1
            WHERE {" AND ".join(f"({item})" for item in filters)}
            ORDER BY q.updated_at DESC, q.question_id DESC
            LIMIT :pool_limit
        """)
    if eligible_question_ids is not None:
        statement = statement.bindparams(
            bindparam("eligible_question_ids", expanding=True)
        )
    rows = connection.execute(statement, params).mappings().all()
    return [dict(row) for row in rows]


def _reason(candidate: dict, profile: dict) -> dict:
    topic = candidate["topic_profile"]
    subtopic = candidate["subtopic_profile"]
    topic_accuracy = (
        float(topic["accuracy"]) if topic and topic["sample_size"] >= CONFIG.minimum_topic_sample else None
    )
    topic_sample = topic["sample_size"] if topic else 0
    recent_accuracy = float(topic["recent_accuracy"]) if topic and topic["recent_accuracy"] is not None else None
    recent_sample = topic["recent_sample_size"] if topic else 0

    if candidate["question_type"] == "CODING":
        if profile["coding_errors"]["COMPILE_ERROR"] >= CONFIG.coding_error_repeat_threshold:
            recommendation_type = "DEBUGGING_PRACTICE"
            reason_text = "Recent coding submissions include compile errors."
        elif profile["coding_errors"]["TIME_LIMIT"] >= CONFIG.coding_error_repeat_threshold:
            recommendation_type = "OPTIMIZATION_PRACTICE"
            reason_text = "Recent coding submissions include time-limit failures."
        elif topic_sample < CONFIG.minimum_topic_sample:
            recommendation_type = "CONCEPT_PRACTICE"
            reason_text = "Limited recent coding practice in this topic."
        elif candidate["difficulty"] == "MEDIUM" and "HARD" in profile["coding_preferred_difficulties"]:
            recommendation_type = "DIFFICULTY_PROGRESS"
            reason_text = "Recent coding results support a gradual difficulty increase."
        else:
            recommendation_type = "IMPLEMENTATION_PRACTICE"
            reason_text = "Provides additional practice for this coding topic."
    elif topic is None or topic_sample < CONFIG.minimum_topic_sample:
        recommendation_type = "TOPIC_EXPLORATION"
        reason_text = "Limited recent practice in this topic."
    elif recent_accuracy is not None and recent_accuracy < CONFIG.low_accuracy_threshold:
        recommendation_type = "CONCEPT_PRACTICE"
        reason_text = "Recent accuracy is below the configured threshold."
    elif candidate["is_exploration"]:
        recommendation_type = "TOPIC_EXPLORATION"
        reason_text = "Provides exploration of an underrepresented topic."
    elif candidate["recently_seen"]:
        recommendation_type = "IMPLEMENTATION_PRACTICE"
        reason_text = "The eligible question pool is limited; this question is repeated after unseen options."
    elif candidate["difficulty"] in profile["preferred_difficulties"]:
        recommendation_type = "DIFFICULTY_PROGRESS"
        reason_text = "Suitable difficulty based on recent performance."
    else:
        recommendation_type = "CONCEPT_PRACTICE"
        reason_text = "Not attempted recently."

    return {
        "text": reason_text,
        "topic_accuracy": topic_accuracy,
        "topic_sample_size": topic_sample,
        "recent_accuracy": recent_accuracy,
        "recent_sample_size": recent_sample,
        "difficulty": candidate["difficulty"],
        "recently_seen": candidate["recently_seen"],
        "recommendation_type": recommendation_type,
    }


def _ranked_pool(
    connection,
    user_id: int,
    question_type: str | None,
    topic_id: int | None,
    subtopic_id: int | None,
    requested_difficulty: str | None,
    required_count: int,
    track_id: int | None = None,
) -> tuple[dict, list[dict], str]:
    profile = _profile(connection, user_id)
    explicit_difficulty = requested_difficulty is not None
    preferred = (requested_difficulty,) if explicit_difficulty else None
    if question_type == "CODING" and not explicit_difficulty:
        preferred = profile["coding_preferred_difficulties"]
    elif not explicit_difficulty:
        preferred = profile["preferred_difficulties"]

    pool = _candidate_pool(
        connection,
        question_type,
        topic_id,
        subtopic_id,
        requested_difficulty,
        track_id,
    )
    scored = [score_candidate(row, profile) for row in pool]
    unseen_preferred = [
        row for row in scored
        if row["difficulty"] in preferred and not row["recently_seen"]
    ]
    all_preferred = [row for row in scored if row["difficulty"] in preferred]
    unseen_any_difficulty = [row for row in scored if not row["recently_seen"]]

    if len(unseen_preferred) >= required_count:
        # Strictest case: enough unseen questions at the preferred difficulty.
        candidates, fallback = unseen_preferred, "STRICT"

    elif len(all_preferred) >= required_count:
        # We need to relax recent-question exclusion.
        # Prefer recently seen questions first when they are sufficient,
        # so the relaxation is explicit and does not reintroduce exploration.
        recently_seen_preferred = [
            row for row in all_preferred
            if row["recently_seen"]
        ]

        if len(recently_seen_preferred) >= required_count:
            candidates = recently_seen_preferred
        else:
            # Not enough recently seen questions to fill the request,
            # so use the complete preferred pool.
            candidates = all_preferred

        fallback = "RECENT_QUESTIONS_RELAXED"

    elif len(unseen_any_difficulty) >= required_count:
        # Enough unseen questions exist, but preferred difficulty is too scarce.
        candidates, fallback = unseen_any_difficulty, "DIFFICULTY_RELAXED"

    else:
        # Both recent-question exclusion and preferred difficulty
        # must be relaxed.
        candidates, fallback = scored, "RECENT_AND_DIFFICULTY_RELAXED"

    # Keep the user's explicit difficulty filter absolute. The SQL pool already
    # enforces it, so no fallback can introduce a different difficulty.
    if explicit_difficulty and not scored:
        return profile, [], "NO_ELIGIBLE_QUESTIONS"
    return profile, candidates, fallback


def get_recommendations(
    connection,
    user_id: int,
    limit: int,
    question_type: str | None = None,
    topic_id: int | None = None,
    subtopic_id: int | None = None,
    difficulty: str | None = None,
    track_id: int | None = None,
) -> dict:
    started = time.perf_counter()
    limit = min(limit, CONFIG.max_recommendations)
    profile, candidates, fallback = _ranked_pool(
        connection, user_id, question_type, topic_id, subtopic_id, difficulty, limit,
        track_id,
    )
    if fallback in (
        "RECENT_QUESTIONS_RELAXED",
        "RECENT_AND_DIFFICULTY_RELAXED",
    ):
        recently_seen_candidates = [
            candidate for candidate in candidates
            if candidate["recently_seen"]
        ]
        if len(recently_seen_candidates) >= limit:
            selected = choose_candidates(
                recently_seen_candidates,
                limit,
                exploration_ratio=0.0,
            )
        else:
            selected = choose_candidates(candidates, limit)
    else:
        selected = choose_candidates(candidates, limit)
    items = []
    for candidate in selected:
        items.append(
            {
                "question_id": int(candidate["question_id"]),
                "priority": candidate["priority"],
                "question_type": candidate["question_type"],
                "title": candidate["title"],
                "difficulty": candidate["difficulty"],
                "topic_id": candidate["topic_id"],
                "topic_name": candidate["topic_name"],
                "subtopic_id": candidate["subtopic_id"],
                "subtopic_name": candidate["subtopic_name"],
                "reason": _reason(candidate, profile),
            }
        )

    status = "OK" if items else "NO_ELIGIBLE_QUESTIONS"
    logger.info(
        "Adaptive recommendation outcome user_id=%s status=%s candidate_count=%s selected_ids=%s fallback=%s duration_ms=%.2f",
        user_id,
        status,
        len(candidates),
        [item["question_id"] for item in items],
        fallback,
        (time.perf_counter() - started) * 1000,
    )
    return {
        "status": status,
        "message": None if items else NO_QUESTIONS["message"],
        "items": items,
    }


def get_next(
    connection,
    user_id: int,
    question_type: str | None = None,
    topic_id: int | None = None,
    subtopic_id: int | None = None,
    difficulty: str | None = None,
    track_id: int | None = None,
) -> dict:
    recommendations = get_recommendations(
        connection,
        user_id,
        1,
        question_type,
        topic_id,
        subtopic_id,
        difficulty,
        track_id,
    )
    if not recommendations["items"]:
        return {
            "status": "NO_ELIGIBLE_QUESTIONS",
            "message": NO_QUESTIONS["message"],
            "question": None,
            "reason": None,
        }
    item = recommendations["items"][0]
    question = question_service.get_question_detail_student(
        connection, item["question_id"]
    )
    return {
        "status": "OK",
        "message": None,
        "question": question,
        "reason": item["reason"],
    }


def create_session(
    connection,
    user_id: int,
    number_of_questions: int | None,
    question_type: str | None = None,
    topic_id: int | None = None,
    subtopic_id: int | None = None,
    target_difficulty: str | None = None,
    duration_seconds: int | None = None,
    track_id: int | None = None,
    blueprint_id: int | None = None,
) -> dict:
    if blueprint_id is not None:
        if any(
            value is not None
            for value in (
                question_type,
                topic_id,
                subtopic_id,
                target_difficulty,
                track_id,
            )
        ):
            raise HTTPException(
                status_code=422,
                detail=(
                    "Blueprint adaptive practice cannot be combined with "
                    "generic question filters."
                ),
            )
        return create_blueprint_session(
            connection,
            user_id,
            blueprint_id,
            number_of_questions,
            duration_seconds,
        )

    number_of_questions = number_of_questions or 10
    started = time.perf_counter()
    profile, candidates, fallback = _ranked_pool(
        connection,
        user_id,
        question_type,
        topic_id,
        subtopic_id,
        target_difficulty,
        number_of_questions,
        track_id,
    )
    selected = choose_candidates(candidates, number_of_questions)
    if not selected:
        logger.info(
            "Adaptive session outcome user_id=%s status=NO_ELIGIBLE_QUESTIONS candidate_count=0 duration_ms=%.2f",
            user_id,
            (time.perf_counter() - started) * 1000,
        )
        return {
            **NO_QUESTIONS,
            "session_id": None,
            "attempt_id": None,
            "mock_test_id": None,
            "status_url": None,
            "title": None,
            "mode": None,
            "duration_seconds": None,
            "questions": [],
        }

    question_ids = [int(item["question_id"]) for item in selected]
    blueprint_service._lock_questions(connection, question_ids)
    mock = blueprint_service.insert_mock_test(
        connection,
        "Adaptive practice",
        "PRACTICE",
        duration_seconds,
        question_ids,
        user_id,
    )
    attempt = attempt_service.create_attempt(
        connection,
        requesting_user_id=user_id,
        mock_test_id=int(mock["mock_test_id"]),
    )
    questions = []
    for sequence, candidate in enumerate(selected, start=1):
        content = question_service.get_question_detail_student(
            connection, int(candidate["question_id"])
        )
        questions.append(
            {
                "question_id": int(candidate["question_id"]),
                "priority": candidate["priority"],
                "question_type": candidate["question_type"],
                "title": candidate["title"],
                "difficulty": candidate["difficulty"],
                "topic_id": candidate["topic_id"],
                "topic_name": candidate["topic_name"],
                "subtopic_id": candidate["subtopic_id"],
                "subtopic_name": candidate["subtopic_name"],
                "reason": _reason(candidate, profile),
                "sequence_no": sequence,
                "points": 1.0,
                "content": content,
            }
        )
    logger.info(
        "Adaptive session created user_id=%s session_id=%s attempt_id=%s mock_test_id=%s selected_ids=%s candidate_count=%s fallback=%s duration_ms=%.2f",
        user_id,
        attempt["attempt_id"],
        attempt["attempt_id"],
        mock["mock_test_id"],
        question_ids,
        len(candidates),
        fallback,
        (time.perf_counter() - started) * 1000,
    )
    return {
        "status": "OK",
        "message": None,
        "session_id": int(attempt["attempt_id"]),
        "attempt_id": int(attempt["attempt_id"]),
        "mock_test_id": int(mock["mock_test_id"]),
        "status_url": f"/adaptive/session/{attempt['attempt_id']}",
        "title": mock["title"],
        "mode": "PRACTICE",
        "practice_mode": "ADAPTIVE_PRACTICE",
        "company": None,
        "company_id": None,
        "program": None,
        "pattern_version": None,
        "blueprint_id": None,
        "duration_seconds": mock["duration_seconds"],
        "questions": questions,
    }


def _adaptive_rule_candidates(
    connection,
    profile: dict,
    blueprint: dict,
    rule: dict,
    eligible_question_ids: list[int],
) -> list[int]:
    pool = _candidate_pool(
        connection,
        rule.get("question_type"),
        rule.get("topic_id"),
        rule.get("subtopic_id"),
        rule.get("difficulty"),
        rule.get("track_id") or blueprint.get("track_id"),
        eligible_question_ids,
    )
    scored = [score_candidate(row, profile) for row in pool]
    def prefers(candidate: dict) -> bool:
        preferred = (
            profile["coding_preferred_difficulties"]
            if candidate["question_type"] == "CODING"
            else profile["preferred_difficulties"]
        )
        return candidate["difficulty"] in preferred

    tiers = (
        [
            row for row in scored
            if prefers(row) and not row["recently_seen"]
        ],
        [row for row in scored if prefers(row)],
        [row for row in scored if not row["recently_seen"]],
        scored,
    )
    ordered = []
    seen = set()
    for tier in tiers:
        for candidate in choose_candidates(tier, len(tier)):
            question_id = int(candidate["question_id"])
            if question_id not in seen:
                ordered.append(question_id)
                seen.add(question_id)
    return ordered


def create_blueprint_session(
    connection,
    user_id: int,
    blueprint_id: int,
    number_of_questions: int | None = None,
    duration_seconds: int | None = None,
) -> dict:
    blueprint = blueprint_service.get_blueprint(
        connection, blueprint_id, lock=True
    )
    if (
        blueprint["status"] != "ACTIVE"
        or not blueprint_service._effective_now(connection, blueprint)
    ):
        raise HTTPException(
            status_code=409,
            detail="Only active blueprints can be used for adaptive practice.",
        )
    errors = blueprint_service.validate_blueprint(connection, blueprint_id)
    if errors:
        insufficient = any(
            "available" in error
            or error.get("code") == "INSUFFICIENT_BLUEPRINT_CONTENT"
            for error in errors
        )
        raise HTTPException(
            status_code=409,
            detail={
                "code": (
                    "INSUFFICIENT_BLUEPRINT_CONTENT"
                    if insufficient else "INVALID_BLUEPRINT"
                ),
                "blueprint_id": blueprint_id,
                "company": blueprint.get("company_name"),
                "errors": errors,
            },
        )

    rules = blueprint["rules"]
    required_total = sum(
        int(rule["question_count"])
        for rule in rules
        if rule.get("is_required", True)
        or len(
            blueprint_service._candidate_question_ids(connection, blueprint, rule)
        ) >= int(rule["question_count"])
    )
    if number_of_questions is not None and number_of_questions != required_total:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "BLUEPRINT_COMPOSITION_MISMATCH",
                "blueprint_id": blueprint_id,
                "required": required_total,
                "requested": number_of_questions,
            },
        )

    profile = _profile(connection, user_id)
    candidates_by_rule = [
        _adaptive_rule_candidates(
            connection,
            profile,
            blueprint,
            rule,
            blueprint_service._candidate_question_ids(connection, blueprint, rule),
        )
        for rule in rules
    ]
    selections = blueprint_service._allocate_unique_questions(
        rules,
        candidates_by_rule,
        preserve_candidate_order=True,
    )
    company = blueprint.get("company_name")
    program = blueprint.get("program_name")
    version = blueprint.get("pattern_version")
    context_parts = [value for value in (company, program, version) if value]
    title = " ".join(context_parts + ["Company-Style Adaptive Practice"])
    mock = blueprint_service.create_mock_test_from_blueprint(
        connection,
        blueprint_id,
        title,
        "PRACTICE",
        user_id,
        selections=selections,
    )
    attempt = attempt_service.create_attempt(
        connection,
        requesting_user_id=user_id,
        mock_test_id=int(mock["mock_test_id"]),
    )
    selected_by_id = {
        int(candidate["question_id"]): candidate
        for rule, ids in zip(rules, candidates_by_rule)
        for candidate in _candidate_pool(
            connection,
            rule.get("question_type"),
            rule.get("topic_id"),
            rule.get("subtopic_id"),
            rule.get("difficulty"),
            rule.get("track_id") or blueprint.get("track_id"),
            ids,
        )
    }
    questions = []
    sequence = 0
    rules_by_id = {
        int(rule["blueprint_rule_id"]): rule
        for rule in rules
    }
    for selection in selections:
        rule = rules_by_id[int(selection["blueprint_rule_id"])]
        for question_id in selection["question_ids"]:
            sequence += 1
            candidate = score_candidate(selected_by_id[question_id], profile)
            content = question_service.get_question_detail_student(
                connection, question_id
            )
            questions.append(
                {
                    "question_id": question_id,
                    "priority": candidate["priority"],
                    "question_type": candidate["question_type"],
                    "title": candidate["title"],
                    "difficulty": candidate["difficulty"],
                    "topic_id": candidate["topic_id"],
                    "topic_name": candidate["topic_name"],
                    "subtopic_id": candidate["subtopic_id"],
                    "subtopic_name": candidate["subtopic_name"],
                    "reason": _reason(candidate, profile),
                    "sequence_no": sequence,
                    "points": selection["points"],
                    "blueprint_rule_id": selection["blueprint_rule_id"],
                    "section_name": rule.get("section_name"),
                    "section_order": rule.get("section_order"),
                    "content": content,
                }
            )
    return {
        "status": "OK",
        "message": None,
        "session_id": int(attempt["attempt_id"]),
        "attempt_id": int(attempt["attempt_id"]),
        "mock_test_id": int(mock["mock_test_id"]),
        "status_url": f"/adaptive/session/{attempt['attempt_id']}",
        "title": mock["title"],
        "mode": "PRACTICE",
        "practice_mode": "ADAPTIVE_PRACTICE",
        "company": company,
        "company_id": blueprint.get("company_id"),
        "program": program,
        "pattern_version": version,
        "blueprint_id": blueprint_id,
        "duration_seconds": mock["duration_seconds"],
        "questions": questions,
    }


def get_session(connection, user_id: int, session_id: int) -> dict:
    attempt = connection.execute(
        text("""
            SELECT
                a.attempt_id,
                a.user_id,
                a.mock_test_id,
                a.status AS attempt_status,
                a.started_at,
                a.submitted_at,
                mt.title,
                mt.mode,
                mt.duration_seconds,
                mt.selection_mode,
                mt.blueprint_id,
                c.company_name,
                tb.program_name,
                tb.pattern_version,
                tb.company_id
            FROM attempts a
            JOIN mock_tests mt ON mt.mock_test_id = a.mock_test_id
            LEFT JOIN test_blueprints tb ON tb.blueprint_id = mt.blueprint_id
            LEFT JOIN companies c ON c.company_id = tb.company_id
            WHERE a.attempt_id = :attempt_id
              AND a.user_id = :user_id
              AND mt.mode = 'PRACTICE'
        """),
        {"attempt_id": session_id, "user_id": user_id},
    ).mappings().first()
    if attempt is None:
        raise HTTPException(status_code=404, detail="Adaptive practice session not found.")

    rows = connection.execute(
        text("""
            SELECT mtq.question_id, mtq.sequence_no, mtq.points
            FROM mock_test_questions mtq
            WHERE mtq.mock_test_id = :mock_test_id
            ORDER BY mtq.sequence_no
        """),
        {"mock_test_id": attempt["mock_test_id"]},
    ).mappings().all()
    section_by_sequence = {}
    if attempt["blueprint_id"] is not None:
        blueprint = blueprint_service.get_blueprint(
            connection, int(attempt["blueprint_id"])
        )
        next_sequence = 1
        for rule in blueprint["rules"]:
            candidates = blueprint_service._candidate_question_ids(
                connection, blueprint, rule
            )
            if not rule.get("is_required", True) and len(candidates) < int(
                rule["question_count"]
            ):
                continue
            for _ in range(int(rule["question_count"])):
                section_by_sequence[next_sequence] = {
                    "blueprint_rule_id": rule["blueprint_rule_id"],
                    "section_name": rule.get("section_name"),
                    "section_order": rule.get("section_order"),
                }
                next_sequence += 1
    questions = []
    for row in rows:
        content = question_service.get_question_detail_student(
            connection, int(row["question_id"])
        )
        questions.append(
            {
                "question_id": int(row["question_id"]),
                "priority": 0.0,
                "question_type": content["question_type"],
                "title": content["title"],
                "difficulty": content["difficulty"],
                "topic_id": None,
                "topic_name": None,
                "subtopic_id": None,
                "subtopic_name": None,
                "reason": {
                    "text": "Part of your adaptive practice session.",
                    "topic_accuracy": None,
                    "topic_sample_size": 0,
                    "recent_accuracy": None,
                    "recent_sample_size": 0,
                    "difficulty": content["difficulty"],
                    "recently_seen": False,
                    "recommendation_type": "TOPIC_EXPLORATION",
                },
                "sequence_no": int(row["sequence_no"]),
                "points": float(row["points"]),
                **section_by_sequence.get(int(row["sequence_no"]), {}),
                "content": content,
            }
        )
    return {
        "status": "OK",
        "message": None,
        "session_id": int(attempt["attempt_id"]),
        "attempt_id": int(attempt["attempt_id"]),
        "mock_test_id": int(attempt["mock_test_id"]),
        "status_url": f"/adaptive/session/{attempt['attempt_id']}",
        "title": attempt["title"],
        "mode": "PRACTICE",
        "practice_mode": "ADAPTIVE_PRACTICE",
        "company": attempt["company_name"],
        "company_id": attempt["company_id"],
        "program": attempt["program_name"],
        "pattern_version": attempt["pattern_version"],
        "blueprint_id": attempt["blueprint_id"],
        "duration_seconds": attempt["duration_seconds"],
        "attempt_status": attempt["attempt_status"],
        "started_at": attempt["started_at"].isoformat(),
        "submitted_at": (
            attempt["submitted_at"].isoformat()
            if attempt["submitted_at"] is not None else None
        ),
        "questions": questions,
    }
