"""Context-safe Placo chat and conversation persistence."""

import logging
import re
import time

from fastapi import HTTPException
from sqlalchemy import text

from app.ai.config import get_ai_config
from app.ai.placo.context import build_context
from app.ai.placo.prompts import PLACO_PROMPT_VERSION, build_placo_prompt
from app.ai.provider import AIProvider, AIProviderError
from app.database import engine
from app.schemas.placo import PlacoChatRequest

logger = logging.getLogger(__name__)
_ANSWER_SEEKING = re.compile(
    r"\b(correct answer|right answer|which option|is\s+[a-e]\s+correct|"
    r"tell me the answer|give me the answer|solve this|what is the answer|"
    r"answer key|confirm my answer|right option|correct option|"
    r"\banswer\b|\boption\s+[a-e]\b|\bsolve\b|\bchoose\b)",
    re.IGNORECASE,
)
_ACTIVE_ASSESSMENT_RESPONSE = (
    "I can’t reveal, confirm, or grade an answer during an active assessment. "
    "Review the core idea in this topic and apply it to the question; I can "
    "walk through the full explanation after you submit."
)


def is_answer_seeking(message: str) -> bool:
    return bool(_ANSWER_SEEKING.search(message))


def _conversation_context(
    connection,
    request: PlacoChatRequest,
    user_id: int,
) -> tuple[int | None, int | None, list[dict]]:
    question_id, attempt_id = request.question_id, request.attempt_id
    if request.conversation_id is None:
        return question_id, attempt_id, []
    conversation = connection.execute(
        text("""
            SELECT conversation_id, question_id, attempt_id
            FROM placo_conversations
            WHERE conversation_id = :conversation_id
              AND user_id = :user_id
        """),
        {
            "conversation_id": request.conversation_id,
            "user_id": user_id,
        },
    ).mappings().first()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    stored_question = conversation["question_id"]
    stored_attempt = conversation["attempt_id"]
    if question_id is not None and question_id != stored_question:
        raise HTTPException(
            status_code=422,
            detail="Conversation is associated with a different question.",
        )
    if attempt_id is not None and attempt_id != stored_attempt:
        raise HTTPException(
            status_code=422,
            detail="Conversation is associated with a different attempt.",
        )
    question_id = stored_question
    attempt_id = stored_attempt
    history_rows = connection.execute(
        text("""
            SELECT role, content
            FROM placo_messages
            WHERE conversation_id = :conversation_id
            ORDER BY message_id DESC
            LIMIT 10
        """),
        {"conversation_id": request.conversation_id},
    ).mappings().all()
    history = [
        {"role": row["role"].casefold(), "content": row["content"]}
        for row in reversed(history_rows)
    ]
    return question_id, attempt_id, history


def _persist_exchange(
    request: PlacoChatRequest,
    user_id: int,
    question_id: int | None,
    attempt_id: int | None,
    assistant_message: str,
) -> int:
    with engine.begin() as connection:
        if request.conversation_id is None:
            result = connection.execute(
                text("""
                    INSERT INTO placo_conversations (
                        user_id, question_id, attempt_id
                    )
                    VALUES (:user_id, :question_id, :attempt_id)
                """),
                {
                    "user_id": user_id,
                    "question_id": question_id,
                    "attempt_id": attempt_id,
                },
            )
            conversation_id = int(result.lastrowid)
        else:
            conversation_id = request.conversation_id
            owned = connection.execute(
                text("""
                    SELECT 1
                    FROM placo_conversations
                    WHERE conversation_id = :conversation_id
                      AND user_id = :user_id
                """),
                {
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                },
            ).scalar_one_or_none()
            if owned is None:
                raise HTTPException(status_code=404, detail="Conversation not found.")
            connection.execute(
                text("""
                    UPDATE placo_conversations
                    SET updated_at = CURRENT_TIMESTAMP
                    WHERE conversation_id = :conversation_id
                """),
                {"conversation_id": conversation_id},
            )
        connection.execute(
            text("""
                INSERT INTO placo_messages (conversation_id, role, content)
                VALUES (:conversation_id, 'USER', :content)
            """),
            {"conversation_id": conversation_id, "content": request.message},
        )
        connection.execute(
            text("""
                INSERT INTO placo_messages (conversation_id, role, content)
                VALUES (:conversation_id, 'ASSISTANT', :content)
            """),
            {
                "conversation_id": conversation_id,
                "content": assistant_message,
            },
        )
    return conversation_id


def chat(
    request: PlacoChatRequest,
    user_id: int,
    provider: AIProvider,
) -> dict:
    if hasattr(provider, "feature"):
        provider.feature = "placo"
    started = time.monotonic()
    with engine.begin() as connection:
        question_id, attempt_id, history = _conversation_context(
            connection, request, user_id
        )
        context = build_context(
            connection,
            user_id,
            question_id,
            attempt_id,
        )

    if (
        context["assessment_state"] == "ACTIVE_ASSESSMENT"
        and is_answer_seeking(request.message)
    ):
        answer = _ACTIVE_ASSESSMENT_RESPONSE
    else:
        # During a live mock, only the broad topic and difficulty are sent.
        # The current question, choices, answer, explanation, and student answer
        # are deliberately withheld.
        safe_message = request.message
        if context["assessment_state"] == "ACTIVE_ASSESSMENT":
            safe_message = (
                "Give a brief conceptual overview of the topic and subtopic. "
                "Do not solve or refer to the active question."
            )
        try:
            answer = provider.generate_text(
                build_placo_prompt(context, safe_message, history)
            )
        except AIProviderError as error:
            logger.warning(
                "Placo chat provider failure user_id=%s feature=placo model=%s category=%s status=%s",
                user_id,
                getattr(provider, "model", "unknown"),
                error.category,
                error.status_code,
            )
            if error.category == "quota_exhausted":
                raise HTTPException(
                    status_code=429,
                    detail="AI assistant quota is currently exhausted for the configured project. Please check provider quota or billing.",
                ) from error
            if error.category == "rate_limit":
                headers = {"Retry-After": str(int(error.retry_after))} if error.retry_after else None
                raise HTTPException(
                    status_code=429,
                    detail="Placo is currently experiencing high demand. Please try again in a few moments.",
                    headers=headers,
                ) from error
            if error.category in {"authentication", "configuration", "dependency"}:
                raise HTTPException(
                    status_code=503,
                    detail="AI service configuration issue. Please verify backend provider settings.",
                ) from error
            if error.category == "unavailable_model":
                raise HTTPException(
                    status_code=503,
                    detail="Configured AI model is unavailable or not supported in this region/project.",
                ) from error
            raise HTTPException(
                status_code=503,
                detail="Placo is temporarily unavailable. Please try again shortly.",
            ) from error

    conversation_id = _persist_exchange(
        request,
        user_id,
        question_id,
        attempt_id,
        answer,
    )
    logger.info(
        "Placo chat completed feature=placo model=%s prompt_version=%s mode=%s "
        "conversation_id=%s status=success latency_ms=%s",
        getattr(provider, "model", get_ai_config().model),
        PLACO_PROMPT_VERSION,
        context["assessment_state"],
        conversation_id,
        round((time.monotonic() - started) * 1000),
    )
    return {
        "conversation_id": conversation_id,
        "message": answer,
        "mode": context["assessment_state"],
        "referenced_question_id": question_id,
    }
