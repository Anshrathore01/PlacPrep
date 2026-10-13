import logging
from datetime import datetime
from decimal import Decimal

from sqlalchemy import text

from app.database import engine
from app.judge.config import RUNNING_TIMEOUT_SECONDS
from app.judge.docker_sandbox import (
    JudgeConfigurationError,
    JudgeUnavailable,
    cleanup_submission_container,
    execute_submission,
)
from app.services.coding_service import calculate_submission_score

logger = logging.getLogger(__name__)

FINAL_STATUSES = {
    "PASSED", "FAILED", "COMPILE_ERROR", "RUNTIME_ERROR", "TIME_LIMIT"
}


def recover_stale_submissions() -> int:
    with engine.begin() as connection:
        stale_ids = [
            row["submission_id"]
            for row in connection.execute(
                text("""
                    SELECT submission_id
                    FROM coding_submissions
                    WHERE status = 'RUNNING'
                      AND started_at < DATE_SUB(NOW(), INTERVAL :timeout SECOND)
                    FOR UPDATE SKIP LOCKED
                """),
                {"timeout": RUNNING_TIMEOUT_SECONDS},
            ).mappings().all()
        ]
        if not stale_ids:
            return 0
        recovered = 0
        for submission_id in stale_ids:
            result = connection.execute(
                text("""
                UPDATE coding_submissions
                SET status = 'RUNTIME_ERROR',
                    completed_at = NOW(),
                    safe_error_message = 'The judge worker did not complete this submission. Please resubmit.'
                WHERE status = 'RUNNING'
                  AND submission_id = :submission_id
                  AND started_at < DATE_SUB(NOW(), INTERVAL :timeout SECOND)
                """),
                {
                    "submission_id": submission_id,
                    "timeout": RUNNING_TIMEOUT_SECONDS,
                },
            )
            recovered += result.rowcount
    for submission_id in stale_ids:
        cleanup_submission_container(submission_id)
    return recovered


def claim_submission() -> dict | None:
    with engine.begin() as connection:
        row = connection.execute(
            text("""
                SELECT submission_id, attempt_id, question_id, source_code
                FROM coding_submissions
                WHERE status = 'QUEUED'
                ORDER BY submission_id
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            """)
        ).mappings().first()
        if row is None:
            return None
        submission_id = row["submission_id"]
        result = connection.execute(
            text("""
                UPDATE coding_submissions
                SET status = 'RUNNING', started_at = NOW(), safe_error_message = NULL
                WHERE submission_id = :submission_id
                  AND status = 'QUEUED'
            """),
            {"submission_id": submission_id},
        )
        if result.rowcount != 1:
            return None
        claimed = dict(row)
        logger.info(
            "Coding submission running: submission_id=%s attempt_id=%s question_id=%s",
            submission_id,
            claimed["attempt_id"],
            claimed["question_id"],
        )
        return claimed


def _load_judge_data(submission: dict) -> tuple[list[dict], Decimal]:
    with engine.connect() as connection:
        current = connection.execute(
            text("""
                SELECT cs.status, a.status AS attempt_status, a.started_at,
                       mt.duration_seconds, mtq.points AS question_points,
                       q.status AS question_status
                FROM coding_submissions cs
                JOIN attempts a ON a.attempt_id = cs.attempt_id
                JOIN mock_tests mt ON mt.mock_test_id = a.mock_test_id
                JOIN mock_test_questions mtq
                  ON mtq.mock_test_id = a.mock_test_id
                 AND mtq.question_id = cs.question_id
                JOIN questions q ON q.question_id = cs.question_id
                WHERE cs.submission_id = :submission_id
            """),
            {"submission_id": submission["submission_id"]},
        ).mappings().first()
        if current is None or current["status"] != "RUNNING":
            raise JudgeConfigurationError("Submission is no longer running.")
        if current["attempt_status"] != "IN_PROGRESS":
            raise JudgeConfigurationError("Attempt is no longer active.")
        if current["question_status"] != "PUBLISHED":
            raise JudgeConfigurationError("Coding question is no longer published.")
        if current["duration_seconds"] is not None:
            elapsed = connection.execute(
                text("SELECT TIMESTAMPDIFF(MICROSECOND, :started_at, NOW())"),
                {"started_at": current["started_at"]},
            ).scalar_one()
            if elapsed >= current["duration_seconds"] * 1_000_000:
                raise JudgeConfigurationError("Attempt expired before judge execution.")
        cases = connection.execute(
            text("""
                SELECT test_case_number, input_data, expected_output, points
                FROM coding_test_cases
                WHERE question_id = :question_id
                ORDER BY test_case_number
            """),
            {"question_id": submission["question_id"]},
        ).mappings().all()
    if not cases or any(case["points"] is None or case["points"] <= 0 for case in cases):
        raise JudgeConfigurationError("Coding question has invalid test-case configuration.")
    return [dict(case) for case in cases], Decimal(current["question_points"])


def _terminal_failure(submission_id: int, status: str, message: str) -> None:
    if status not in FINAL_STATUSES:
        status = "RUNTIME_ERROR"
    with engine.begin() as connection:
        connection.execute(
            text("""
                UPDATE coding_submissions
                SET status = :status,
                    tests_passed = 0,
                    score = 0,
                    completed_at = NOW(),
                    safe_error_message = :message
                WHERE submission_id = :submission_id
                  AND status = 'RUNNING'
            """),
            {
                "submission_id": submission_id,
                "status": status,
                "message": message[:2000],
            },
        )


def process_submission(submission: dict) -> None:
    submission_id = submission["submission_id"]
    started = datetime.now()
    try:
        cases, points = _load_judge_data(submission)
        result = execute_submission(
            submission_id,
            submission["source_code"],
            cases,
        )
        tests_passed = max(0, min(int(result["tests_passed"]), len(cases)))
        score = calculate_submission_score(points, cases, tests_passed)
        status = result["status"]
        if status not in FINAL_STATUSES:
            raise JudgeConfigurationError("Judge returned an unsupported result.")
        if status == "PASSED":
            score = points
        elapsed_ms = result.get("execution_time_ms")
        with engine.begin() as connection:
            connection.execute(
                text("""
                    UPDATE coding_submissions
                    SET status = :status,
                        tests_passed = :tests_passed,
                        tests_total = :tests_total,
                        score = :score,
                        execution_time_ms = :execution_time_ms,
                        completed_at = NOW(),
                        safe_error_message = :safe_error_message
                    WHERE submission_id = :submission_id
                      AND status = 'RUNNING'
                """),
                {
                    "submission_id": submission_id,
                    "status": status,
                    "tests_passed": tests_passed,
                    "tests_total": len(cases),
                    "score": score,
                    "execution_time_ms": elapsed_ms,
                    "safe_error_message": result.get("safe_error_message"),
                },
            )
        logger.info(
            "Coding submission completed: submission_id=%s status=%s duration_ms=%s",
            submission_id,
            status,
            int((datetime.now() - started).total_seconds() * 1000),
        )
    except JudgeUnavailable:
        logger.exception("Judge unavailable: submission_id=%s", submission_id)
        _terminal_failure(
            submission_id,
            "RUNTIME_ERROR",
            "The isolated judge is unavailable. Please contact support.",
        )
    except JudgeConfigurationError as error:
        logger.error(
            "Judge configuration/execution rejected: submission_id=%s reason=%s",
            submission_id,
            error,
        )
        _terminal_failure(
            submission_id,
            "RUNTIME_ERROR",
            "The judge could not safely evaluate this submission.",
        )
    except Exception:
        logger.exception("Unexpected judge worker failure: submission_id=%s", submission_id)
        _terminal_failure(
            submission_id,
            "RUNTIME_ERROR",
            "The judge could not complete this submission. Please resubmit.",
        )
