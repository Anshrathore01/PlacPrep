from fastapi import APIRouter, Depends

from app.ai.placo.service import chat
from app.ai.provider import AIProvider, get_ai_provider
from app.ai.rate_limit import enforce_user_limit
from app.auth.dependencies import get_current_user
from app.schemas.placo import PlacoChatRequest, PlacoChatResponse

router = APIRouter(prefix="/ai/placo", tags=["Placo"])


@router.post("/chat", response_model=PlacoChatResponse)
def placo_chat(
    request: PlacoChatRequest,
    current_user: dict = Depends(get_current_user),
    provider: AIProvider = Depends(get_ai_provider),
):
    enforce_user_limit("placo", int(current_user["user_id"]))
    return chat(request, int(current_user["user_id"]), provider)
