from typing import Literal

from pydantic import BaseModel, Field, StrictInt, model_validator

DifficultyMode = Literal["EASY", "MEDIUM", "TOUGH", "MIXED"]
QuestionType = Literal["MCQ", "CODING"]


class DifficultyDistribution(BaseModel):
    EASY: int = Field(ge=0, le=100)
    MEDIUM: int = Field(ge=0, le=100)
    TOUGH: int = Field(ge=0, le=100)


class AIMockGenerationRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    question_type: QuestionType = "MCQ"
    track_id: int | None = Field(default=None, ge=1)
    topic_id: int | None = Field(default=None, ge=1)
    subtopic_id: int | None = Field(default=None, ge=1)
    difficulty_mode: DifficultyMode
    total_questions: int = Field(ge=1, le=100)
    duration_seconds: StrictInt | None = Field(default=None, ge=60, le=28_800)
    difficulty_distribution: DifficultyDistribution | None = None
    blueprint_id: int | None = Field(default=None, ge=1)
    exclude_recent_questions: bool = True

    @model_validator(mode="after")
    def validate_distribution(self):
        if self.difficulty_mode == "MIXED":
            if self.difficulty_distribution is None:
                raise ValueError(
                    "difficulty_distribution is required for MIXED mode."
                )
            if sum(self.difficulty_distribution.model_dump().values()) != self.total_questions:
                raise ValueError(
                    "Difficulty distribution must sum to total_questions."
                )
        elif self.difficulty_distribution is not None:
            raise ValueError(
                "difficulty_distribution is only valid for MIXED mode."
            )
        if self.subtopic_id is not None and self.topic_id is None:
            raise ValueError("topic_id is required when subtopic_id is supplied.")
        return self


class AIMockGenerationResponse(BaseModel):
    mock_test_id: int
    blueprint_id: int | None = None
    title: str
    mode: str
    selection_mode: str
    duration_seconds: int | None = None
    total_questions: int
    status: str
    selected_question_ids: list[int]
