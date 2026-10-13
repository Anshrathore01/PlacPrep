"""Read-only analytics derived from operational MySQL tables.

Only SUBMITTED attempts contribute to final question, score, topic, difficulty,
time, mock, and progress metrics. EXPIRED attempts are counted and visible in
attempt history, but the attempt engine only records their terminal status and
submitted_at (it does not grade or persist a final score); IN_PROGRESS and
ABANDONED attempts are likewise excluded from performance aggregation.

An assigned question is skipped when it has no selected MCQ answer or no
finalized coding submission in that submitted attempt. MCQ accuracy is correct
selected answers divided by selected answers. Coding is attempted when at
least one finalized submission exists and solved when any submission is PASSED.
Coding problem success rate counts each distinct problem once, regardless of
submission count. Final coding score selection uses highest score, then latest
submission ID as the tie-break, matching the Phase 6 attempt scorer.

For topic attribution each question contributes to one normalized
question_subtopics mapping: the lowest-ID primary mapping, or the lowest-ID
mapping when no primary is set. Questions without a mapping are omitted from
topic/subtopic reports. Missing, zero, and negative answer times are excluded
from timing averages because zero is the stored default and cannot be
distinguished from an unrecorded duration. MySQL DATETIME values are returned
in their database-local form; weekly progress starts on Monday.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import text


FINAL_CODING_STATUSES = (
    "PASSED",
    "FAILED",
    "COMPILE_ERROR",
    "RUNTIME_ERROR",
    "TIME_LIMIT",
)


def _percent(numerator: int | float, denominator: int | float) -> float:
    if not denominator:
        return 0.0
    return float(numerator) * 100.0 / float(denominator)


def _score_percentage(score: Any, max_score: Any) -> float | None:
    if score is None or max_score is None or float(max_score) <= 0:
        return None
    return float(score) * 100.0 / float(max_score)


def choose_canonical_subtopics(mappings: list[dict]) -> dict[int, dict]:
    """Choose one mapping per question: lowest primary ID, or lowest ID if none is primary."""
    grouped: dict[int, list[dict]] = defaultdict(list)
    for mapping in mappings:
        grouped[int(mapping["question_id"])].append(mapping)

    chosen = {}
    for question_id, rows in grouped.items():
        primary = [row for row in rows if row.get("is_primary")]
        chosen[question_id] = min(
            primary or rows,
            key=lambda row: int(row["subtopic_id"]),
        )
    return chosen


def _question_rows(connection, user_id: int) -> tuple[list[dict], dict[int, dict]]:
    rows = connection.execute(
        text("""
            WITH final_coding AS (
                SELECT
                    attempt_id,
                    question_id,
                    COUNT(*) AS final_submission_count,
                    MAX(status = 'PASSED') AS solved
                FROM coding_submissions
                WHERE status IN (
                    'PASSED', 'FAILED', 'COMPILE_ERROR', 'RUNTIME_ERROR', 'TIME_LIMIT'
                )
                  AND attempt_id IS NOT NULL
                GROUP BY attempt_id, question_id
            )
            SELECT
                a.attempt_id,
                a.mock_test_id,
                mtq.question_id,
                mtq.points AS assigned_points,
                q.question_type,
                q.difficulty,
                aa.selected_option_key,
                aa.is_correct,
                aa.time_spent_seconds,
                COALESCE(fc.final_submission_count, 0) AS final_submission_count,
                COALESCE(fc.solved, 0) AS coding_solved
            FROM attempts a
            JOIN mock_test_questions mtq ON mtq.mock_test_id = a.mock_test_id
            JOIN questions q ON q.question_id = mtq.question_id
            LEFT JOIN attempt_answers aa
              ON aa.attempt_id = a.attempt_id
             AND aa.question_id = q.question_id
            LEFT JOIN final_coding fc
              ON fc.attempt_id = a.attempt_id
             AND fc.question_id = q.question_id
            WHERE a.user_id = :user_id
              AND a.status = 'SUBMITTED'
        """),
        {"user_id": user_id},
    ).mappings().all()
    question_rows = [dict(row) for row in rows]
    if not question_rows:
        return [], {}

    mappings = connection.execute(
        text("""
            SELECT
                qs.question_id,
                qs.subtopic_id,
                qs.is_primary,
                s.subtopic_name,
                t.topic_id,
                t.topic_name
            FROM question_subtopics qs
            JOIN subtopics s ON s.subtopic_id = qs.subtopic_id
            JOIN topics t ON t.topic_id = s.topic_id
            WHERE EXISTS (
                SELECT 1
                FROM attempts a
                JOIN mock_test_questions mtq ON mtq.mock_test_id = a.mock_test_id
                WHERE a.user_id = :user_id
                  AND a.status = 'SUBMITTED'
                  AND mtq.question_id = qs.question_id
            )
        """),
        {"user_id": user_id},
    ).mappings().all()
    return question_rows, choose_canonical_subtopics([dict(row) for row in mappings])


def _question_attempted(row: dict) -> bool:
    if row["question_type"] == "MCQ":
        return row["selected_option_key"] is not None
    if row["question_type"] == "CODING":
        return int(row["final_submission_count"] or 0) > 0
    return False


def _question_correct(row: dict) -> bool:
    if row["question_type"] == "MCQ":
        return row["is_correct"] in (True, 1)
    if row["question_type"] == "CODING":
        return row["coding_solved"] in (True, 1)
    return False


def _valid_mcq_time(row: dict) -> float | None:
    if row["question_type"] != "MCQ" or row["selected_option_key"] is None:
        return None
    value = row["time_spent_seconds"]
    if value is None or float(value) <= 0:
        return None
    return float(value)


def _dimension_key(row: dict, mappings: dict[int, dict], dimension: str):
    if dimension == "difficulty":
        return row["difficulty"], {"difficulty": row["difficulty"]}
    mapping = mappings.get(int(row["question_id"]))
    if mapping is None:
        return None, None
    if dimension == "topic":
        key = int(mapping["topic_id"])
        detail = {"topic_id": key, "topic_name": mapping["topic_name"]}
        return key, detail
    if dimension == "subtopic":
        key = int(mapping["subtopic_id"])
        detail = {
            "subtopic_id": key,
            "subtopic_name": mapping["subtopic_name"],
            "topic_id": int(mapping["topic_id"]),
            "topic_name": mapping["topic_name"],
        }
        return key, detail
    raise ValueError(f"Unsupported analytics dimension: {dimension}")


def aggregate_question_metrics(
    rows: list[dict],
    mappings: dict[int, dict],
    dimension: str,
) -> list[dict]:
    buckets: dict[Any, dict] = {}
    for row in rows:
        if not _question_attempted(row):
            continue
        key, detail = _dimension_key(row, mappings, dimension)
        if detail is None:
            continue
        bucket = buckets.setdefault(
            key,
            {
                **detail,
                "questions_attempted": 0,
                "questions_correct": 0,
                "times": [],
            },
        )
        bucket["questions_attempted"] += 1
        bucket["questions_correct"] += int(_question_correct(row))
        time_value = _valid_mcq_time(row)
        if time_value is not None:
            bucket["times"].append(time_value)

    results = []
    for bucket in buckets.values():
        times = bucket.pop("times")
        bucket["accuracy"] = _percent(
            bucket["questions_correct"],
            bucket["questions_attempted"],
        )
        bucket["time_sample_size"] = len(times)
        bucket["average_time_seconds"] = (
            sum(times) / len(times) if times else None
        )
        results.append(bucket)
    sort_key = "difficulty" if dimension == "difficulty" else f"{dimension}_name"
    return sorted(
        results,
        key=lambda item: (
            item[sort_key] is None,
            item[sort_key] if item[sort_key] is not None else "",
        ),
    )


def coding_submission_metrics(rows: list[dict]) -> dict:
    submissions = len(rows)
    problems: dict[int, dict] = {}
    finalized = []
    for row in rows:
        question_id = int(row["question_id"])
        problem = problems.setdefault(question_id, {"solved": False})
        problem["solved"] = problem["solved"] or row["status"] == "PASSED"
        if row["status"] in FINAL_CODING_STATUSES:
            finalized.append(row)

    attempted = len(problems)
    solved = sum(int(problem["solved"]) for problem in problems.values())

    def average(field):
        values = [
            float(row[field])
            for row in finalized
            if row.get(field) is not None
        ]
        return sum(values) / len(values) if values else None

    counts = {status: 0 for status in FINAL_CODING_STATUSES}
    for row in rows:
        if row["status"] in counts:
            counts[row["status"]] += 1
    return {
        "total_submissions": submissions,
        "problems_attempted": attempted,
        "problems_solved": solved,
        "success_rate": _percent(solved, attempted),
        "scored_submission_count": sum(
            1 for row in finalized if row.get("score") is not None
        ),
        "average_score": average("score"),
        "average_tests_passed": average("tests_passed"),
        "average_tests_total": average("tests_total"),
        "compile_error_count": counts["COMPILE_ERROR"],
        "runtime_error_count": counts["RUNTIME_ERROR"],
        "time_limit_count": counts["TIME_LIMIT"],
        "wrong_answer_count": counts["FAILED"],
        "average_execution_time_ms": average("execution_time_ms"),
    }


def select_best_coding_submission(submissions: list[dict]) -> dict | None:
    finalized = [
        row for row in submissions if row["status"] in FINAL_CODING_STATUSES
    ]
    if not finalized:
        return None
    return max(
        finalized,
        key=lambda row: (
            float(row["score"] or 0),
            int(row["submission_id"]),
        ),
    )


def _coding_rows(connection, user_id: int) -> list[dict]:
    rows = connection.execute(
        text("""
            SELECT question_id, status, score, tests_passed, tests_total,
                   execution_time_ms
            FROM coding_submissions
            WHERE user_id = :user_id
        """),
        {"user_id": user_id},
    ).mappings().all()
    return [dict(row) for row in rows]


def _score_rows(connection, user_id: int) -> list[dict]:
    rows = connection.execute(
        text("""
            SELECT attempt_id, score, max_score
            FROM attempts
            WHERE user_id = :user_id
              AND status = 'SUBMITTED'
        """),
        {"user_id": user_id},
    ).mappings().all()
    return [dict(row) for row in rows]


def get_summary(connection, user_id: int) -> dict:
    status_rows = connection.execute(
        text("""
            SELECT status, COUNT(*) AS attempt_count
            FROM attempts
            WHERE user_id = :user_id
            GROUP BY status
        """),
        {"user_id": user_id},
    ).mappings().all()
    status_counts = {row["status"]: int(row["attempt_count"]) for row in status_rows}

    question_rows, mappings = _question_rows(connection, user_id)
    assigned = len(question_rows)
    attempted = sum(int(_question_attempted(row)) for row in question_rows)
    correct = sum(
        int(_question_correct(row))
        for row in question_rows
        if _question_attempted(row)
    )
    skipped = assigned - attempted
    mcq_rows = [
        row for row in question_rows
        if row["question_type"] == "MCQ"
        and row["selected_option_key"] is not None
    ]
    mcq_correct = sum(int(_question_correct(row)) for row in mcq_rows)
    times = [
        value
        for row in question_rows
        if (value := _valid_mcq_time(row)) is not None
    ]
    score_values = [
        value
        for row in _score_rows(connection, user_id)
        if (value := _score_percentage(row["score"], row["max_score"])) is not None
    ]
    coding = coding_submission_metrics(_coding_rows(connection, user_id))
    topics = aggregate_question_metrics(question_rows, mappings, "topic")

    return {
        "total_attempts": sum(status_counts.values()),
        "completed_attempts": status_counts.get("SUBMITTED", 0),
        "expired_attempts": status_counts.get("EXPIRED", 0),
        "abandoned_attempts": status_counts.get("ABANDONED", 0),
        "questions_assigned": assigned,
        "questions_attempted": attempted,
        "questions_correct": correct,
        "questions_skipped": skipped,
        "mcq_questions_attempted": len(mcq_rows),
        "mcq_questions_correct": mcq_correct,
        "average_accuracy": _percent(mcq_correct, len(mcq_rows)),
        "average_score_percentage": (
            sum(score_values) / len(score_values) if score_values else 0.0
        ),
        "highest_score_percentage": max(score_values) if score_values else None,
        "lowest_score_percentage": min(score_values) if score_values else None,
        "score_sample_size": len(score_values),
        "average_time_per_question": sum(times) / len(times) if times else None,
        "time_sample_size": len(times),
        "coding_submissions": coding["total_submissions"],
        "coding_problems_attempted": coding["problems_attempted"],
        "coding_problems_solved": coding["problems_solved"],
        "coding_success_rate": coding["success_rate"],
        "topics": topics,
    }


def get_attempt_history(
    connection,
    user_id: int,
    page: int,
    page_size: int,
) -> dict:
    total = connection.execute(
        text("SELECT COUNT(*) FROM attempts WHERE user_id = :user_id"),
        {"user_id": user_id},
    ).scalar_one()
    offset = (page - 1) * page_size
    rows = connection.execute(
        text("""
            SELECT
                a.attempt_id,
                a.mock_test_id,
                mt.title AS mock_test_title,
                mt.blueprint_id,
                c.company_name,
                a.status,
                a.started_at,
                a.submitted_at,
                a.score,
                a.max_score,
                a.time_spent_seconds,
                CASE
                    WHEN mcq.attempted > 0
                    THEN mcq.correct * 100.0 / mcq.attempted
                    ELSE NULL
                END AS mcq_accuracy
            FROM attempts a
            JOIN mock_tests mt ON mt.mock_test_id = a.mock_test_id
            LEFT JOIN test_blueprints tb ON tb.blueprint_id = mt.blueprint_id
            LEFT JOIN companies c ON c.company_id = tb.company_id
            LEFT JOIN (
                SELECT
                    aa.attempt_id,
                    SUM(CASE
                        WHEN q.question_type = 'MCQ'
                         AND aa.selected_option_key IS NOT NULL THEN 1 ELSE 0
                    END) AS attempted,
                    SUM(CASE
                        WHEN q.question_type = 'MCQ'
                         AND aa.selected_option_key IS NOT NULL
                         AND aa.is_correct = TRUE THEN 1 ELSE 0
                    END) AS correct
                FROM attempt_answers aa
                JOIN questions q ON q.question_id = aa.question_id
                GROUP BY aa.attempt_id
            ) mcq ON mcq.attempt_id = a.attempt_id
            WHERE a.user_id = :user_id
            ORDER BY a.started_at DESC, a.attempt_id DESC
            LIMIT :page_size OFFSET :offset
        """),
        {"user_id": user_id, "page_size": page_size, "offset": offset},
    ).mappings().all()
    items = []
    for row in rows:
        completed = row["status"] == "SUBMITTED"
        score = row["score"] if completed else None
        max_score = row["max_score"] if completed else None
        items.append(
            {
                "attempt_id": int(row["attempt_id"]),
                "mock_test_id": int(row["mock_test_id"]),
                "mock_test_title": row["mock_test_title"],
                "blueprint_id": row["blueprint_id"],
                "company_name": row["company_name"],
                "status": row["status"],
                "started_at": row["started_at"],
                "submitted_at": row["submitted_at"],
                "score": float(score) if score is not None else None,
                "max_score": float(max_score) if max_score is not None else None,
                "score_percentage": _score_percentage(score, max_score),
                "accuracy": (
                    float(row["mcq_accuracy"])
                    if completed and row["mcq_accuracy"] is not None
                    else None
                ),
                "time_spent_seconds": (
                    int(row["time_spent_seconds"])
                    if completed and row["time_spent_seconds"] is not None
                    else None
                ),
            }
        )
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": int(total),
    }


def get_topics(connection, user_id: int) -> list[dict]:
    rows, mappings = _question_rows(connection, user_id)
    return aggregate_question_metrics(rows, mappings, "topic")


def get_subtopics(connection, user_id: int) -> list[dict]:
    rows, mappings = _question_rows(connection, user_id)
    return aggregate_question_metrics(rows, mappings, "subtopic")


def get_difficulty(connection, user_id: int) -> list[dict]:
    rows, mappings = _question_rows(connection, user_id)
    return aggregate_question_metrics(rows, mappings, "difficulty")


def get_question_types(connection, user_id: int) -> list[dict]:
    rows, _ = _question_rows(connection, user_id)
    mcq_rows = [
        row for row in rows
        if row["question_type"] == "MCQ"
        and row["selected_option_key"] is not None
    ]
    mcq_correct = sum(int(_question_correct(row)) for row in mcq_rows)
    coding = coding_submission_metrics(_coding_rows(connection, user_id))
    return [
        {
            "question_type": "MCQ",
            "questions_attempted": len(mcq_rows),
            "questions_correct": mcq_correct,
            "accuracy": _percent(mcq_correct, len(mcq_rows)),
        },
        {
            "question_type": "CODING",
            "questions_attempted": coding["problems_attempted"],
            "questions_correct": coding["problems_solved"],
            "accuracy": coding["success_rate"],
            "problems_attempted": coding["problems_attempted"],
            "problems_solved": coding["problems_solved"],
            "success_rate": coding["success_rate"],
            "total_submissions": coding["total_submissions"],
        },
    ]


def get_coding(connection, user_id: int) -> dict:
    return coding_submission_metrics(_coding_rows(connection, user_id))


def get_coding_problems(
    connection,
    user_id: int,
    page: int,
    page_size: int,
) -> dict:
    total = connection.execute(
        text("""
            SELECT COUNT(DISTINCT question_id)
            FROM coding_submissions
            WHERE user_id = :user_id
        """),
        {"user_id": user_id},
    ).scalar_one()
    offset = (page - 1) * page_size
    rows = connection.execute(
        text("""
            WITH user_submissions AS (
                SELECT
                    cs.submission_id,
                    cs.question_id,
                    cs.status,
                    cs.score,
                    cs.tests_passed,
                    cs.tests_total,
                    cs.submitted_at,
                    q.title
                FROM coding_submissions cs
                JOIN questions q ON q.question_id = cs.question_id
                WHERE cs.user_id = :user_id
            ),
            ranked_final AS (
                SELECT *,
                    ROW_NUMBER() OVER (
                        PARTITION BY question_id
                        ORDER BY COALESCE(score, 0) DESC, submission_id DESC
                    ) AS result_rank
                FROM user_submissions
                WHERE status IN (
                    'PASSED', 'FAILED', 'COMPILE_ERROR', 'RUNTIME_ERROR', 'TIME_LIMIT'
                )
            ),
            ranked_latest AS (
                SELECT *,
                    ROW_NUMBER() OVER (
                        PARTITION BY question_id
                        ORDER BY submitted_at DESC, submission_id DESC
                    ) AS latest_rank
                FROM user_submissions
            ),
            problem_totals AS (
                SELECT
                    question_id,
                    MAX(title) AS title,
                    COUNT(*) AS submission_count,
                    MAX(status = 'PASSED') AS solved,
                    MAX(submitted_at) AS latest_submission_at,
                    MIN(CASE WHEN status = 'PASSED' THEN submitted_at END)
                        AS successful_submission_at
                FROM user_submissions
                GROUP BY question_id
            )
            SELECT
                pt.question_id,
                pt.title,
                pt.submission_count,
                pt.solved,
                rf.score AS best_score,
                rf.tests_passed,
                rf.tests_total,
                COALESCE(rf.status, rl.status) AS best_final_status,
                pt.latest_submission_at,
                pt.successful_submission_at
            FROM problem_totals pt
            LEFT JOIN ranked_final rf
              ON rf.question_id = pt.question_id
             AND rf.result_rank = 1
            LEFT JOIN ranked_latest rl
              ON rl.question_id = pt.question_id
             AND rl.latest_rank = 1
            ORDER BY pt.latest_submission_at DESC, pt.question_id
            LIMIT :page_size OFFSET :offset
        """),
        {"user_id": user_id, "page_size": page_size, "offset": offset},
    ).mappings().all()
    items = []
    for row in rows:
        items.append(
            {
                "question_id": int(row["question_id"]),
                "title": row["title"],
                "submission_count": int(row["submission_count"]),
                "solved": bool(row["solved"]),
                "best_score": float(row["best_score"])
                if row["best_score"] is not None else None,
                "tests_passed": row["tests_passed"],
                "tests_total": row["tests_total"],
                "best_final_status": row["best_final_status"],
                "latest_submission_at": row["latest_submission_at"],
                "successful_submission_at": row["successful_submission_at"],
            }
        )
    return {"items": items, "page": page, "page_size": page_size, "total": int(total)}


def get_mocks(
    connection,
    user_id: int,
    page: int,
    page_size: int,
) -> dict:
    rows = connection.execute(
        text("""
            SELECT
                a.mock_test_id,
                mt.title,
                a.attempt_id,
                a.score,
                a.max_score,
                a.submitted_at,
                CASE
                    WHEN mcq.attempted > 0
                    THEN mcq.correct * 100.0 / mcq.attempted
                    ELSE NULL
                END AS mcq_accuracy
            FROM attempts a
            JOIN mock_tests mt ON mt.mock_test_id = a.mock_test_id
            LEFT JOIN (
                SELECT
                    aa.attempt_id,
                    SUM(CASE
                        WHEN q.question_type = 'MCQ'
                         AND aa.selected_option_key IS NOT NULL THEN 1 ELSE 0
                    END) AS attempted,
                    SUM(CASE
                        WHEN q.question_type = 'MCQ'
                         AND aa.selected_option_key IS NOT NULL
                         AND aa.is_correct = TRUE THEN 1 ELSE 0
                    END) AS correct
                FROM attempt_answers aa
                JOIN questions q ON q.question_id = aa.question_id
                GROUP BY aa.attempt_id
            ) mcq ON mcq.attempt_id = a.attempt_id
            WHERE a.user_id = :user_id
              AND a.status = 'SUBMITTED'
            ORDER BY a.submitted_at DESC, a.attempt_id DESC
        """),
        {"user_id": user_id},
    ).mappings().all()
    grouped: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[int(row["mock_test_id"])].append(dict(row))

    items = []
    for mock_test_id, attempts in grouped.items():
        scores = [
            float(row["score"])
            for row in attempts
            if row["score"] is not None
        ]
        percentages = [
            value for row in attempts
            if (value := _score_percentage(row["score"], row["max_score"])) is not None
        ]
        latest = attempts[0]
        items.append(
            {
                "mock_test_id": mock_test_id,
                "title": latest["title"],
                "attempt_count": len(attempts),
                "latest_score": float(latest["score"])
                if latest["score"] is not None else None,
                "latest_score_percentage": _score_percentage(
                    latest["score"], latest["max_score"]
                ),
                "latest_accuracy": float(latest["mcq_accuracy"])
                if latest["mcq_accuracy"] is not None else None,
                "best_score": max(scores) if scores else None,
                "best_score_percentage": max(percentages) if percentages else None,
                "average_score": sum(scores) / len(scores) if scores else None,
                "average_score_percentage": (
                    sum(percentages) / len(percentages) if percentages else None
                ),
                "latest_submitted_at": latest["submitted_at"],
            }
        )
    items.sort(
        key=lambda item: (
            item["latest_submitted_at"] is not None,
            item["latest_submitted_at"] or datetime.min,
            item["mock_test_id"],
        ),
        reverse=True,
    )
    total = len(items)
    start = (page - 1) * page_size
    return {
        "items": items[start:start + page_size],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


def _period_for(value: datetime, granularity: str) -> date:
    current = value.date()
    if granularity == "week":
        return current - timedelta(days=current.weekday())
    return current


def get_progress(connection, user_id: int, granularity: str) -> dict:
    attempt_rows = connection.execute(
        text("""
            SELECT attempt_id, submitted_at, score, max_score
            FROM attempts
            WHERE user_id = :user_id
              AND status = 'SUBMITTED'
            ORDER BY submitted_at, attempt_id
        """),
        {"user_id": user_id},
    ).mappings().all()
    question_rows, _ = _question_rows(connection, user_id)
    by_attempt: dict[int, list[dict]] = defaultdict(list)
    for row in question_rows:
        by_attempt[int(row["attempt_id"])].append(row)

    periods: dict[date, dict] = {}
    for attempt in attempt_rows:
        submitted_at = attempt["submitted_at"]
        if submitted_at is None:
            continue
        if isinstance(submitted_at, str):
            submitted_at = datetime.fromisoformat(submitted_at)
        period = _period_for(submitted_at, granularity)
        bucket = periods.setdefault(
            period,
            {
                "attempt_count": 0,
                "score_percentages": [],
                "mcq_attempted": 0,
                "mcq_correct": 0,
                "questions_attempted": 0,
                "questions_correct": 0,
            },
        )
        bucket["attempt_count"] += 1
        score_percentage = _score_percentage(attempt["score"], attempt["max_score"])
        if score_percentage is not None:
            bucket["score_percentages"].append(score_percentage)
        for row in by_attempt.get(int(attempt["attempt_id"]), []):
            if _question_attempted(row):
                bucket["questions_attempted"] += 1
                bucket["questions_correct"] += int(_question_correct(row))
            if (
                row["question_type"] == "MCQ"
                and row["selected_option_key"] is not None
            ):
                bucket["mcq_attempted"] += 1
                bucket["mcq_correct"] += int(_question_correct(row))

    items = []
    for period, bucket in sorted(periods.items()):
        percentages = bucket["score_percentages"]
        items.append(
            {
                "period": period.isoformat(),
                "attempt_count": bucket["attempt_count"],
                "average_score_percentage": (
                    sum(percentages) / len(percentages) if percentages else None
                ),
                "average_accuracy": _percent(
                    bucket["mcq_correct"], bucket["mcq_attempted"]
                ),
                "mcq_questions_attempted": bucket["mcq_attempted"],
                "mcq_questions_correct": bucket["mcq_correct"],
                "questions_attempted": bucket["questions_attempted"],
                "questions_correct": bucket["questions_correct"],
            }
        )
    return {"granularity": granularity, "items": items}


def get_time(connection, user_id: int) -> dict:
    rows, mappings = _question_rows(connection, user_id)
    answered = [
        row for row in rows
        if row["question_type"] == "MCQ"
        and row["selected_option_key"] is not None
    ]
    timed = [
        (row, value)
        for row in answered
        if (value := _valid_mcq_time(row)) is not None
    ]
    correct_times = [value for row, value in timed if _question_correct(row)]
    incorrect_times = [value for row, value in timed if not _question_correct(row)]
    by_topic = aggregate_question_metrics(rows, mappings, "topic")
    return {
        "average_time_per_question": (
            sum(value for _, value in timed) / len(timed) if timed else None
        ),
        "average_time_correct": (
            sum(correct_times) / len(correct_times) if correct_times else None
        ),
        "average_time_incorrect": (
            sum(incorrect_times) / len(incorrect_times) if incorrect_times else None
        ),
        "timed_question_count": len(timed),
        "timed_correct_count": len(correct_times),
        "timed_incorrect_count": len(incorrect_times),
        "by_topic": [
            {
                "topic_id": item["topic_id"],
                "topic_name": item["topic_name"],
                "questions_attempted": item["questions_attempted"],
                "questions_correct": item["questions_correct"],
                "accuracy": item["accuracy"],
                "average_time_seconds": item["average_time_seconds"],
                "time_sample_size": item["time_sample_size"],
            }
            for item in by_topic
        ],
    }


def get_admin_overview(connection) -> dict:
    students = connection.execute(
        text("""
            SELECT
                COUNT(*) AS total_students,
                SUM(is_active = TRUE) AS active_students
            FROM users
            WHERE role = 'STUDENT'
        """)
    ).mappings().one()
    attempts = connection.execute(
        text("SELECT COUNT(*) FROM attempts")
    ).scalar_one()
    submissions = connection.execute(
        text("SELECT COUNT(*) FROM coding_submissions")
    ).scalar_one()
    questions_attempted = connection.execute(
        text("""
            SELECT COUNT(*)
            FROM (
                SELECT DISTINCT aa.attempt_id, aa.question_id
                FROM attempt_answers aa
                JOIN attempts a ON a.attempt_id = aa.attempt_id
                JOIN questions q ON q.question_id = aa.question_id
                WHERE a.status = 'SUBMITTED'
                  AND q.question_type = 'MCQ'
                  AND aa.selected_option_key IS NOT NULL
                UNION
                SELECT DISTINCT cs.attempt_id, cs.question_id
                FROM coding_submissions cs
                JOIN attempts a ON a.attempt_id = cs.attempt_id
                WHERE a.status = 'SUBMITTED'
                  AND cs.status IN (
                      'PASSED', 'FAILED', 'COMPILE_ERROR', 'RUNTIME_ERROR', 'TIME_LIMIT'
                  )
            ) attempted_questions
        """)
    ).scalar_one()
    return {
        "total_students": int(students["total_students"] or 0),
        "active_students": int(students["active_students"] or 0),
        "total_attempts": int(attempts),
        "total_submissions": int(submissions),
        "total_questions_attempted": int(questions_attempted),
    }
