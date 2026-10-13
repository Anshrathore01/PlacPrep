import logging
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException
from sqlalchemy import text

from app.judge.docker_sandbox import JudgeConfigurationError, validate_judge_input

logger = logging.getLogger(__name__)


def create_submission(
    connection,
    attempt_id: int,
    question_id: int,
    language: str,
    source_code: str,
    user: dict,
) -> int:
    if language != "C++17":
        raise HTTPException(status_code=422, detail="Only C++17 submissions are supported.")
    if not source_code.strip():
        raise HTTPException(status_code=422, detail="Source code must not be empty.")

    attempt = connection.execute(
        text("""
            SELECT a.attempt_id, a.user_id, a.mock_test_id, a.status, a.started_at,
                   mt.duration_seconds
            FROM attempts a
            JOIN mock_tests mt ON mt.mock_test_id = a.mock_test_id
            WHERE a.attempt_id = :attempt_id
            FOR UPDATE
        """),
        {"attempt_id": attempt_id},
    ).mappings().first()
    if attempt is None:
        raise HTTPException(status_code=404, detail="Attempt not found.")
    if attempt["user_id"] != user["user_id"]:
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to submit to this attempt.",
        )
    if attempt["status"] != "IN_PROGRESS":
        raise HTTPException(status_code=409, detail="This attempt is not accepting submissions.")
    if attempt["duration_seconds"] is not None:
        elapsed = connection.execute(
            text("SELECT TIMESTAMPDIFF(MICROSECOND, :started_at, NOW())"),
            {"started_at": attempt["started_at"]},
        ).scalar_one()
        if elapsed >= attempt["duration_seconds"] * 1_000_000:
            raise HTTPException(status_code=409, detail="This attempt has expired.")

    question = connection.execute(
        text("""
            SELECT q.question_type, q.status, cq.question_id AS coding_question_id
            FROM questions q
            LEFT JOIN coding_questions cq ON cq.question_id = q.question_id
            JOIN mock_test_questions mtq
              ON mtq.question_id = q.question_id
             AND mtq.mock_test_id = :mock_test_id
            WHERE q.question_id = :question_id
        """),
        {"question_id": question_id, "mock_test_id": attempt["mock_test_id"]},
    ).mappings().first()
    if question is None:
        raise HTTPException(status_code=404, detail="Question is not part of this attempt.")
    if question["question_type"] != "CODING" or question["coding_question_id"] is None:
        raise HTTPException(status_code=422, detail="The selected question is not a coding question.")
    if question["status"] != "PUBLISHED":
        raise HTTPException(status_code=409, detail="The coding question is not published.")

    cases = connection.execute(
        text("""
            SELECT test_case_number, input_data, expected_output, points
            FROM coding_test_cases
            WHERE question_id = :question_id
            ORDER BY test_case_number
        """),
        {"question_id": question_id},
    ).mappings().all()
    if not cases or any(case["points"] is None or case["points"] <= 0 for case in cases):
        logger.error(
            "Coding judge configuration invalid: question_id=%s test_cases=%s",
            question_id,
            len(cases),
        )
        raise HTTPException(
            status_code=503,
            detail="The coding question is not configured for judging. Please contact support.",
        )
    try:
        validate_judge_input(source_code, [dict(case) for case in cases])
    except JudgeConfigurationError as error:
        logger.error(
            "Coding judge configuration invalid: question_id=%s reason=%s",
            question_id,
            error,
        )
        raise HTTPException(
            status_code=503,
            detail="The coding question is not configured for judging. Please contact support.",
        ) from error

    result = connection.execute(
        text("""
            INSERT INTO coding_submissions (
                attempt_id, user_id, question_id, language, source_code,
                status, tests_passed, tests_total, score
            )
            VALUES (
                :attempt_id, :user_id, :question_id, :language, :source_code,
                'QUEUED', 0, 0, 0
            )
        """),
        {
            "attempt_id": attempt_id,
            "user_id": user["user_id"],
            "question_id": question_id,
            "language": language,
            "source_code": source_code,
        },
    )
    submission_id = int(result.lastrowid)
    logger.info(
        "Coding submission queued: submission_id=%s attempt_id=%s question_id=%s",
        submission_id,
        attempt_id,
        question_id,
    )
    return submission_id


def get_submission(connection, submission_id: int, user: dict) -> dict:
    submission = connection.execute(
        text("""
            SELECT submission_id, user_id, question_id, language, status, tests_passed,
                   tests_total, score, submitted_at, completed_at,
                   safe_error_message
            FROM coding_submissions
            WHERE submission_id = :submission_id
        """),
        {"submission_id": submission_id},
    ).mappings().first()
    if submission is None:
        raise HTTPException(status_code=404, detail="Coding submission not found.")
    if submission["user_id"] != user["user_id"] and user.get("role") != "ADMIN":
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to access this coding submission.",
        )
    result = dict(submission)
    result.pop("user_id")
    return result


def calculate_submission_score(
    question_points: Decimal,
    cases: list[dict],
    tests_passed: int,
) -> Decimal:
    total_weight = sum(Decimal(case["points"]) for case in cases)
    passed_weight = sum(
        Decimal(case["points"]) for case in cases[:tests_passed]
    )
    if total_weight <= 0:
        raise JudgeConfigurationError("Coding test-case points must sum to a positive value.")
    return (
        question_points * passed_weight / total_weight
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
