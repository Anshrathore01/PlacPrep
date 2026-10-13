from fastapi import APIRouter, Depends

from app.ai.mock_generator.service import generate_mock
from app.ai.provider import AIProvider, get_ai_provider
from app.ai.rate_limit import enforce_user_limit
from app.auth.dependencies import get_current_user
from app.schemas.ai_mock import (
    AIMockGenerationRequest,
    AIMockGenerationResponse,
)

router = APIRouter(prefix="/ai/mock-tests", tags=["AI Mock Generator"])


@router.post("/generate", response_model=AIMockGenerationResponse, status_code=201)
def generate_ai_mock(
    request: AIMockGenerationRequest,
    current_user: dict = Depends(get_current_user),
    provider: AIProvider = Depends(get_ai_provider),
):
    enforce_user_limit("mock", int(current_user["user_id"]))
    return generate_mock(request, int(current_user["user_id"]), provider)
