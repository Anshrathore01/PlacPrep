from typing import Literal

from fastapi import APIRouter, Depends, Query

from app.adaptive.rules import CONFIG
from app.auth.dependencies import get_current_user
from app.database import engine
from app.schemas.adaptive import (
    AdaptiveNextResponse,
    AdaptiveRecommendationsResponse,
    AdaptiveSessionRequest,
    AdaptiveSessionResponse,
    AdaptiveSessionStatusResponse,
)
from app.services import adaptive_service

router = APIRouter(prefix="/adaptive", tags=["Adaptive Practice"])


@router.get("/next", response_model=AdaptiveNextResponse)
def next_question(
    question_type: Literal["MCQ", "CODING"] | None = None,
    track_id: int | None = Query(default=None, ge=1),
    topic_id: int | None = Query(default=None, ge=1),
    subtopic_id: int | None = Query(default=None, ge=1),
    difficulty: Literal["EASY", "MEDIUM", "HARD"] | None = None,
    current_user: dict = Depends(get_current_user),
):
    with engine.connect() as connection:
        return adaptive_service.get_next(
            connection,
            current_user["user_id"],
            question_type,
            topic_id,
            subtopic_id,
            difficulty,
            track_id,
        )


@router.get(
    "/recommendations",
    response_model=AdaptiveRecommendationsResponse,
)
def recommendations(
    limit: int = Query(default=5, ge=1, le=CONFIG.max_recommendations),
    question_type: Literal["MCQ", "CODING"] | None = None,
    track_id: int | None = Query(default=None, ge=1),
    topic_id: int | None = Query(default=None, ge=1),
    subtopic_id: int | None = Query(default=None, ge=1),
    difficulty: Literal["EASY", "MEDIUM", "HARD"] | None = None,
    current_user: dict = Depends(get_current_user),
):
    with engine.connect() as connection:
        return adaptive_service.get_recommendations(
            connection,
            current_user["user_id"],
            limit,
            question_type,
            topic_id,
            subtopic_id,
            difficulty,
            track_id,
        )


@router.post("/session", response_model=AdaptiveSessionResponse)
def create_session(
    request: AdaptiveSessionRequest,
    current_user: dict = Depends(get_current_user),
):
    with engine.begin() as connection:
        return adaptive_service.create_session(
            connection,
            current_user["user_id"],
            request.number_of_questions,
            request.question_type,
            request.topic_id,
            request.subtopic_id,
            request.target_difficulty,
            request.duration_seconds,
            request.track_id,
            request.blueprint_id,
        )


@router.get(
    "/session/{session_id}",
    response_model=AdaptiveSessionStatusResponse,
)
def get_session(
    session_id: int,
    current_user: dict = Depends(get_current_user),
):
    with engine.connect() as connection:
        return adaptive_service.get_session(
            connection,
            current_user["user_id"],
            session_id,
        )
