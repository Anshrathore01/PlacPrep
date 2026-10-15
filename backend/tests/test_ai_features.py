import uuid
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import text

from app.ai.mock_generator.prompts import build_selection_prompt
from app.ai.mock_generator.schemas import QuestionSelection
from app.ai.mock_generator.validator import validate_selected_ids
from app.ai.placo.context import build_context
from app.ai.placo.service import is_answer_seeking
from app.ai.provider import AIProvider, AIProviderError, get_ai_provider
from app.auth.dependencies import get_current_user
from app.database import engine
from app.main import app
from app.schemas.ai_mock import AIMockGenerationRequest


class FakeAIProvider(AIProvider):
    model = "fake-test-model"

    def __init__(self, selected_ids=None, text_response="A safe explanation."):
        self.selected_ids = selected_ids or []
        self.text_response = text_response
        self.prompts = []

    def generate_structured(self, prompt, response_schema):
        self.prompts.append(prompt)
        return response_schema(selected_question_ids=self.selected_ids)

    def generate_text(self, prompt):
        self.prompts.append(prompt)
        return self.text_response


class FakeScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one(self):
        return self.value


class FakeMappingResult:
    def __init__(self, value):
        self.value = value

    def mappings(self):
        return self

    def first(self):
        return self.value


def test_ai_mock_schema_validates_mixed_distribution_and_tough_alias():
    request = AIMockGenerationRequest(
        title="Mixed",
        difficulty_mode="MIXED",
        total_questions=20,
        difficulty_distribution={"EASY": 6, "MEDIUM": 10, "TOUGH": 4},
    )
    assert request.difficulty_distribution.TOUGH == 4
    tough = AIMockGenerationRequest(
        title="Tough",
        difficulty_mode="TOUGH",
        total_questions=5,
    )
    assert tough.difficulty_mode == "TOUGH"
    with pytest.raises(ValidationError):
        AIMockGenerationRequest(
            title="Invalid mixed",
            difficulty_mode="MIXED",
            total_questions=20,
            difficulty_distribution={"EASY": 6, "MEDIUM": 10, "TOUGH": 3},
        )


def test_mock_selection_validator_rejects_untrusted_ids_and_difficulties():
    candidates = [
        {"question_id": 21, "difficulty": "EASY"},
        {"question_id": 22, "difficulty": "EASY"},
    ]
    assert validate_selected_ids([22], candidates, 1, "EASY") == [22]
    with pytest.raises(HTTPException, match="outside the eligible candidate pool"):
        validate_selected_ids([99], candidates, 1, "EASY")
    with pytest.raises(HTTPException, match="duplicate question IDs"):
        validate_selected_ids([21, 21], candidates, 2, "EASY")
    with pytest.raises(HTTPException, match="unexpected difficulty"):
        validate_selected_ids([22], [{**candidates[1], "difficulty": "HARD"}], 1, "EASY")


def test_mock_prompt_only_serializes_candidate_selection_data():
    provider = FakeAIProvider([42])
    result = provider.generate_structured(
        build_selection_prompt(
            [{
                "question_id": 42,
                "question_text": "Which structure uses FIFO?",
                "topic": "Data structures",
                "subtopic": "Queues",
                "difficulty": "EASY",
            }],
            1,
            "EASY",
            {"question_type": "MCQ"},
        ),
        QuestionSelection,
    )
    assert result.selected_question_ids == [42]
    assert "correct_option_key" not in provider.prompts[0]
    assert "options" not in provider.prompts[0]


def test_active_mock_context_withholds_question_and_all_answer_data():
    connection = type("FakeConnection", (), {})()
    connection.execute = lambda statement, params=None: (
        FakeScalarResult(1)
        if "SELECT EXISTS" in str(statement)
        else FakeScalarResult("MOCK")
        if "SELECT mode" in str(statement)
        else FakeMappingResult({
            "question_id": 42,
            "question_type": "MCQ",
            "difficulty": "MEDIUM",
            "question_text": "Which option is correct?",
            "mcq_explanation": "The full explanation.",
            "correct_option_key": "B",
            "problem_statement": None,
            "topic_name": "Databases",
            "subtopic_name": "Normalization",
        })
    )
    attempt = {
        "attempt_id": 8,
        "user_id": 7,
        "mock_test_id": 9,
        "status": "IN_PROGRESS",
    }
    with patch(
        "app.ai.placo.context.attempt_service.get_attempt_detail",
        return_value=attempt,
    ):
        context = build_context(connection, 7, 42, 8)
    assert context["assessment_state"] == "ACTIVE_ASSESSMENT"
    assert context["topic"] == "Databases"
    assert "question_text" not in context
    assert "options" not in context
    assert "correct_option_key" not in context
    assert "stored_explanation" not in context
    assert "student_answer" not in context


def test_placo_answer_seeking_detector_catches_direct_active_mock_requests():
    assert is_answer_seeking("Why is option B correct?")
    assert is_answer_seeking("Can you tell me the answer?")
    assert not is_answer_seeking("Can you explain normalization?")


def test_ai_routes_are_documented_and_authentication_is_required():
    schema = app.openapi()
    assert "/ai/mock-tests/generate" in schema["paths"]
    assert "/ai/placo/chat" in schema["paths"]
    response = TestClient(app).post(
        "/ai/placo/chat",
        json={"message": "Explain this concept"},
    )
    assert response.status_code == 401


def test_placo_rejects_empty_message():
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": 42,
        "role": "STUDENT",
    }
    response = TestClient(app).post(
        "/ai/placo/chat",
        json={"message": ""},
    )
    assert response.status_code == 422


def test_missing_provider_configuration_maps_to_safe_503(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr("app.ai.provider.get_ai_config", lambda: SimpleNamespace(
        api_key="test-key", model="test-model", gemini_fallback_model=None,
        openai_api_key=None, openai_fallback_model="gpt-4o-mini",
    ))
    with patch(
        "app.ai.provider.GeminiProvider",
        side_effect=AIProviderError("not configured"),
    ):
        with pytest.raises(HTTPException) as raised:
            get_ai_provider()
    assert raised.value.status_code == 503
    assert "temporarily unavailable" in raised.value.detail


@pytest.fixture
def ai_endpoint_data():
    suffix = uuid.uuid4().hex
    emails = [f"ai-endpoint-{suffix}-{index}@example.test" for index in (1, 2)]
    previous_overrides = dict(app.dependency_overrides)
    user_ids = []
    mock_ids = []
    attempt_ids = []
    question_id = None
    track_id = topic_id = subtopic_id = None
    try:
        with engine.begin() as connection:
            source_id = int(
                connection.execute(
                    text("SELECT source_id FROM sources ORDER BY source_id LIMIT 1")
                ).scalar_one()
            )
            track_id = int(
                connection.execute(
                    text("INSERT INTO tracks (track_name) VALUES (:name)"),
                    {"name": f"AI endpoint track {suffix}"},
                ).lastrowid
            )
            topic_id = int(
                connection.execute(
                    text("""
                        INSERT INTO topics (track_id, topic_name, display_order)
                        VALUES (:track_id, :name, 1)
                    """),
                    {"track_id": track_id, "name": f"AI endpoint topic {suffix}"},
                ).lastrowid
            )
            subtopic_id = int(
                connection.execute(
                    text("""
                        INSERT INTO subtopics (topic_id, subtopic_name, display_order)
                        VALUES (:topic_id, :name, 1)
                    """),
                    {"topic_id": topic_id, "name": f"AI endpoint subtopic {suffix}"},
                ).lastrowid
            )
            for email in emails:
                user_ids.append(
                    int(
                        connection.execute(
                            text("""
                                INSERT INTO users (
                                    email, password_hash, display_name, role, is_active
                                )
                                VALUES (
                                    :email, 'test-only-hash', 'AI Endpoint Test',
                                    'STUDENT', TRUE
                                )
                            """),
                            {"email": email},
                        ).lastrowid
                    )
                )
            question_id = int(
                connection.execute(
                    text("""
                        INSERT INTO questions (
                            source_id, question_type, track_id, title, difficulty,
                            status, content_hash
                        )
                        VALUES (
                            :source_id, 'MCQ', :track_id, :title, 'EASY',
                            'DRAFT', :content_hash
                        )
                    """),
                    {
                        "source_id": source_id,
                        "track_id": track_id,
                        "title": f"AI endpoint question {suffix}",
                        "content_hash": suffix + "endpoint-question",
                    },
                ).lastrowid
            )
            connection.execute(
                text("""
                    INSERT INTO question_subtopics (question_id, subtopic_id, is_primary)
                    VALUES (:question_id, :subtopic_id, TRUE)
                """),
                {"question_id": question_id, "subtopic_id": subtopic_id},
            )
            connection.execute(
                text("""
                    INSERT INTO mcq_questions (
                        question_id, question_text, explanation,
                        correct_option_key, is_multiple_correct
                    )
                    VALUES (
                        :question_id, :question_text, :explanation, 'A', FALSE
                    )
                """),
                {
                    "question_id": question_id,
                    "question_text": f"Which test fixture is {suffix}?",
                    "explanation": "Fixture-only explanation.",
                },
            )
            for order, (key, label) in enumerate(
                (("A", "Alpha"), ("B", "Beta"), ("C", "Gamma"), ("D", "Delta")),
                start=1,
            ):
                connection.execute(
                    text("""
                        INSERT INTO mcq_options (
                            question_id, option_key, option_text, display_order
                        )
                        VALUES (
                            :question_id, :key, :label, :display_order
                        )
                    """),
                    {
                        "question_id": question_id,
                        "key": key,
                        "label": f"{label} {suffix}",
                        "display_order": order,
                    },
                )

            mock_id = int(
                connection.execute(
                    text("""
                        INSERT INTO mock_tests (
                            created_by, title, mode, selection_mode,
                            total_questions, status
                        )
                        VALUES (
                            :user_id, 'AI endpoint active fixture', 'MOCK',
                            'FIXED_QUESTIONS', 1, 'PUBLISHED'
                        )
                    """),
                    {"user_id": user_ids[0]},
                ).lastrowid
            )
            mock_ids.append(mock_id)
            connection.execute(
                text("""
                    INSERT INTO mock_test_questions (
                        mock_test_id, question_id, sequence_no, points
                    )
                    VALUES (:mock_id, :question_id, 1, 1)
                """),
                {"mock_id": mock_id, "question_id": question_id},
            )
            for user_id in user_ids:
                attempt_ids.append(
                    int(
                        connection.execute(
                            text("""
                                INSERT INTO attempts (
                                    user_id, mock_test_id, started_at, status
                                )
                                VALUES (:user_id, :mock_id, NOW(), 'IN_PROGRESS')
                            """),
                            {"user_id": user_id, "mock_id": mock_id},
                        ).lastrowid
                    )
                )

        yield {
            "user_ids": user_ids,
            "question_id": question_id,
            "track_id": track_id,
            "topic_id": topic_id,
            "subtopic_id": subtopic_id,
            "attempt_ids": attempt_ids,
            "mock_ids": mock_ids,
        }
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)
        with engine.begin() as connection:
            connection.execute(
                text("""
                    DELETE FROM placo_messages
                    WHERE conversation_id IN (
                        SELECT conversation_id FROM placo_conversations
                        WHERE user_id IN :user_ids
                    )
                """),
                {"user_ids": tuple(user_ids)},
            )
            connection.execute(
                text("DELETE FROM placo_conversations WHERE user_id IN :user_ids"),
                {"user_ids": tuple(user_ids)},
            )
            if user_ids:
                mock_ids.extend(
                    int(mock_id)
                    for mock_id in connection.execute(
                        text("""
                            SELECT mock_test_id
                            FROM mock_tests
                            WHERE created_by IN :user_ids
                        """),
                        {"user_ids": tuple(user_ids)},
                    ).scalars()
                )
            if attempt_ids:
                connection.execute(
                    text("DELETE FROM attempt_answers WHERE attempt_id IN :attempt_ids"),
                    {"attempt_ids": tuple(attempt_ids)},
                )
                connection.execute(
                    text("DELETE FROM attempts WHERE attempt_id IN :attempt_ids"),
                    {"attempt_ids": tuple(attempt_ids)},
                )
            if mock_ids:
                connection.execute(
                    text("""
                        DELETE FROM mock_test_questions
                        WHERE mock_test_id IN :mock_ids
                    """),
                    {"mock_ids": tuple(mock_ids)},
                )
                connection.execute(
                    text("DELETE FROM mock_tests WHERE mock_test_id IN :mock_ids"),
                    {"mock_ids": tuple(mock_ids)},
                )
            if question_id is not None:
                connection.execute(
                    text("DELETE FROM question_subtopics WHERE question_id = :id"),
                    {"id": question_id},
                )
                connection.execute(
                    text("DELETE FROM mcq_options WHERE question_id = :id"),
                    {"id": question_id},
                )
                connection.execute(
                    text("DELETE FROM mcq_questions WHERE question_id = :id"),
                    {"id": question_id},
                )
                connection.execute(
                    text("DELETE FROM questions WHERE question_id = :id"),
                    {"id": question_id},
                )
            if user_ids:
                connection.execute(
                    text("DELETE FROM users WHERE user_id IN :user_ids"),
                    {"user_ids": tuple(user_ids)},
                )
            if subtopic_id is not None:
                connection.execute(
                    text("DELETE FROM subtopics WHERE subtopic_id = :id"),
                    {"id": subtopic_id},
                )
            if topic_id is not None:
                connection.execute(
                    text("DELETE FROM topics WHERE topic_id = :id"),
                    {"id": topic_id},
                )
            if track_id is not None:
                connection.execute(
                    text("DELETE FROM tracks WHERE track_id = :id"),
                    {"id": track_id},
                )


def test_ai_mock_endpoint_persists_ai_generated_mock(ai_endpoint_data):
    fixture = ai_endpoint_data
    provider = FakeAIProvider([fixture["question_id"]])
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": fixture["user_ids"][0],
        "role": "STUDENT",
    }
    app.dependency_overrides[get_ai_provider] = lambda: provider

    response = TestClient(app).post(
        "/ai/mock-tests/generate",
        json={
            "title": "AI endpoint integration fixture",
            "question_type": "MCQ",
            "track_id": fixture["track_id"],
            "topic_id": fixture["topic_id"],
            "subtopic_id": fixture["subtopic_id"],
            "difficulty_mode": "EASY",
            "total_questions": 1,
            "exclude_recent_questions": False,
        },
    )

    assert response.status_code == 201, response.text
    data = response.json()
    assert data["selection_mode"] == "AI_GENERATED"
    assert data["selected_question_ids"] == [fixture["question_id"]]
    with engine.connect() as connection:
        persisted = connection.execute(
            text("""
                SELECT mt.selection_mode, mtq.question_id
                FROM mock_tests mt
                JOIN mock_test_questions mtq ON mtq.mock_test_id = mt.mock_test_id
                WHERE mt.mock_test_id = :mock_id
            """),
            {"mock_id": data["mock_test_id"]},
        ).mappings().one()
    assert persisted["selection_mode"] == "AI_GENERATED"
    assert int(persisted["question_id"]) == fixture["question_id"]


def test_placo_endpoint_enforces_attempt_ownership_and_active_mock_safety(
    ai_endpoint_data,
):
    fixture = ai_endpoint_data
    provider = FakeAIProvider(text_response="A topic-level conceptual overview.")
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": fixture["user_ids"][0],
        "role": "STUDENT",
    }
    app.dependency_overrides[get_ai_provider] = lambda: provider
    client = TestClient(app)

    unauthorized = client.post(
        "/ai/placo/chat",
        json={
            "message": "Explain this question",
            "question_id": fixture["question_id"],
            "attempt_id": fixture["attempt_ids"][1],
        },
    )
    assert unauthorized.status_code == 403
    assert provider.prompts == []

    response = client.post(
        "/ai/placo/chat",
        json={
            "message": "Explain this question",
            "question_id": fixture["question_id"],
            "attempt_id": fixture["attempt_ids"][0],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["mode"] == "ACTIVE_ASSESSMENT"
    assert "Which test fixture" not in provider.prompts[-1]
    assert "Fixture-only explanation" not in provider.prompts[-1]
    assert "Alpha " not in provider.prompts[-1]
    with engine.connect() as connection:
        persisted = connection.execute(
            text("""
                SELECT role, content
                FROM placo_messages
                WHERE conversation_id = :conversation_id
                ORDER BY message_id
            """),
            {"conversation_id": response.json()["conversation_id"]},
        ).mappings().all()
    assert [row["role"] for row in persisted] == ["USER", "ASSISTANT"]


def test_submitted_result_exposes_trusted_key_and_explanation_context_only_to_owner(
    ai_endpoint_data,
):
    fixture = ai_endpoint_data
    owner_id, other_id = fixture["user_ids"]
    attempt_id = fixture["attempt_ids"][0]
    question_id = fixture["question_id"]
    provider = FakeAIProvider(text_response="The stored answer is correct because it matches the definition.")
    app.dependency_overrides[get_current_user] = lambda: {"user_id": owner_id, "role": "STUDENT"}
    app.dependency_overrides[get_ai_provider] = lambda: provider
    client = TestClient(app)

    active = client.get(f"/attempts/{attempt_id}")
    assert active.status_code == 200, active.text
    active_question = active.json()["questions"][0]
    assert "correct_option_key" not in active_question

    with engine.begin() as connection:
        connection.execute(
            text("UPDATE attempts SET status = 'SUBMITTED', submitted_at = NOW() WHERE attempt_id = :id"),
            {"id": attempt_id},
        )
        connection.execute(
            text("""
                INSERT INTO attempt_answers (
                    attempt_id, question_id, selected_option_key, answer_text,
                    is_correct, points_awarded, time_spent_seconds, answered_at
                ) VALUES (:attempt_id, :question_id, 'B', NULL, FALSE, 0, 3, NOW())
            """),
            {"attempt_id": attempt_id, "question_id": question_id},
        )

    result = client.get(f"/attempts/{attempt_id}")
    assert result.status_code == 200, result.text
    result_question = result.json()["questions"][0]
    assert result_question["correct_option_key"] == "A"
    assert result_question["answer_key_available"] is True
    assert result_question["selected_option_key"] == "B"
    assert result_question["is_correct"] is False

    explanation = client.post(
        "/ai/placo/chat",
        json={
            "message": "Explain why the correct answer is correct and why my answer is wrong.",
            "question_id": question_id,
            "attempt_id": attempt_id,
        },
    )
    assert explanation.status_code == 200, explanation.text
    prompt = provider.prompts[-1]
    assert "correct_option_key" in prompt and '"A"' in prompt
    assert "student_answer" in prompt and '"B"' in prompt
    assert "Fixture-only explanation." in prompt

    app.dependency_overrides[get_current_user] = lambda: {"user_id": other_id, "role": "STUDENT"}
    assert client.get(f"/attempts/{attempt_id}").status_code == 403
    forbidden_explanation = client.post(
        "/ai/placo/chat",
        json={"message": "Explain this answer", "question_id": question_id, "attempt_id": attempt_id},
    )
    assert forbidden_explanation.status_code == 403

    with engine.connect() as connection:
        final_attempt = connection.execute(
            text("SELECT status, score FROM attempts WHERE attempt_id = :id"),
            {"id": attempt_id},
        ).mappings().one()
        attempt_count = connection.execute(
            text("SELECT COUNT(*) FROM attempts WHERE user_id = :user_id"),
            {"user_id": owner_id},
        ).scalar_one()
    assert final_attempt["status"] == "SUBMITTED"
    assert attempt_count == 1


def test_placo_conversation_persists_exchange_and_supplies_history(ai_endpoint_data):
    fixture = ai_endpoint_data
    provider = FakeAIProvider(text_response="A concise explanation.")
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": fixture["user_ids"][0],
        "role": "STUDENT",
    }
    app.dependency_overrides[get_ai_provider] = lambda: provider
    client = TestClient(app)

    first = client.post(
        "/ai/placo/chat",
        json={"message": "Explain binary search."},
    )
    assert first.status_code == 200, first.text
    conversation_id = first.json()["conversation_id"]
    assert first.json()["message"] == "A concise explanation."

    second = client.post(
        "/ai/placo/chat",
        json={
            "message": "When is it useful?",
            "conversation_id": conversation_id,
        },
    )
    assert second.status_code == 200, second.text
    assert second.json()["conversation_id"] == conversation_id
    assert "Explain binary search." in provider.prompts[-1]
    assert "A concise explanation." in provider.prompts[-1]

    with engine.connect() as connection:
        persisted = connection.execute(
            text("""
                SELECT role, content
                FROM placo_messages
                WHERE conversation_id = :conversation_id
                ORDER BY message_id
            """),
            {"conversation_id": conversation_id},
        ).mappings().all()
    assert [row["role"] for row in persisted] == [
        "USER",
        "ASSISTANT",
        "USER",
        "ASSISTANT",
    ]


def test_placo_provider_failure_returns_503_without_persisting_exchange(
    ai_endpoint_data,
):
    fixture = ai_endpoint_data

    class FailingProvider(FakeAIProvider):
        def generate_text(self, prompt):
            raise AIProviderError("Temporary provider outage.")

    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": fixture["user_ids"][0],
        "role": "STUDENT",
    }
    app.dependency_overrides[get_ai_provider] = FailingProvider

    response = TestClient(app).post(
        "/ai/placo/chat",
        json={"message": "Explain binary search."},
    )
    assert response.status_code == 503
    assert "temporarily unavailable" in response.json()["detail"]

    with engine.connect() as connection:
        count = connection.execute(
            text("""
                SELECT COUNT(*)
                FROM placo_conversations
                WHERE user_id = :user_id
            """),
            {"user_id": fixture["user_ids"][0]},
        ).scalar_one()
    assert count == 0


def test_fallback_provider_uses_primary_without_fallback():
    from app.ai.provider import FallbackAIProvider

    primary = FakeAIProvider(text_response="Primary answer")
    secondary = FakeAIProvider(text_response="Secondary answer")
    fallback = FallbackAIProvider([("gemini_primary", primary), ("openai", secondary)], "placo")
    assert fallback.generate_text("safe prompt") == "Primary answer"
    assert len(primary.prompts) == 1
    assert not secondary.prompts


def test_fallback_provider_retries_transient_then_advances():
    from app.ai.provider import FallbackAIProvider

    class FailsTransiently(FakeAIProvider):
        def generate_text(self, prompt):
            self.prompts.append(prompt)
            raise AIProviderError("temporary", status_code=503, category="temporary_outage", retryable=True)

    first, second, final = FailsTransiently(), FailsTransiently(), FakeAIProvider(text_response="OpenAI answer")
    fallback = FallbackAIProvider([("gemini_primary", first), ("gemini_secondary", second), ("openai", final)], "placo")
    with patch("app.ai.provider.time.sleep"):
        assert fallback.generate_text("safe prompt") == "OpenAI answer"
    assert len(first.prompts) == 2
    assert len(second.prompts) == 1
    assert len(final.prompts) == 1


def test_fallback_provider_does_not_retry_permanent_errors():
    from app.ai.provider import FallbackAIProvider

    class InvalidRequest(FakeAIProvider):
        def generate_text(self, prompt):
            self.prompts.append(prompt)
            raise AIProviderError("invalid", status_code=400, category="invalid_request")

    primary, secondary = InvalidRequest(), FakeAIProvider(text_response="fallback")
    fallback = FallbackAIProvider([("gemini_primary", primary), ("openai", secondary)], "placo")
    assert fallback.generate_text("prompt") == "fallback"
    assert len(primary.prompts) == 1


def test_fallback_structured_output_runs_existing_id_validator():
    from app.ai.provider import FallbackAIProvider

    invalid = FakeAIProvider([999])
    valid = FakeAIProvider([42])
    fallback = FallbackAIProvider([("gemini_primary", invalid), ("openai", valid)], "mock_generation")
    selected = fallback.generate_structured_validated(
        "select", QuestionSelection,
        lambda result: validate_selected_ids(result.selected_question_ids,
            [{"question_id": 42, "difficulty": "EASY"}], 1, "EASY"),
    )
    assert selected == [42]
    assert len(invalid.prompts) == len(valid.prompts) == 1
