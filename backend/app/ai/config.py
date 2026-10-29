import os
from dataclasses import dataclass

from app.environment import load_environment

load_environment()


@dataclass(frozen=True)
class AIConfig:
    model: str
    api_key: str | None
    candidate_pool_cap: int
    gemini_fallback_model: str | None
    openai_api_key: str | None
    openai_fallback_model: str


def get_ai_config() -> AIConfig:
    primary_model = (os.getenv("AI_MODEL") or "gemini-2.0-flash").strip()
    fallback_model = (os.getenv("GEMINI_FALLBACK_MODEL") or "").strip() or None
    if fallback_model is None and primary_model != "gemini-1.5-flash":
        fallback_model = "gemini-1.5-flash"

    return AIConfig(
        model=primary_model,
        api_key=(os.getenv("GEMINI_API_KEY") or "").strip() or None,
        candidate_pool_cap=80,
        gemini_fallback_model=fallback_model,
        openai_api_key=(os.getenv("OPENAI_API_KEY") or "").strip() or None,
        openai_fallback_model=(os.getenv("OPENAI_FALLBACK_MODEL") or "gpt-4o-mini").strip(),
    )
