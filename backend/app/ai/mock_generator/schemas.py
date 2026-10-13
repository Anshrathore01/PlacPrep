from pydantic import BaseModel, Field


class QuestionSelection(BaseModel):
    selected_question_ids: list[int] = Field(max_length=100)
