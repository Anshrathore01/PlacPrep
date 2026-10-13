from typing import Literal

from pydantic import BaseModel, Field

from app.adaptive.rules import CONFIG

QuestionType = Literal["MCQ", "CODING"]
Difficulty = Literal["EASY", "MEDIUM", "HARD"]


class AdaptiveOption(BaseModel):
    option_key: str
    option_text: str
    display_order: int


class AdaptiveQuestionContent(BaseModel):
    question_id: int
    title: str | None = None
    question_type: QuestionType
    difficulty: str | None = None
    status: str | None = None
    question_text: str | None = None
    is_multiple_correct: bool | None = None
    options: list[AdaptiveOption] | None = None
    problem_statement: str | None = None
    constraints_text: str | None = None
    input_format: str | None = None
    output_format: str | None = None
    starter_code: str | None = None
    examples: list[dict] | None = None


class AdaptiveReason(BaseModel):
    text: str
    topic_accuracy: float | None = None
    topic_sample_size: int = 0
    recent_accuracy: float | None = None
    recent_sample_size: int = 0
    difficulty: str | None = None
    recently_seen: bool
    recommendation_type: Literal[
        "CONCEPT_PRACTICE",
        "IMPLEMENTATION_PRACTICE",
        "DEBUGGING_PRACTICE",
        "OPTIMIZATION_PRACTICE",
        "DIFFICULTY_PROGRESS",
        "TOPIC_EXPLORATION",
    ]


class AdaptiveRecommendation(BaseModel):
    question_id: int
    priority: float = Field(ge=0, le=1)
    question_type: QuestionType
    title: str | None = None
    difficulty: str | None = None
    topic_id: int | None = None
    topic_name: str | None = None
    subtopic_id: int | None = None
    subtopic_name: str | None = None
    reason: AdaptiveReason


class AdaptiveNextResponse(BaseModel):
    status: Literal["OK", "NO_ELIGIBLE_QUESTIONS"]
    message: str | None = None
    question: AdaptiveQuestionContent | None = None
    reason: AdaptiveReason | None = None


class AdaptiveRecommendationsResponse(BaseModel):
    status: Literal["OK", "NO_ELIGIBLE_QUESTIONS"]
    message: str | None = None
    items: list[AdaptiveRecommendation]


class AdaptiveSessionRequest(BaseModel):
    number_of_questions: int | None = Field(
        default=None,
        ge=1,
        le=CONFIG.max_session_questions,
    )
    blueprint_id: int | None = Field(default=None, ge=1)
    question_type: QuestionType | None = None
    track_id: int | None = Field(default=None, ge=1)
    topic_id: int | None = Field(default=None, ge=1)
    subtopic_id: int | None = Field(default=None, ge=1)
    target_difficulty: Difficulty | None = None
    duration_seconds: int | None = Field(default=None, ge=1)


class AdaptiveSessionQuestion(AdaptiveRecommendation):
    sequence_no: int
    points: float
    blueprint_rule_id: int | None = None
    section_name: str | None = None
    section_order: int | None = None
    content: AdaptiveQuestionContent


class AdaptiveSessionResponse(BaseModel):
    status: Literal["OK", "NO_ELIGIBLE_QUESTIONS"]
    message: str | None = None
    session_id: int | None = None
    attempt_id: int | None = None
    mock_test_id: int | None = None
    status_url: str | None = None
    title: str | None = None
    mode: Literal["PRACTICE"] | None = None
    practice_mode: Literal["ADAPTIVE_PRACTICE"] | None = None
    company: str | None = None
    company_id: int | None = None
    program: str | None = None
    pattern_version: str | None = None
    blueprint_id: int | None = None
    duration_seconds: int | None = None
    questions: list[AdaptiveSessionQuestion] = Field(default_factory=list)


class AdaptiveSessionStatusResponse(AdaptiveSessionResponse):
    attempt_status: str | None = None
    started_at: str | None = None
    submitted_at: str | None = None
