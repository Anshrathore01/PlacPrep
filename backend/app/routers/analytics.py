from typing import Literal

from fastapi import APIRouter, Depends, Query

from app.auth.dependencies import get_current_user, require_admin
from app.database import engine
from app.schemas.analytics import (
    AdminAnalyticsOverview,
    AnalyticsSummary,
    AttemptHistoryPage,
    CodingAnalytics,
    CodingProblemPage,
    DifficultyMetric,
    MockAnalyticsPage,
    ProgressResponse,
    QuestionTypeMetric,
    SubtopicMetric,
    TimeAnalytics,
    TopicMetric,
)
from app.services import analytics_service

router = APIRouter(prefix="/analytics", tags=["Analytics"])
admin_router = APIRouter(prefix="/admin/analytics", tags=["Admin Analytics"])


@router.get("/me/summary", response_model=AnalyticsSummary)
def my_summary(current_user: dict = Depends(get_current_user)):
    with engine.connect() as connection:
        return analytics_service.get_summary(connection, current_user["user_id"])


@router.get("/me/attempts", response_model=AttemptHistoryPage)
def my_attempts(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    with engine.connect() as connection:
        return analytics_service.get_attempt_history(
            connection, current_user["user_id"], page, page_size
        )


@router.get("/me/topics", response_model=list[TopicMetric])
def my_topics(current_user: dict = Depends(get_current_user)):
    with engine.connect() as connection:
        return analytics_service.get_topics(connection, current_user["user_id"])


@router.get("/me/subtopics", response_model=list[SubtopicMetric])
def my_subtopics(current_user: dict = Depends(get_current_user)):
    with engine.connect() as connection:
        return analytics_service.get_subtopics(connection, current_user["user_id"])


@router.get("/me/difficulty", response_model=list[DifficultyMetric])
def my_difficulty(current_user: dict = Depends(get_current_user)):
    with engine.connect() as connection:
        return analytics_service.get_difficulty(connection, current_user["user_id"])


@router.get("/me/question-types", response_model=list[QuestionTypeMetric])
def my_question_types(current_user: dict = Depends(get_current_user)):
    with engine.connect() as connection:
        return analytics_service.get_question_types(
            connection, current_user["user_id"]
        )


@router.get("/me/coding", response_model=CodingAnalytics)
def my_coding(current_user: dict = Depends(get_current_user)):
    with engine.connect() as connection:
        return analytics_service.get_coding(connection, current_user["user_id"])


@router.get("/me/coding/problems", response_model=CodingProblemPage)
def my_coding_problems(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    with engine.connect() as connection:
        return analytics_service.get_coding_problems(
            connection, current_user["user_id"], page, page_size
        )


@router.get("/me/mocks", response_model=MockAnalyticsPage)
def my_mocks(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    with engine.connect() as connection:
        return analytics_service.get_mocks(
            connection, current_user["user_id"], page, page_size
        )


@router.get("/me/progress", response_model=ProgressResponse)
def my_progress(
    granularity: Literal["day", "week"] = Query(default="week"),
    current_user: dict = Depends(get_current_user),
):
    with engine.connect() as connection:
        return analytics_service.get_progress(
            connection, current_user["user_id"], granularity
        )


@router.get("/me/time", response_model=TimeAnalytics)
def my_time(current_user: dict = Depends(get_current_user)):
    with engine.connect() as connection:
        return analytics_service.get_time(connection, current_user["user_id"])


@admin_router.get("/overview", response_model=AdminAnalyticsOverview)
def analytics_overview(
    _: dict = Depends(require_admin),
):
    with engine.connect() as connection:
        return analytics_service.get_admin_overview(connection)
