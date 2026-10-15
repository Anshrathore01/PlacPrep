
"""Provider boundary for structured selection and natural-language tutoring."""

import json
import logging
import random
import time
from abc import ABC, abstractmethod
from typing import TypeVar

from fastapi import HTTPException
from pydantic import BaseModel

from app.ai.config import get_ai_config

logger = logging.getLogger(__name__)
ResponseModel = TypeVar("ResponseModel", bound=BaseModel)


class AIProviderError(RuntimeError):
    """Sanitized provider failure safe to map to an application response."""

    def __init__(self, message: str, *, status_code: int | None = None,
                 category: str = "provider_error", retryable: bool = False,
                 retry_after: float | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.category = category
        self.retryable = retryable
        self.retry_after = retry_after


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


def _log_provider_error(operation: str, model: str, error: Exception) -> None:
    """Log useful provider diagnostics without logging prompts or credentials."""
    status = getattr(error, "status_code", None)
    if status is None:
        status = getattr(error, "code", None)

    logger.warning(
        "AI provider failure feature=ai provider=gemini model=%s operation=%s attempt=1 category=%s status=%s",
        model,
        operation,
        getattr(error, "category", type(error).__name__),
        status,
    )


class GeminiProvider(AIProvider):
    def __init__(self, model: str | None = None) -> None:
        config = get_ai_config()

        if not config.api_key:
            raise AIProviderError("AI provider is not configured.")

        if not config.model:
            raise AIProviderError("AI model configuration is empty.")

        try:
            from google import genai
            from google.genai import types
        except ImportError as error:
            raise AIProviderError(
                "AI provider dependency is unavailable."
            ) from error

        self.model = model or config.model

        try:
            self._client = genai.Client(
                api_key=config.api_key,
                http_options=types.HttpOptions(timeout=8_000),
            )
        except Exception as error:
            _log_provider_error("initialization", self.model, error)
            raise AIProviderError(
                "AI provider could not be initialized."
            ) from error

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
                raise AIProviderError(
                    "AI provider returned an empty response."
                )

            return response_schema.model_validate(json.loads(response.text))

        except AIProviderError:
            raise
        except Exception as error:
            _log_provider_error("structured generation", self.model, error)
            raise AIProviderError(
                "AI provider could not complete the request.", **_failure_details(error)
            ) from error

    def generate_text(self, prompt: str) -> str:
        try:
            response = self._client.models.generate_content(
                model=self.model,
                contents=prompt,
            )

            if not response.text or not response.text.strip():
                raise AIProviderError(
                    "AI provider returned an empty response."
                )

            return response.text.strip()

        except AIProviderError:
            raise
        except Exception as error:
            _log_provider_error("text generation", self.model, error)
            raise AIProviderError(
                "AI provider could not complete the request.", **_failure_details(error)
            ) from error


def _failure_details(error: Exception) -> dict:
    status = getattr(error, "status_code", None)
    retryable = status in {408, 429, 500, 502, 503, 504}
    category = (
        "rate_limit" if status == 429 else "temporary_outage" if retryable
        else "authentication" if status in {401, 403}
        else "unavailable_model" if status == 404
        else "invalid_request" if status == 400 else "provider_error"
    )
    headers = getattr(error, "headers", None) or {}
    retry_after = None
    try:
        retry_after = float(headers.get("retry-after"))
    except (TypeError, ValueError):
        pass
    return {"status_code": status, "retryable": retryable,
            "category": category, "retry_after": retry_after}


class OpenAIProvider(AIProvider):
    def __init__(self, api_key: str, model: str):
        self.model = model
        try:
            from openai import OpenAI
            self._client = OpenAI(api_key=api_key, timeout=8.0, max_retries=0)
        except ImportError as error:
            raise AIProviderError("OpenAI dependency is unavailable.", category="dependency") from error
        except Exception as error:
            raise AIProviderError("OpenAI provider could not be initialized.", **_failure_details(error)) from error

    def generate_text(self, prompt: str) -> str:
        try:
            response = self._client.chat.completions.create(
                model=self.model, messages=[{"role": "user", "content": prompt}],
            )
            result = response.choices[0].message.content
            if not result or not result.strip():
                raise AIProviderError("AI provider returned an empty response.", category="empty_response")
            return result.strip()
        except AIProviderError:
            raise
        except Exception as error:
            raise AIProviderError("AI provider could not complete the request.", **_failure_details(error)) from error

    def generate_structured(self, prompt: str, response_schema: type[ResponseModel]) -> ResponseModel:
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_schema", "json_schema": {
                    "name": response_schema.__name__, "strict": True,
                    "schema": response_schema.model_json_schema(),
                }},
            )
            content = response.choices[0].message.content
            if not content:
                raise AIProviderError("AI provider returned an empty response.", category="empty_response")
            return response_schema.model_validate_json(content)
        except AIProviderError:
            raise
        except Exception as error:
            raise AIProviderError("AI provider could not complete the request.", **_failure_details(error)) from error


class FallbackAIProvider(AIProvider):
    """Feature-scoped ordered fallback with bounded retries for transient failures."""
    def __init__(self, providers: list[tuple[str, AIProvider]], feature: str,
                 max_retries: int = 1, timeout_seconds: float = 45.0):
        self.providers, self.feature = providers, feature
        self.max_retries, self.timeout_seconds = max_retries, timeout_seconds
        self.model = providers[0][1].model if providers else "unconfigured"

    def _run(self, method: str, *args, validator=None):
        deadline = time.monotonic() + self.timeout_seconds
        last_error = None
        total_attempts = 0
        for provider_index, (name, provider) in enumerate(self.providers):
            attempts = 0
            attempt_budget = max(1, 4 - (len(self.providers) - provider_index - 1))
            while (attempts <= self.max_retries and total_attempts < attempt_budget
                   and time.monotonic() < deadline):
                attempts += 1
                total_attempts += 1
                try:
                    result = getattr(provider, method)(*args)
                    if validator is not None:
                        try:
                            result = validator(result)
                        except Exception as error:
                            last_error = AIProviderError(
                                "AI provider returned invalid structured output.",
                                status_code=502, category="invalid_structured_output",
                            )
                            logger.warning("AI provider failure feature=%s provider=%s model=%s attempt=%s category=invalid_structured_output status=502 fallback_attempted=true", self.feature, name, provider.model, attempts)
                            break
                    if name != self.providers[0][0]:
                        logger.warning("AI fallback succeeded feature=%s provider=%s model=%s attempt=%s", self.feature, name, provider.model, attempts)
                    return result
                except AIProviderError as error:
                    last_error = error
                    logger.warning("AI provider failure feature=%s provider=%s model=%s attempt=%s category=%s status=%s fallback_attempted=%s", self.feature, name, provider.model, attempts, error.category, error.status_code, True)
                    if not error.retryable or attempts > self.max_retries:
                        break
                    delay = min(error.retry_after or (0.25 * (2 ** (attempts - 1)) + random.random() * 0.15), 1.5)
                    if time.monotonic() + delay >= deadline:
                        break
                    time.sleep(delay)
        raise AIProviderError("AI providers are temporarily unavailable.",
                              status_code=last_error.status_code if last_error else None,
                              category=last_error.category if last_error else "unconfigured",
                              retry_after=last_error.retry_after if last_error else None) from last_error

    def generate_text(self, prompt: str) -> str:
        return self._run("generate_text", prompt)

    def generate_structured(self, prompt: str, response_schema: type[ResponseModel]) -> ResponseModel:
        return self._run("generate_structured", prompt, response_schema)

    def generate_structured_validated(self, prompt: str, response_schema: type[ResponseModel], validator):
        return self._run("generate_structured", prompt, response_schema, validator=validator)


def get_ai_provider() -> AIProvider:
    """FastAPI dependency, replaceable with a fake provider in tests."""
    try:
        providers: list[tuple[str, AIProvider]] = []
        config = get_ai_config()
        if config.api_key:
            try:
                providers.append(("gemini_primary", GeminiProvider()))
            except AIProviderError:
                logger.warning("AI provider unavailable feature=initialization provider=gemini model=%s category=configuration", config.model)
            if config.gemini_fallback_model and config.gemini_fallback_model != config.model:
                try:
                    providers.append(("gemini_secondary", GeminiProvider(config.gemini_fallback_model)))
                except AIProviderError:
                    logger.warning("AI provider unavailable feature=initialization provider=gemini model=%s category=configuration", config.gemini_fallback_model)
        if config.openai_api_key:
            providers.append(("openai", OpenAIProvider(config.openai_api_key, config.openai_fallback_model)))
        if not providers:
            raise AIProviderError("AI provider is not configured.")
        return FallbackAIProvider(providers, "ai")
    except AIProviderError as error:
        cause = error.__cause__

        logger.warning(
            "AI provider unavailable model=%s failure_type=%s",
            get_ai_config().model,
            type(cause).__name__ if cause is not None else type(error).__name__,
        )

        raise HTTPException(
            status_code=503,
            detail=(
                "AI provider is not configured or is temporarily unavailable."
            ),
        ) from error
