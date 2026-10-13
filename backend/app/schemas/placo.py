from pydantic import BaseModel, Field


class PlacoChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    question_id: int | None = Field(default=None, ge=1)
    attempt_id: int | None = Field(default=None, ge=1)
    conversation_id: int | None = Field(default=None, ge=1)


class PlacoChatResponse(BaseModel):
    conversation_id: int
    message: str
    mode: str
    referenced_question_id: int | None = None
