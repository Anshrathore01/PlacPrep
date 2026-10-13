"""Provider boundary for structured selection and natural-language tutoring."""

import json
import logging
from abc import ABC, abstractmethod
from typing import TypeVar

from fastapi import HTTPException
from pydantic import BaseModel

from app.ai.config import get_ai_config

logger = logging.getLogger(__name__)
ResponseModel = TypeVar("ResponseModel", bound=BaseModel)


class AIProviderError(RuntimeError):
    """Sanitized provider failure safe to map to an application response."""


class AIProvider(ABC):
    model: str

    @abstractmethod
    def generate_structured(
        self,
        prompt: str,
        response_schema: type[ResponseModel],
    ) -> ResponseModel:
        raise NotImplementedError

    @abstractmethod
    def generate_text(self, prompt: str) -> str:
        raise NotImplementedError


class GeminiProvider(AIProvider):
    def __init__(self) -> None:
        config = get_ai_config()
        if not config.api_key:
            raise AIProviderError("AI provider is not configured.")
        if not config.model:
            raise AIProviderError("AI model configuration is empty.")
        try:
            from google import genai
        except ImportError as error:
            raise AIProviderError("AI provider dependency is unavailable.") from error

        self.model = config.model
        try:
            self._client = genai.Client(api_key=config.api_key)
        except Exception as error:
            logger.warning(
                "AI provider initialization failed model=%s error_type=%s",
                self.model,
                type(error).__name__,
            )
            raise AIProviderError("AI provider could not be initialized.") from error

    def generate_structured(
        self,
        prompt: str,
        response_schema: type[ResponseModel],
    ) -> ResponseModel:
        try:
            from google.genai import types

            response = self._client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=response_schema,
                ),
            )
            if response.parsed is not None:
                parsed = response.parsed
                if isinstance(parsed, response_schema):
                    return parsed
                return response_schema.model_validate(parsed)
            if not response.text:
                raise AIProviderError("AI provider returned an empty response.")
            return response_schema.model_validate(json.loads(response.text))
        except AIProviderError:
            raise
        except Exception as error:
            logger.warning(
                "AI structured generation failed model=%s error_type=%s",
                self.model,
                type(error).__name__,
            )
            raise AIProviderError("AI provider could not complete the request.") from error

    def generate_text(self, prompt: str) -> str:
        try:
            response = self._client.models.generate_content(
                model=self.model,
                contents=prompt,
            )
            if not response.text or not response.text.strip():
                raise AIProviderError("AI provider returned an empty response.")
            return response.text.strip()
        except AIProviderError:
            raise
        except Exception as error:
            logger.warning(
                "AI text generation failed model=%s error_type=%s",
                self.model,
                type(error).__name__,
            )
            raise AIProviderError("AI provider could not complete the request.") from error


def get_ai_provider() -> AIProvider:
    """FastAPI dependency, replaceable with a fake provider in tests."""
    try:
        return GeminiProvider()
    except AIProviderError as error:
        cause = error.__cause__
        logger.warning(
            "AI provider unavailable model=%s failure_type=%s",
            get_ai_config().model,
            type(cause).__name__ if cause is not None else type(error).__name__,
        )
        raise HTTPException(
            status_code=503,
            detail="AI provider is not configured or is temporarily unavailable.",
        ) from error
