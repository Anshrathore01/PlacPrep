
"""Provider boundary for structured selection and natural-language tutoring."""

import json
import logging
import random
import re
import time
from abc import ABC, abstractmethod
from typing import TypeVar

from fastapi import HTTPException
from pydantic import BaseModel, ValidationError

from app.ai.config import get_ai_config

logger = logging.getLogger(__name__)
ResponseModel = TypeVar("ResponseModel", bound=BaseModel)
_SECRET_PATTERNS = (
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer [REDACTED]"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"), "[REDACTED_KEY]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"), "[REDACTED_KEY]"),
    (re.compile(r"(?i)(api[_ -]?key|access[_ -]?token|refresh[_ -]?token)\s*[:=]\s*[^\s,;]+"), r"\1=[REDACTED]"),
)


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


def _log_provider_error(operation: str, model: str, error: Exception,
                        sensitive_text: str | None = None,
                        feature: str = "ai") -> None:
    """Log useful provider diagnostics without logging prompts or credentials."""
    status = getattr(error, "status_code", None)
    if status is None:
        status = getattr(error, "code", None)

    message = _safe_provider_message(error, sensitive_text)
    logger.warning(
        "AI provider failure feature=%s provider=gemini model=%s operation=%s attempt=1 category=%s status=%s provider_message=%s",
        feature,
        model,
        operation,
        getattr(error, "category", type(error).__name__),
        status,
        message,
    )


def _safe_provider_message(error: Exception, sensitive_text: str | None = None) -> str:
    """Keep upstream diagnostics while redacting credential-like values."""
    message = getattr(error, "message", None)
    if not isinstance(message, str) or not message.strip():
        return "(no provider message)"
    message = " ".join(message.split())[:800]
    if sensitive_text:
        message = message.replace(sensitive_text, "[REDACTED_INPUT]")
    for pattern, replacement in _SECRET_PATTERNS:
        message = pattern.sub(replacement, message)
    return message


_GEMINI_CLIENTS: dict[str, object] = {}
_OPENAI_CLIENTS: dict[str, object] = {}


def _get_gemini_client(api_key: str):
    if api_key not in _GEMINI_CLIENTS:
        from google import genai
        from google.genai import types

        _GEMINI_CLIENTS[api_key] = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=10_000),
        )
    return _GEMINI_CLIENTS[api_key]


def _get_openai_client(api_key: str):
    if api_key not in _OPENAI_CLIENTS:
        from openai import OpenAI

        _OPENAI_CLIENTS[api_key] = OpenAI(api_key=api_key, timeout=10.0, max_retries=0)
    return _OPENAI_CLIENTS[api_key]


class GeminiProvider(AIProvider):
    def __init__(self, model: str | None = None) -> None:
        config = get_ai_config()

        if not config.api_key:
            raise AIProviderError("AI provider is not configured.")

        if not config.model:
            raise AIProviderError("AI model configuration is empty.")

        self.model = model or config.model
        self.feature = "ai"

        try:
            self._client = _get_gemini_client(config.api_key)
        except ImportError as error:
            raise AIProviderError(
                "AI provider dependency is unavailable.",
                category="dependency",
            ) from error
        except Exception as error:
            _log_provider_error("initialization", self.model, error)
            raise AIProviderError(
                "AI provider could not be initialized.",
                **_failure_details(error),
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
            _log_provider_error("structured generation", self.model, error, prompt, getattr(self, "feature", "ai"))
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
            _log_provider_error("text generation", self.model, error, prompt, getattr(self, "feature", "ai"))
            raise AIProviderError(
                "AI provider could not complete the request.", **_failure_details(error)
            ) from error


def _failure_details(error: Exception) -> dict:
    status = getattr(error, "status_code", None)
    body = getattr(error, "body", None)
    body_error = body.get("error", body) if isinstance(body, dict) else {}
    if not isinstance(body_error, dict):
        body_error = {}
    code = str(getattr(error, "code", "") or body_error.get("code", "") or "").casefold()
    message = str(getattr(error, "message", "") or body_error.get("message", "") or "").casefold()
    quota_exhausted = any(marker in f"{code} {message}" for marker in (
        "insufficient_quota", "billing_hard_limit", "quota_exceeded",
        "resource_exhausted", "exceeded your current quota",
    ))
    retryable = status in {408, 429, 500, 502, 503, 504} and not quota_exhausted
    category = (
        "invalid_structured_output" if isinstance(error, ValidationError)
        else "quota_exhausted" if quota_exhausted else "rate_limit" if status == 429 else "temporary_outage" if retryable
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


def _openai_strict_schema(model: type[ResponseModel]) -> dict:
    """Normalize Pydantic JSON Schema to OpenAI strict Structured Outputs rules."""
    schema = model.model_json_schema()

    def normalize(node):
        if not isinstance(node, dict):
            return
        if node.get("type") == "object":
            properties = node.get("properties", {})
            node["additionalProperties"] = False
            node["required"] = list(properties)
            for child in properties.values():
                normalize(child)
        if node.get("type") == "array":
            normalize(node.get("items"))
        for definition in node.get("$defs", {}).values():
            normalize(definition)

    normalize(schema)
    return schema


class OpenAIProvider(AIProvider):
    def __init__(self, api_key: str, model: str):
        self.model = model
        try:
            self._client = _get_openai_client(api_key)
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
                    "schema": _openai_strict_schema(response_schema),
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
                    if hasattr(provider, "feature"):
                        provider.feature = self.feature
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
                    fallback_attempted = provider_index < len(self.providers) - 1 or attempts <= self.max_retries
                    logger.warning("AI provider failure feature=%s provider=%s model=%s attempt=%s category=%s status=%s fallback_attempted=%s", self.feature, name, provider.model, attempts, error.category, error.status_code, fallback_attempted)
                    if not error.retryable or attempts > self.max_retries:
                        break
                    delay = min(error.retry_after or (0.25 * (2 ** (attempts - 1)) + random.random() * 0.15), 1.5)
                    if time.monotonic() + delay >= deadline:
                        break
                    time.sleep(delay)
        logger.error("AI fallback exhausted feature=%s attempts=%s last_category=%s last_status=%s fallback_succeeded=false", self.feature, total_attempts, last_error.category if last_error else "unconfigured", last_error.status_code if last_error else None)
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
            try:
                providers.append(("openai", OpenAIProvider(config.openai_api_key, config.openai_fallback_model)))
            except AIProviderError:
                logger.warning(
                    "AI provider unavailable feature=initialization provider=openai model=%s category=configuration",
                    config.openai_fallback_model,
                )
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
