"""
Attempts Router — Phase 3
=========================

Exposes:
  POST   /attempts
  GET    /attempts/{attempt_id}
  POST   /attempts/{attempt_id}/answers
  POST   /attempts/{attempt_id}/submit

All attempt mutation endpoints delegate to attempt_service for state machine
enforcement, ownership checking, and scoring.

PHASE 4 NOTE
------------
Replace `payload.user_id` lookups with `current_user = Depends(get_current_user)`
from the auth module — no changes needed in attempt_service itself.
"""

import logging
from typing import Callable, Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field, StrictInt
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.database import engine
from app.services import attempt_service, question_service
from app.auth.dependencies import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Attempts"])


def _run_attempt_mutation(operation: Callable[[Connection], dict]) -> dict:
    expired_message: str | None = None
    result: dict | None = None
    with engine.begin() as connection:
        try:
            result = operation(connection)
        except attempt_service.AttemptExpired as error:
            expired_message = str(error)
    if expired_message is not None:
        raise HTTPException(status_code=400, detail=expired_message)
    if result is None:
        raise RuntimeError("Attempt service returned no result.")
    return result


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class StartAttemptRequest(BaseModel):
    mock_test_id: int = Field(ge=1)
    duration_seconds: Optional[StrictInt] = Field(default=None, ge=60, le=28800)


class AnswerRequest(BaseModel):
    question_id: int = Field(ge=1)
    selected_option_key: Optional[str] = Field(
        default=None, min_length=1, max_length=1
    )
    answer_text: Optional[str] = None
    time_spent_seconds: int = Field(default=0, ge=0)


# ---------------------------------------------------------------------------
# POST /attempts — start a new attempt
# ---------------------------------------------------------------------------

@router.post("/attempts", status_code=201)
def start_attempt(payload: StartAttemptRequest, current_user: dict = Depends(get_current_user)):
    """
    Start a new attempt for the given user and mock test.

    Returns attempt metadata + questions (no answer keys).
    """
    with engine.begin() as conn:
        attempt = attempt_service.create_attempt(
            conn,
            requesting_user_id=current_user["user_id"],
            mock_test_id=payload.mock_test_id,
            duration_seconds=payload.duration_seconds,
        )
        attempt_id = attempt["attempt_id"]

        # Build question list from mock test (no answer keys)
        mock_rows = conn.execute(
            text("""
                SELECT sequence_no, points, question_id
                FROM mock_test_questions
                WHERE mock_test_id = :mock_test_id
                ORDER BY sequence_no
            """),
            {"mock_test_id": payload.mock_test_id},
        ).mappings().all()

        questions = []
        for row in mock_rows:
            q = question_service.get_question_detail_student(
                conn, row["question_id"]
            )
            q["sequence_no"] = row["sequence_no"]
            q["points"] = float(row["points"])
            questions.append(q)

    return {
        **{k: v for k, v in attempt.items()
           if k not in ("mock_title", "total_questions", "duration_seconds")},
        "mock_test": {
            "mock_test_id":    attempt["mock_test_id"],
            "title":           attempt["mock_title"],
            "duration_seconds": attempt["duration_seconds"],
            "total_questions": attempt["total_questions"],
            "status":          "PUBLISHED",
        },
        "expires_at": attempt_service._compute_expires_at(attempt),
        "questions":  questions,
    }


# ---------------------------------------------------------------------------
# GET /attempts/{attempt_id} — retrieve attempt (resume support)
# ---------------------------------------------------------------------------

@router.get("/attempts/{attempt_id}")
def get_attempt(attempt_id: int, current_user: dict = Depends(get_current_user)):
    """
    Return current attempt state and student-facing questions.

    - Resolves expiration lazily if the timer has run out.
    - Includes the student's current answers (for resume).
    - Does NOT expose correct_option_key.
    - Returns expires_at so the frontend can display a countdown timer
      (but the backend is authoritative — no frontend timer can override this).
    """
    with engine.begin() as conn:
        attempt = attempt_service.get_attempt_detail(conn, attempt_id)
        if attempt["user_id"] != current_user["user_id"] and current_user["role"] != "ADMIN":
            raise HTTPException(status_code=403, detail="You do not have permission to view this attempt")

        # Load questions + saved answers
        rows = conn.execute(
            text("""
                SELECT
                    mtq.sequence_no,
                    mtq.points,
                    mtq.question_id,
                    aa.selected_option_key,
                    aa.answer_text,
                    aa.time_spent_seconds  AS answer_time_spent,
                    aa.is_correct,
                    aa.points_awarded
                FROM mock_test_questions mtq
                LEFT JOIN attempt_answers aa
                  ON aa.question_id = mtq.question_id
                 AND aa.attempt_id  = :attempt_id
                WHERE mtq.mock_test_id = :mock_test_id
                ORDER BY mtq.sequence_no
            """),
            {
                "attempt_id":   attempt_id,
                "mock_test_id": attempt["mock_test_id"],
            },
        ).mappings().all()

        questions = []
        for row in rows:
            q = question_service.get_question_detail_student(
                conn, row["question_id"]
            )
            q["sequence_no"]          = row["sequence_no"]
            q["points"]               = float(row["points"])
            q["selected_option_key"]  = row["selected_option_key"]
            q["answer_text"]          = row["answer_text"]
            q["time_spent_seconds"]   = row["answer_time_spent"] or 0
            if attempt["status"] in ("SUBMITTED", "EXPIRED"):
                q["is_correct"] = (
                    bool(row["is_correct"])
                    if row["is_correct"] is not None
                    else None
                )
                q["points_awarded"] = (
                    float(row["points_awarded"])
                    if row["points_awarded"] is not None
                    else None
                )
            if attempt["status"] == "SUBMITTED" and q["question_type"] == "MCQ":
                answer_key = conn.execute(
                    text("SELECT correct_option_key FROM mcq_questions WHERE question_id = :question_id"),
                    {"question_id": row["question_id"]},
                ).scalar_one_or_none()
                q["answer_key_available"] = answer_key is not None
                q["correct_option_key"] = answer_key
            questions.append(q)

    # Clean up internal-only keys from the attempt dict before responding
    attempt_out = {
        k: v for k, v in attempt.items()
        if k not in ("mock_title", "total_questions")
    }

    return {
        "attempt":   attempt_out,
        "questions": questions,
    }


# ---------------------------------------------------------------------------
# POST /attempts/{attempt_id}/answers — save / update a single answer
# ---------------------------------------------------------------------------

@router.post("/attempts/{attempt_id}/answers")
def save_answer(attempt_id: int, payload: AnswerRequest, current_user: dict = Depends(get_current_user)):
    """
    Save or update a student answer for one question.

    Behaviour:
      - First save: creates the row.
      - Subsequent saves for the same question: updates the row (resume support).
      - After submission: rejected with 400.
      - After expiration: rejected with 400.
      - Invalid question or option: rejected with 400.

    The database UNIQUE KEY (attempt_id, question_id) guarantees at most one
    active answer row per question per attempt, regardless of concurrent requests.
    """
    return _run_attempt_mutation(
        lambda connection: attempt_service.save_answer(
            connection,
            attempt_id=attempt_id,
            requesting_user_id=current_user["user_id"],
            question_id=payload.question_id,
            selected_option_key=payload.selected_option_key,
            answer_text=payload.answer_text,
            time_spent_seconds=payload.time_spent_seconds,
        )
    )


# ---------------------------------------------------------------------------
# POST /attempts/{attempt_id}/submit — finalise the attempt
# ---------------------------------------------------------------------------

@router.post("/attempts/{attempt_id}/submit")
def submit_attempt(attempt_id: int, current_user: dict = Depends(get_current_user)):
    """
    Submit and finalise the attempt.

    Uses SELECT … FOR UPDATE to prevent double-submit races.
    Grading is performed server-side within the same transaction.
    Attempt fields are top-level for clients, with the nested attempt retained
    for compatibility with existing callers.
    """
    result = _run_attempt_mutation(
        lambda connection: attempt_service.submit_attempt(
            connection,
            attempt_id=attempt_id,
            requesting_user_id=current_user["user_id"],
        )
    )
    attempt = result["attempt"]
    return {
        **attempt,
        **{key: value for key, value in result.items() if key != "attempt"},
        "attempt": attempt,
    }
