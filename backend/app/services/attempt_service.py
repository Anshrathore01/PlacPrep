"""
Attempt Service — Phase 3
=========================

Centralises all attempt lifecycle logic:

  - state machine enforcement (IN_PROGRESS → SUBMITTED / EXPIRED / ABANDONED)
  - timeout / expiration detection
  - answer validation (question membership, option validity, MCQ integrity)
  - duplicate-answer prevention (backed by DB UNIQUE KEY uq_attempt_question)
  - scoring (server-side, transactional)
  - double-submit race-condition protection (SELECT … FOR UPDATE)
  - ownership boundary (ready for Phase 4 auth replacement)

OWNERSHIP CONTRACT
------------------
Every public function receives `requesting_user_id`.  Currently the value
comes from the request body (dev mode).  In Phase 4, replace with the
authenticated identity extracted from the JWT — no changes needed inside
this service.

SECURITY
--------
Correct option keys, solution pseudocode, and hidden test data are NEVER
returned by functions in this module to caller code that assembles
student-facing responses.
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import text

logger = logging.getLogger(__name__)


class AttemptExpired(Exception):
    pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_attempt_expired(conn, started_at: datetime, duration_seconds: Optional[int]) -> bool:
    """
    Return True when a timed attempt has exceeded its duration.

    Untimed attempts (duration_seconds=None) never expire via this check.
    """
    if duration_seconds is None:
        return False
    elapsed_microseconds = conn.execute(
        text("""
            SELECT TIMESTAMPDIFF(MICROSECOND, :started_at, NOW())
        """),
        {"started_at": started_at},
    ).scalar_one()
    return elapsed_microseconds > duration_seconds * 1_000_000


def _resolve_attempt_expiry(conn, attempt: dict) -> str:
    """
    Given a fresh attempt row (dict), determine the effective status.

    If the DB status is IN_PROGRESS but the timer has expired, write EXPIRED
    to the DB and return 'EXPIRED'.  This keeps the DB and application state
    consistent without a background job.

    Returns the effective status string.
    """
    if attempt["status"] != "IN_PROGRESS":
        return attempt["status"]

    duration = attempt.get("duration_seconds")
    started_at = attempt["started_at"]

    if not _is_attempt_expired(conn, started_at, duration):
        return "IN_PROGRESS"

    # Transition to EXPIRED
    conn.execute(
        text("""
            UPDATE attempts
               SET status = 'EXPIRED',
                   submitted_at = NOW()
             WHERE attempt_id = :attempt_id
               AND status = 'IN_PROGRESS'
        """),
        {"attempt_id": attempt["attempt_id"]},
    )
    logger.info(
        "Attempt %s automatically transitioned to EXPIRED "
        "(started_at=%s, duration=%s s)",
        attempt["attempt_id"],
        started_at,
        duration,
    )
    return "EXPIRED"


# ---------------------------------------------------------------------------
# Ownership
# ---------------------------------------------------------------------------

def check_attempt_ownership(attempt: dict, requesting_user_id: int) -> None:
    """
    Verify the requesting user owns this attempt.

    Phase 3: raises 403 if user_id does not match the attempt's owner.
    Phase 4: replace the `requesting_user_id` source with authenticated identity.
    """
    if attempt["user_id"] != requesting_user_id:
        logger.warning(
            "Ownership violation: user %s tried to access attempt %s (owner: %s)",
            requesting_user_id,
            attempt["attempt_id"],
            attempt["user_id"],
        )
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to access this attempt",
        )


# ---------------------------------------------------------------------------
# Fetch helpers (no answer keys exposed)
# ---------------------------------------------------------------------------

def _fetch_attempt_row(conn, attempt_id: int) -> dict:
    """
    Load an attempt row joined with its mock test duration.

    Returns a dict with keys:
      attempt_id, user_id, mock_test_id, started_at, submitted_at,
      status, score, max_score, accuracy, time_spent_seconds,
      duration_seconds  (from mock_tests)

    Raises 404 if not found.
    """
    row = conn.execute(
        text("""
            SELECT
                a.attempt_id,
                a.user_id,
                a.mock_test_id,
                a.started_at,
                a.submitted_at,
                a.status,
                a.score,
                a.max_score,
                a.accuracy,
                a.time_spent_seconds,
                COALESCE(a.duration_seconds, mt.duration_seconds) AS duration_seconds,
                mt.title  AS mock_title,
                mt.total_questions
            FROM attempts a
            JOIN mock_tests mt ON mt.mock_test_id = a.mock_test_id
            WHERE a.attempt_id = :attempt_id
        """),
        {"attempt_id": attempt_id},
    ).mappings().first()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"Attempt {attempt_id} not found",
        )

    return dict(row)


def _compute_expires_at(attempt: dict) -> Optional[str]:
    """Return ISO 8601 expiry timestamp string if timed, else None."""
    duration = attempt.get("duration_seconds")
    if duration is None:
        return None
    started = attempt["started_at"]
    from datetime import timedelta
    expires = started + timedelta(seconds=duration)
    return expires.isoformat()


# ---------------------------------------------------------------------------
# Public API: create attempt
# ---------------------------------------------------------------------------

def create_attempt(conn, requesting_user_id: int, mock_test_id: int, duration_seconds: Optional[int] = None) -> dict:
    """
    Start a new attempt for requesting_user_id on mock_test_id.

    Validates:
      - user exists and is active
      - mock_test is PUBLISHED
      - question count matches total_questions

    Returns the attempt dict (no answer keys).
    """
    if duration_seconds is not None and (not isinstance(duration_seconds, int) or isinstance(duration_seconds, bool) or not 60 <= duration_seconds <= 28800):
        raise HTTPException(status_code=422, detail="Duration must be between 1 and 480 minutes")
    # -- User check
    user = conn.execute(
        text("""
            SELECT user_id, is_active
            FROM users
            WHERE user_id = :user_id
        """),
        {"user_id": requesting_user_id},
    ).mappings().first()

    if user is None:
        raise HTTPException(
            status_code=404,
            detail=f"User {requesting_user_id} not found",
        )
    if not user["is_active"]:
        raise HTTPException(status_code=403, detail="User is inactive")

    # -- Mock test check
    mock_test = conn.execute(
        text("""
            SELECT
                mock_test_id,
                title,
                duration_seconds,
                total_questions,
                status
            FROM mock_tests
            WHERE mock_test_id = :mock_test_id
        """),
        {"mock_test_id": mock_test_id},
    ).mappings().first()

    if mock_test is None:
        raise HTTPException(
            status_code=404,
            detail=f"Mock test {mock_test_id} not found",
        )
    if mock_test["status"] != "PUBLISHED":
        raise HTTPException(
            status_code=400,
            detail="Mock test is not published",
        )

    # Snapshot the established default as well as explicit user selections so
    # later edits to shared mock settings cannot change a live attempt.
    effective_duration_seconds = (
        duration_seconds
        if duration_seconds is not None
        else mock_test["duration_seconds"]
    )

    # -- Question count sanity
    question_count = conn.execute(
        text("""
            SELECT COUNT(*)
            FROM mock_test_questions
            WHERE mock_test_id = :mock_test_id
        """),
        {"mock_test_id": mock_test_id},
    ).scalar_one()

    if question_count != mock_test["total_questions"]:
        raise HTTPException(
            status_code=500,
            detail="Mock test question count is inconsistent",
        )

    # -- Max score from actual points
    max_score = conn.execute(
        text("""
            SELECT COALESCE(SUM(points), 0)
            FROM mock_test_questions
            WHERE mock_test_id = :mock_test_id
        """),
        {"mock_test_id": mock_test_id},
    ).scalar_one()

    # -- Insert attempt
    result = conn.execute(
        text("""
            INSERT INTO attempts (
                user_id,
                mock_test_id,
                started_at,
                status,
                score,
                max_score,
                accuracy,
                time_spent_seconds
                , duration_seconds
            )
            VALUES (
                :user_id,
                :mock_test_id,
                NOW(),
                'IN_PROGRESS',
                0,
                :max_score,
                NULL,
                0,
                :duration_seconds
            )
        """),
        {
            "user_id": requesting_user_id,
            "mock_test_id": mock_test_id,
            "max_score": max_score,
            "duration_seconds": effective_duration_seconds,
        },
    )
    attempt_id = result.lastrowid

    logger.info(
        "Attempt %s created: user=%s mock_test=%s max_score=%s",
        attempt_id,
        requesting_user_id,
        mock_test_id,
        max_score,
    )

    # Re-fetch with duration join
    attempt = _fetch_attempt_row(conn, attempt_id)
    return attempt


# ---------------------------------------------------------------------------
# Public API: get attempt (student-facing, no answer keys)
# ---------------------------------------------------------------------------

def get_attempt_detail(conn, attempt_id: int) -> dict:
    """
    Return attempt state + questions (no correct_option_key in response).

    Also resolves expiration lazily if the timer has run out.
    """
    attempt = _fetch_attempt_row(conn, attempt_id)
    effective_status = _resolve_attempt_expiry(conn, attempt)
    attempt["status"] = effective_status
    attempt["expires_at"] = _compute_expires_at(attempt)
    return attempt


# ---------------------------------------------------------------------------
# Public API: save / update answer
# ---------------------------------------------------------------------------

def save_answer(
    conn,
    attempt_id: int,
    requesting_user_id: int,
    question_id: int,
    selected_option_key: Optional[str],
    answer_text: Optional[str],
    time_spent_seconds: int,
) -> dict:
    """
    Persist an MCQ answer for an IN_PROGRESS attempt.

    Rules enforced:
      1. Attempt must exist
      2. Requesting user must own the attempt
      3. Attempt must be IN_PROGRESS (not expired, submitted, or abandoned)
      4. Question must belong to this attempt's mock test
      5. For MCQ: selected_option_key required, option must exist for the question
      6. Duplicate row → UPDATE via ON DUPLICATE KEY (one active answer per question)

    Correctness is NOT evaluated here — only at submission time.
    """
    # -- Load attempt with lock to serialise concurrent saves
    attempt = conn.execute(
        text("""
            SELECT
                a.attempt_id,
                a.user_id,
                a.mock_test_id,
                a.started_at,
                a.status,
                COALESCE(a.duration_seconds, mt.duration_seconds) AS duration_seconds
            FROM attempts a
            JOIN mock_tests mt ON mt.mock_test_id = a.mock_test_id
            WHERE a.attempt_id = :attempt_id
            FOR UPDATE
        """),
        {"attempt_id": attempt_id},
    ).mappings().first()

    if attempt is None:
        raise HTTPException(
            status_code=404,
            detail=f"Attempt {attempt_id} not found",
        )

    attempt = dict(attempt)

    # -- Ownership check
    check_attempt_ownership(attempt, requesting_user_id)

    # -- Resolve expiry (may update DB status)
    effective_status = _resolve_attempt_expiry(conn, attempt)

    if effective_status != "IN_PROGRESS":
        status_messages = {
            "SUBMITTED": "This attempt has already been submitted",
            "EXPIRED":   "This attempt has expired — time limit exceeded",
            "ABANDONED": "This attempt has been abandoned",
        }
        if effective_status == "EXPIRED":
            raise AttemptExpired(status_messages["EXPIRED"])
        raise HTTPException(
            status_code=400,
            detail=status_messages.get(
                effective_status,
                "This attempt is no longer accepting answers",
            ),
        )

    # -- Question membership check
    question = conn.execute(
        text("""
            SELECT
                q.question_id,
                q.question_type
            FROM questions q
            JOIN mock_test_questions mtq ON mtq.question_id = q.question_id
            WHERE mtq.mock_test_id = :mock_test_id
              AND q.question_id    = :question_id
        """),
        {
            "mock_test_id": attempt["mock_test_id"],
            "question_id":  question_id,
        },
    ).mappings().first()

    if question is None:
        raise HTTPException(
            status_code=400,
            detail="Question does not belong to this attempt",
        )

    # -- MCQ-specific validation
    if question["question_type"] == "MCQ":
        if not selected_option_key:
            raise HTTPException(
                status_code=400,
                detail="selected_option_key is required for an MCQ",
            )

        mcq = conn.execute(
            text("""
                SELECT
                    mq.correct_option_key,
                    mq.is_multiple_correct,
                    (
                        SELECT COUNT(*)
                        FROM mcq_options mo
                        WHERE mo.question_id = mq.question_id
                    ) AS option_count
                FROM mcq_questions mq
                WHERE mq.question_id = :question_id
            """),
            {"question_id": question_id},
        ).mappings().first()

        if mcq is None:
            raise HTTPException(
                status_code=400,
                detail="MCQ content is missing for this question",
            )
        if mcq["is_multiple_correct"]:
            raise HTTPException(
                status_code=400,
                detail="Multiple-correct MCQs are not supported by the current scorer",
            )

        if mcq["option_count"] > 0:
            if not selected_option_key:
                raise HTTPException(
                    status_code=400,
                    detail="selected_option_key is required for an MCQ with options",
                )
            # Validate the student's chosen option
            option_exists = conn.execute(
                text("""
                    SELECT 1
                    FROM mcq_options
                    WHERE question_id = :question_id
                      AND option_key  = :option_key
                """),
                {
                    "question_id": question_id,
                    "option_key":  selected_option_key,
                },
            ).first()

            if option_exists is None:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid option for this MCQ",
                )

    # -- Upsert answer (DB UNIQUE KEY uq_attempt_question prevents duplicate rows)
    conn.execute(
        text("""
            INSERT INTO attempt_answers (
                attempt_id,
                question_id,
                selected_option_key,
                answer_text,
                is_correct,
                points_awarded,
                time_spent_seconds,
                answered_at
            )
            VALUES (
                :attempt_id,
                :question_id,
                :selected_option_key,
                :answer_text,
                NULL,
                0,
                :time_spent_seconds,
                NOW()
            )
            ON DUPLICATE KEY UPDATE
                selected_option_key = VALUES(selected_option_key),
                answer_text         = VALUES(answer_text),
                time_spent_seconds  = VALUES(time_spent_seconds),
                answered_at         = NOW()
        """),
        {
            "attempt_id":          attempt_id,
            "question_id":         question_id,
            "selected_option_key": selected_option_key,
            "answer_text":         answer_text,
            "time_spent_seconds":  time_spent_seconds,
        },
    )

    logger.info(
        "Answer saved: attempt=%s question=%s option=%s",
        attempt_id,
        question_id,
        selected_option_key,
    )

    return {
        "message":    "Answer saved",
        "attempt_id": attempt_id,
        "question_id": question_id,
    }


# ---------------------------------------------------------------------------
# Public API: submit attempt
# ---------------------------------------------------------------------------

def submit_attempt(conn, attempt_id: int, requesting_user_id: int) -> dict:
    """
    Finalise an attempt.

    Uses SELECT … FOR UPDATE to prevent double-submit races.

    Steps:
      1. Lock the attempt row
      2. Verify ownership
      3. Verify IN_PROGRESS (check expiry)
      4. Grade MCQ answers server-side
      5. Compute score, max_score, accuracy, time_spent
      6. Atomically set status=SUBMITTED
      7. Return final result (no answer keys)
    """
    # -- Lock the attempt row (prevents two concurrent submissions)
    attempt = conn.execute(
        text("""
            SELECT
                a.attempt_id,
                a.user_id,
                a.mock_test_id,
                a.started_at,
                a.status,
                COALESCE(a.duration_seconds, mt.duration_seconds) AS duration_seconds
            FROM attempts a
            JOIN mock_tests mt ON mt.mock_test_id = a.mock_test_id
            WHERE a.attempt_id = :attempt_id
            FOR UPDATE
        """),
        {"attempt_id": attempt_id},
    ).mappings().first()

    if attempt is None:
        raise HTTPException(
            status_code=404,
            detail=f"Attempt {attempt_id} not found",
        )

    attempt = dict(attempt)

    # -- Ownership check
    check_attempt_ownership(attempt, requesting_user_id)

    # -- Resolve expiry
    effective_status = _resolve_attempt_expiry(conn, attempt)

    if effective_status == "SUBMITTED":
        raise HTTPException(
            status_code=400,
            detail="Attempt has already been submitted",
        )
    if effective_status in ("EXPIRED", "ABANDONED"):
        if effective_status == "EXPIRED":
            raise AttemptExpired(
                "This attempt has expired and cannot be submitted normally. "
                "Results have been recorded."
            )
        raise HTTPException(
            status_code=400,
            detail="This attempt has been abandoned",
        )
    if effective_status != "IN_PROGRESS":
        raise HTTPException(
            status_code=400,
            detail="Attempt is not in a submittable state",
        )

    mock_test_id = attempt["mock_test_id"]

    active_coding_submissions = conn.execute(
        text("""
            SELECT COUNT(*)
            FROM coding_submissions
            WHERE attempt_id = :attempt_id
              AND status IN ('QUEUED', 'RUNNING')
        """),
        {"attempt_id": attempt_id},
    ).scalar_one()
    if active_coding_submissions:
        raise HTTPException(
            status_code=409,
            detail="Wait for coding submissions to finish before submitting the attempt.",
        )

    # -- Server-side MCQ grading
    conn.execute(
        text("""
            UPDATE attempt_answers aa
            JOIN mock_test_questions mtq
              ON mtq.mock_test_id = :mock_test_id
             AND mtq.question_id  = aa.question_id
            JOIN mcq_questions mq
              ON mq.question_id = aa.question_id
            SET
                aa.is_correct =
                    CASE
                        WHEN aa.selected_option_key IS NOT NULL
                         AND mq.correct_option_key IS NOT NULL
                         AND aa.selected_option_key = mq.correct_option_key
                        THEN TRUE
                        WHEN aa.answer_text IS NOT NULL
                         AND (
                             (mq.correct_option_key IS NOT NULL AND LOWER(TRIM(aa.answer_text)) = LOWER(TRIM(mq.correct_option_key)))
                             OR (mq.explanation IS NOT NULL AND LOWER(TRIM(aa.answer_text)) = LOWER(TRIM(mq.explanation)))
                         )
                        THEN TRUE
                        ELSE FALSE
                    END,
                aa.points_awarded =
                    CASE
                        WHEN aa.selected_option_key IS NOT NULL
                         AND mq.correct_option_key IS NOT NULL
                         AND aa.selected_option_key = mq.correct_option_key
                        THEN mtq.points
                        WHEN aa.answer_text IS NOT NULL
                         AND (
                             (mq.correct_option_key IS NOT NULL AND LOWER(TRIM(aa.answer_text)) = LOWER(TRIM(mq.correct_option_key)))
                             OR (mq.explanation IS NOT NULL AND LOWER(TRIM(aa.answer_text)) = LOWER(TRIM(mq.explanation)))
                         )
                        THEN mtq.points
                        ELSE 0
                    END
            WHERE aa.attempt_id = :attempt_id
        """),
        {
            "attempt_id":  attempt_id,
            "mock_test_id": mock_test_id,
        },
    )

    # -- Score from actual points awarded
    mcq_score = conn.execute(
        text("""
            SELECT COALESCE(SUM(points_awarded), 0)
            FROM attempt_answers
            WHERE attempt_id = :attempt_id
        """),
        {"attempt_id": attempt_id},
    ).scalar_one()
    coding_score = conn.execute(
        text("""
            SELECT COALESCE(SUM(best.score), 0)
            FROM coding_submissions best
            WHERE best.attempt_id = :attempt_id
              AND best.status IN (
                  'PASSED', 'FAILED', 'COMPILE_ERROR', 'RUNTIME_ERROR', 'TIME_LIMIT'
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM coding_submissions newer
                  WHERE newer.attempt_id = best.attempt_id
                    AND newer.question_id = best.question_id
                    AND newer.status IN (
                        'PASSED', 'FAILED', 'COMPILE_ERROR', 'RUNTIME_ERROR', 'TIME_LIMIT'
                    )
                    AND (
                        newer.score > best.score
                        OR (
                            newer.score = best.score
                            AND newer.submission_id > best.submission_id
                        )
                    )
              )
        """),
        {"attempt_id": attempt_id},
    ).scalar_one()
    score = mcq_score + coding_score

    # -- Stats
    mcq_total = conn.execute(
        text("""
            SELECT COUNT(*)
            FROM mock_test_questions mtq
            JOIN questions q ON q.question_id = mtq.question_id
            WHERE mtq.mock_test_id = :mock_test_id
              AND q.question_type  = 'MCQ'
        """),
        {"mock_test_id": mock_test_id},
    ).scalar_one()

    correct_mcqs = conn.execute(
        text("""
            SELECT COUNT(*)
            FROM attempt_answers
            WHERE attempt_id = :attempt_id
              AND is_correct  = TRUE
        """),
        {"attempt_id": attempt_id},
    ).scalar_one()

    answered_mcqs = conn.execute(
        text("""
            SELECT COUNT(*)
            FROM attempt_answers aa
            JOIN questions q ON q.question_id = aa.question_id
            WHERE aa.attempt_id          = :attempt_id
              AND q.question_type        = 'MCQ'
              AND aa.selected_option_key IS NOT NULL
        """),
        {"attempt_id": attempt_id},
    ).scalar_one()

    coding_total = conn.execute(
        text("""
            SELECT COUNT(*)
            FROM mock_test_questions mtq
            JOIN questions q ON q.question_id = mtq.question_id
            WHERE mtq.mock_test_id = :mock_test_id
              AND q.question_type  = 'CODING'
        """),
        {"mock_test_id": mock_test_id},
    ).scalar_one()

    max_score = conn.execute(
        text("""
            SELECT COALESCE(SUM(mtq.points), 0)
            FROM mock_test_questions mtq
            WHERE mtq.mock_test_id = :mock_test_id
        """),
        {"mock_test_id": mock_test_id},
    ).scalar_one()

    accuracy = (
        float(score) / float(max_score)
        if coding_total and max_score
        else (float(correct_mcqs) / float(mcq_total) if mcq_total else None)
    )

    time_spent = conn.execute(
        text("""
            SELECT TIMESTAMPDIFF(SECOND, started_at, NOW())
            FROM attempts
            WHERE attempt_id = :attempt_id
        """),
        {"attempt_id": attempt_id},
    ).scalar_one()

    # -- Atomic state transition
    conn.execute(
        text("""
            UPDATE attempts
               SET submitted_at      = NOW(),
                   status            = 'SUBMITTED',
                   score             = :score,
                   max_score         = :max_score,
                   accuracy          = :accuracy,
                   time_spent_seconds = :time_spent
             WHERE attempt_id = :attempt_id
               AND status     = 'IN_PROGRESS'
        """),
        {
            "attempt_id": attempt_id,
            "score":      score,
            "max_score":  max_score,
            "accuracy":   accuracy,
            "time_spent": time_spent or 0,
        },
    )

    logger.info(
        "Attempt %s submitted: user=%s score=%s/%s accuracy=%s",
        attempt_id,
        attempt["user_id"],
        score,
        max_score,
        accuracy,
    )

    # Re-fetch final state
    final = conn.execute(
        text("""
            SELECT
                attempt_id,
                user_id,
                mock_test_id,
                started_at,
                submitted_at,
                status,
                score,
                max_score,
                accuracy,
                time_spent_seconds
            FROM attempts
            WHERE attempt_id = :attempt_id
        """),
        {"attempt_id": attempt_id},
    ).mappings().one()

    return {
        "attempt":               dict(final),
        "mcq_total":             mcq_total,
        "mcq_answered":          answered_mcqs,
        "mcq_correct":           correct_mcqs,
        "coding_total":          coding_total,
        "coding_grading_status": (
            "PENDING_CODE_JUDGE" if coding_total else "NOT_APPLICABLE"
        ),
    }
