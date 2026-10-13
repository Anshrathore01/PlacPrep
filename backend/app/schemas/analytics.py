from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class TopicMetric(BaseModel):
    topic_id: int
    topic_name: str
    questions_attempted: int
    questions_correct: int
    accuracy: float = Field(description="Correct attempted question records / attempted question records, as a percentage; a coding question is correct when a submission is PASSED.")
    average_time_seconds: float | None = None
    time_sample_size: int = 0


class SubtopicMetric(BaseModel):
    subtopic_id: int
    subtopic_name: str
    topic_id: int
    topic_name: str
    questions_attempted: int
    questions_correct: int
    accuracy: float = Field(description="Correct attempted question records / attempted question records, as a percentage; a coding question is correct when a submission is PASSED.")
    average_time_seconds: float | None = None
    time_sample_size: int = 0


class DifficultyMetric(BaseModel):
    difficulty: str | None = Field(description="NULL is reported as null; no synthetic difficulty is assigned.")
    questions_attempted: int
    questions_correct: int
    accuracy: float = Field(description="Correct attempted question records / attempted question records, as a percentage; a coding question is correct when a submission is PASSED.")
    average_time_seconds: float | None = None
    time_sample_size: int = 0


class QuestionTypeMetric(BaseModel):
    question_type: Literal["MCQ", "CODING"]
    questions_attempted: int
    questions_correct: int
    accuracy: float = Field(description="For MCQ, correct selected answers / selected answers. For coding, solved problems / submitted problems.")
    problems_attempted: int = 0
    problems_solved: int = 0
    success_rate: float = 0
    total_submissions: int = 0


class AnalyticsSummary(BaseModel):
    total_attempts: int = Field(description="All attempts for the authenticated user, including unfinished and terminal non-submitted states.")
    completed_attempts: int = Field(description="Attempts with status SUBMITTED; expired, abandoned, and in-progress attempts are excluded.")
    expired_attempts: int
    abandoned_attempts: int
    questions_assigned: int = Field(description="Questions assigned across SUBMITTED attempts.")
    questions_attempted: int = Field(description="MCQs with a selected option plus coding problems with at least one finalized submission, counted per attempt.")
    questions_correct: int = Field(description="Correct selected MCQ answers plus coding questions with a PASSED submission, counted per attempt.")
    questions_skipped: int = Field(description="Assigned questions in SUBMITTED attempts that have no selected MCQ answer or finalized coding submission.")
    mcq_questions_attempted: int
    mcq_questions_correct: int
    average_accuracy: float = Field(description="MCQ accuracy: correct selected MCQ answers / selected MCQ answers, as a percentage.")
    average_score_percentage: float = Field(description="Arithmetic mean of stored score / max_score percentages for submitted attempts with positive max_score.")
    highest_score_percentage: float | None = None
    lowest_score_percentage: float | None = None
    score_sample_size: int = 0
    average_time_per_question: float | None = Field(default=None, description="Mean positive MCQ answer time; missing, zero, and negative values are excluded.")
    time_sample_size: int = 0
    coding_submissions: int
    coding_problems_attempted: int
    coding_problems_solved: int
    coding_success_rate: float = Field(description="Distinct coding problems with a PASSED submission / distinct coding problems with a submission, as a percentage.")
    topics: list[TopicMetric] = Field(default_factory=list)


class AttemptHistoryItem(BaseModel):
    attempt_id: int
    mock_test_id: int
    mock_test_title: str
    blueprint_id: int | None = None
    company_name: str | None = None
    status: str
    started_at: datetime
    submitted_at: datetime | None = None
    score: float | None = None
    max_score: float | None = None
    score_percentage: float | None = None
    accuracy: float | None = Field(default=None, description="MCQ accuracy for submitted attempts; null for attempts without an MCQ answer sample or not yet scored.")
    time_spent_seconds: int | None = None


class AttemptHistoryPage(BaseModel):
    items: list[AttemptHistoryItem]
    page: int
    page_size: int
    total: int


class CodingAnalytics(BaseModel):
    total_submissions: int
    problems_attempted: int = Field(description="Distinct coding questions with one or more submissions, including pending submissions.")
    problems_solved: int = Field(description="Distinct coding questions with at least one PASSED submission.")
    success_rate: float
    scored_submission_count: int
    average_score: float | None = None
    average_tests_passed: float | None = None
    average_tests_total: float | None = None
    compile_error_count: int
    runtime_error_count: int
    time_limit_count: int
    wrong_answer_count: int
    average_execution_time_ms: float | None = Field(default=None, description="Mean stored execution_time_ms for finalized submissions with a recorded value.")


class CodingProblemItem(BaseModel):
    question_id: int
    title: str | None = None
    submission_count: int
    solved: bool
    best_score: float | None = None
    tests_passed: int | None = None
    tests_total: int | None = None
    best_final_status: str | None = Field(default=None, description="Highest score among finalized submissions; ties use the latest submission. If none is finalized, this is the latest known status.")
    latest_submission_at: datetime | None = None
    successful_submission_at: datetime | None = None


class CodingProblemPage(BaseModel):
    items: list[CodingProblemItem]
    page: int
    page_size: int
    total: int


class MockAnalyticsItem(BaseModel):
    mock_test_id: int
    title: str
    attempt_count: int
    latest_score: float | None = None
    latest_score_percentage: float | None = None
    latest_accuracy: float | None = None
    best_score: float | None = None
    best_score_percentage: float | None = None
    average_score: float | None = None
    average_score_percentage: float | None = None
    latest_submitted_at: datetime | None = None


class MockAnalyticsPage(BaseModel):
    items: list[MockAnalyticsItem]
    page: int
    page_size: int
    total: int


class ProgressPoint(BaseModel):
    period: str = Field(description="Database-local calendar date; Monday date for weekly aggregation.")
    attempt_count: int
    average_score_percentage: float | None = None
    average_accuracy: float = Field(description="Correct selected MCQ answers / selected MCQ answers, as a percentage.")
    mcq_questions_attempted: int
    mcq_questions_correct: int
    questions_attempted: int
    questions_correct: int


class ProgressResponse(BaseModel):
    granularity: Literal["day", "week"]
    items: list[ProgressPoint]


class TopicTimeMetric(BaseModel):
    topic_id: int
    topic_name: str
    questions_attempted: int
    questions_correct: int
    accuracy: float
    average_time_seconds: float | None = None
    time_sample_size: int = 0


class TimeAnalytics(BaseModel):
    average_time_per_question: float | None = Field(default=None, description="Mean positive time_spent_seconds for selected MCQ answers in SUBMITTED attempts.")
    average_time_correct: float | None = Field(default=None, description="Mean positive MCQ answer time where is_correct is true.")
    average_time_incorrect: float | None = Field(default=None, description="Mean positive MCQ answer time where is_correct is false.")
    timed_question_count: int
    timed_correct_count: int
    timed_incorrect_count: int
    by_topic: list[TopicTimeMetric] = Field(default_factory=list)


class AdminAnalyticsOverview(BaseModel):
    total_students: int
    active_students: int
    total_attempts: int
    total_submissions: int
    total_questions_attempted: int
