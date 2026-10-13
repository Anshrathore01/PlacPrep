from decimal import Decimal
from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


QuestionType = Literal["MCQ", "CODING"]
Difficulty = Literal["EASY", "MEDIUM", "HARD"]
BlueprintStatus = Literal["DRAFT", "ACTIVE", "INACTIVE", "ARCHIVED"]
PatternVerification = Literal["OFFICIAL", "REPORTED", "UNVERIFIED"]
PatternSourceType = Literal[
    "COMPANY_OFFICIAL",
    "ASSESSMENT_PROVIDER",
    "RECRUITMENT_REPORT",
    "CANDIDATE_REPORT",
    "INTERNAL",
]
SelectionStrategy = Literal[
    "QUESTION_ID_ASC",
    "EASY_TO_HARD",
    "HARD_TO_EASY",
]


class CompanyCreate(BaseModel):
    company_name: str = Field(min_length=1, max_length=150)
    slug: str = Field(
        min_length=1,
        max_length=150,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    )
    description: Optional[str] = None


class CompanyUpdate(BaseModel):
    company_name: Optional[str] = Field(default=None, min_length=1, max_length=150)
    slug: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=150,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    )
    description: Optional[str] = None


class QuestionClassificationDecision(BaseModel):
    decision: Literal["APPROVE", "NEEDS_EDIT", "REJECT"]
    difficulty: Optional[Difficulty] = None
    reviewer_notes: str = Field(min_length=10, max_length=4000)

    @model_validator(mode="after")
    def validate_decision_fields(self):
        if self.decision == "APPROVE" and self.difficulty is None:
            raise ValueError("difficulty is required when approving a classification")
        if self.decision != "APPROVE" and self.difficulty is not None:
            raise ValueError("difficulty can only be supplied when approving")
        return self


class ReconstructionContentReviewDecision(BaseModel):
    decision: Literal["APPROVE", "REJECT"]
    notes: str = Field(min_length=10, max_length=4000)


class BlueprintCreate(BaseModel):
    blueprint_name: str = Field(min_length=1, max_length=180)
    company_id: Optional[int] = Field(default=None, ge=1)
    program_name: Optional[str] = Field(default=None, max_length=180)
    pattern_version: Optional[str] = Field(default=None, max_length=80)
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    source_name: Optional[str] = Field(default=None, max_length=180)
    source_url: Optional[str] = Field(default=None, max_length=1000)
    source_type: Optional[PatternSourceType] = None
    source_published_at: Optional[date] = None
    source_accessed_at: Optional[datetime] = None
    source_notes: Optional[str] = None
    pattern_details: dict | None = None
    verification_status: PatternVerification = "UNVERIFIED"
    verification_notes: Optional[str] = None
    track_id: Optional[int] = Field(default=None, ge=1)
    duration_seconds: Optional[int] = Field(default=None, ge=1)
    description: Optional[str] = None


class BlueprintUpdate(BaseModel):
    blueprint_name: Optional[str] = Field(default=None, min_length=1, max_length=180)
    company_id: Optional[int] = Field(default=None, ge=1)
    program_name: Optional[str] = Field(default=None, max_length=180)
    pattern_version: Optional[str] = Field(default=None, max_length=80)
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    source_name: Optional[str] = Field(default=None, max_length=180)
    source_url: Optional[str] = Field(default=None, max_length=1000)
    source_type: Optional[PatternSourceType] = None
    source_published_at: Optional[date] = None
    source_accessed_at: Optional[datetime] = None
    source_notes: Optional[str] = None
    pattern_details: dict | None = None
    verification_status: Optional[PatternVerification] = None
    verification_notes: Optional[str] = None
    track_id: Optional[int] = Field(default=None, ge=1)
    duration_seconds: Optional[int] = Field(default=None, ge=1)
    description: Optional[str] = None
    status: Optional[BlueprintStatus] = None


class BlueprintRuleCreate(BaseModel):
    section_name: Optional[str] = Field(default=None, max_length=120)
    section_order: int = Field(default=1, ge=1)
    is_required: bool = True
    time_allocation_seconds: Optional[int] = Field(default=None, ge=1)
    selection_strategy: SelectionStrategy = "QUESTION_ID_ASC"
    track_id: Optional[int] = Field(default=None, ge=1)
    minimum_difficulty: Optional[Difficulty] = None
    maximum_difficulty: Optional[Difficulty] = None
    topic_id: Optional[int] = Field(default=None, ge=1)
    subtopic_id: Optional[int] = Field(default=None, ge=1)
    question_type: Optional[QuestionType] = None
    difficulty: Optional[Difficulty] = None
    question_count: int = Field(ge=1, le=100)
    points: Decimal = Field(default=Decimal("1.00"), gt=0, max_digits=8, decimal_places=2)
    selection_weight: Decimal = Field(
        default=Decimal("1.0000"), gt=0, max_digits=8, decimal_places=4
    )

    @model_validator(mode="after")
    def require_topic_for_subtopic(self):
        if self.subtopic_id is not None and self.topic_id is None:
            raise ValueError("topic_id is required when subtopic_id is supplied")
        return self


class BlueprintRuleUpdate(BaseModel):
    section_name: Optional[str] = Field(default=None, max_length=120)
    section_order: Optional[int] = Field(default=None, ge=1)
    is_required: Optional[bool] = None
    time_allocation_seconds: Optional[int] = Field(default=None, ge=1)
    selection_strategy: Optional[SelectionStrategy] = None
    track_id: Optional[int] = Field(default=None, ge=1)
    minimum_difficulty: Optional[Difficulty] = None
    maximum_difficulty: Optional[Difficulty] = None
    topic_id: Optional[int] = Field(default=None, ge=1)
    subtopic_id: Optional[int] = Field(default=None, ge=1)
    question_type: Optional[QuestionType] = None
    difficulty: Optional[Difficulty] = None
    question_count: Optional[int] = Field(default=None, ge=1, le=100)
    points: Optional[Decimal] = Field(
        default=None, gt=0, max_digits=8, decimal_places=2
    )
    selection_weight: Optional[Decimal] = Field(
        default=None, gt=0, max_digits=8, decimal_places=4
    )
