"""Deterministic filtering, bounded AI curation, and normal mock persistence."""

import logging
import time

from fastapi import HTTPException
from sqlalchemy import bindparam, text

from app.ai.config import get_ai_config
from app.ai.mock_generator.prompts import (
    MOCK_SELECTION_PROMPT_VERSION,
    build_selection_prompt,
)
from app.ai.mock_generator.schemas import QuestionSelection
from app.ai.mock_generator.validator import validate_selected_ids
from app.ai.provider import AIProvider, AIProviderError
from app.database import engine
from app.schemas.ai_mock import AIMockGenerationRequest
from app.services import blueprint_service
from app.services.mock_eligibility_service import MOCK_ELIGIBLE_QUESTION_SQL

logger = logging.getLogger(__name__)
_DIFFICULTY = {"EASY": "EASY", "MEDIUM": "MEDIUM", "TOUGH": "HARD"}


def _difficulty_counts(request: AIMockGenerationRequest) -> dict[str, int]:
    if request.difficulty_mode == "MIXED":
        return {
            "EASY": request.difficulty_distribution.EASY,
            "MEDIUM": request.difficulty_distribution.MEDIUM,
            "HARD": request.difficulty_distribution.TOUGH,
        }
    return {_DIFFICULTY[request.difficulty_mode]: request.total_questions}


def _validate_taxonomy(connection, request: AIMockGenerationRequest) -> None:
    if request.track_id is not None and connection.execute(
        text("SELECT 1 FROM tracks WHERE track_id = :track_id"),
        {"track_id": request.track_id},
    ).scalar_one_or_none() is None:
        raise HTTPException(status_code=422, detail="Track does not exist.")
    if request.topic_id is not None:
        topic_track = connection.execute(
            text("SELECT track_id FROM topics WHERE topic_id = :topic_id"),
            {"topic_id": request.topic_id},
        ).scalar_one_or_none()
        if topic_track is None:
            raise HTTPException(status_code=422, detail="Topic does not exist.")
        if request.track_id is not None and int(topic_track) != request.track_id:
            raise HTTPException(
                status_code=422,
                detail="Topic does not belong to the requested track.",
            )
    if request.subtopic_id is not None:
        subtopic = connection.execute(
            text("""
                SELECT st.topic_id, t.track_id
                FROM subtopics st
                JOIN topics t ON t.topic_id = st.topic_id
                WHERE st.subtopic_id = :subtopic_id
            """),
            {"subtopic_id": request.subtopic_id},
        ).mappings().first()
        if subtopic is None:
            raise HTTPException(status_code=422, detail="Subtopic does not exist.")
        if int(subtopic["topic_id"]) != request.topic_id:
            raise HTTPException(
                status_code=422,
                detail="Subtopic does not belong to the supplied topic.",
            )
        if request.track_id is not None and int(subtopic["track_id"]) != request.track_id:
            raise HTTPException(
                status_code=422,
                detail="Subtopic does not belong to the requested track.",
            )


def _filter_conditions(request: AIMockGenerationRequest) -> tuple[list[str], dict]:
    conditions = [
        f"({MOCK_ELIGIBLE_QUESTION_SQL})",
        "q.question_type = :question_type",
    ]
    params = {"question_type": request.question_type}
    if request.track_id is not None:
        conditions.append("q.track_id = :track_id")
        params["track_id"] = request.track_id
    if request.topic_id is not None:
        conditions.append("""
            EXISTS (
                SELECT 1
                FROM question_subtopics topic_qs
                JOIN subtopics topic_st
                  ON topic_st.subtopic_id = topic_qs.subtopic_id
                WHERE topic_qs.question_id = q.question_id
                  AND topic_st.topic_id = :topic_id
            )
        """)
        params["topic_id"] = request.topic_id
    if request.subtopic_id is not None:
        conditions.append("""
            EXISTS (
                SELECT 1 FROM question_subtopics subtopic_qs
                WHERE subtopic_qs.question_id = q.question_id
                  AND subtopic_qs.subtopic_id = :subtopic_id
            )
        """)
        params["subtopic_id"] = request.subtopic_id
    return conditions, params


def _recent_filter(user_id: int) -> tuple[str, dict]:
    return (
        """
        NOT EXISTS (
            SELECT 1
            FROM (
                SELECT attempt_id, mock_test_id
                FROM attempts
                WHERE user_id = :recent_user_id
                ORDER BY started_at DESC, attempt_id DESC
                LIMIT 5
            ) recent_attempt
            JOIN mock_test_questions recent_mtq
              ON recent_mtq.mock_test_id = recent_attempt.mock_test_id
            WHERE recent_mtq.question_id = q.question_id
        )
        """,
        {"recent_user_id": user_id},
    )


def _candidate_rows(
    connection,
    request: AIMockGenerationRequest,
    user_id: int,
    difficulty: str,
    *,
    exclude_recent: bool,
) -> tuple[int, list[dict]]:
    conditions, params = _filter_conditions(request)
    conditions.append("q.difficulty = :difficulty")
    params["difficulty"] = difficulty
    if exclude_recent:
        recent_sql, recent_params = _recent_filter(user_id)
        conditions.append(recent_sql)
        params.update(recent_params)
    where = " AND ".join(f"({condition})" for condition in conditions)
    count = int(
        connection.execute(
            text(f"SELECT COUNT(*) FROM questions q WHERE {where}"),
            params,
        ).scalar_one()
    )
    pool_limit = min(
        100,
        max(
            get_ai_config().candidate_pool_cap,
            _difficulty_counts(request).get(difficulty, 0),
        ),
    )
    rows = connection.execute(
        text(f"""
            SELECT q.question_id, q.question_type, q.difficulty,
                   CASE
                       WHEN q.question_type = 'MCQ' THEN LEFT(mq.question_text, 1200)
                       ELSE LEFT(cq.problem_statement, 1200)
                   END AS question_text,
                   tr.track_name,
                   (
                       SELECT t.topic_name
                       FROM question_subtopics primary_qs
                       JOIN subtopics primary_st
                         ON primary_st.subtopic_id = primary_qs.subtopic_id
                       JOIN topics t ON t.topic_id = primary_st.topic_id
                       WHERE primary_qs.question_id = q.question_id
                       ORDER BY primary_qs.is_primary DESC, primary_qs.subtopic_id
                       LIMIT 1
                   ) AS topic_name,
                   (
                       SELECT primary_st.subtopic_name
                       FROM question_subtopics primary_qs
                       JOIN subtopics primary_st
                         ON primary_st.subtopic_id = primary_qs.subtopic_id
                       WHERE primary_qs.question_id = q.question_id
                       ORDER BY primary_qs.is_primary DESC, primary_qs.subtopic_id
                       LIMIT 1
                   ) AS subtopic_name
            FROM questions q
            LEFT JOIN mcq_questions mq ON mq.question_id = q.question_id
            LEFT JOIN coding_questions cq ON cq.question_id = q.question_id
            JOIN tracks tr ON tr.track_id = q.track_id
            WHERE {where}
            ORDER BY RAND()
            LIMIT :pool_limit
        """),
        {**params, "pool_limit": pool_limit},
    ).mappings().all()
    return count, [dict(row) for row in rows]


def _candidate_pool(
    connection,
    request: AIMockGenerationRequest,
    user_id: int,
) -> dict[str, list[dict]]:
    _validate_taxonomy(connection, request)
    pools = {}
    for difficulty, required in _difficulty_counts(request).items():
        if not required:
            pools[difficulty] = []
            continue
        all_count, all_rows = _candidate_rows(
            connection, request, user_id, difficulty, exclude_recent=False
        )
        if all_count < required:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Insufficient content-eligible questions.",
                    "difficulty": difficulty,
                    "available": all_count,
                    "requested": required,
                },
            )
        selected_rows = all_rows
        if request.exclude_recent_questions:
            recent_count, recent_rows = _candidate_rows(
                connection, request, user_id, difficulty, exclude_recent=True
            )
            if recent_count >= required:
                selected_rows = recent_rows
        pools[difficulty] = selected_rows
    return pools


def _curate(
    provider: AIProvider,
    candidates: list[dict],
    requested_count: int,
    difficulty: str,
    filters: dict,
) -> list[int]:
    prompt_candidates = [
        {
            "question_id": int(row["question_id"]),
            "question_text": row["question_text"],
            "topic": row["topic_name"],
            "subtopic": row["subtopic_name"],
            "difficulty": row["difficulty"],
        }
        for row in candidates
    ]
    try:
        result = provider.generate_structured(
            build_selection_prompt(
                prompt_candidates,
                requested_count,
                difficulty,
                filters,
            ),
            QuestionSelection,
        )
    except AIProviderError as error:
        raise HTTPException(
            status_code=503,
            detail="AI question curation is temporarily unavailable.",
        ) from error
    return validate_selected_ids(
        result.selected_question_ids,
        candidates,
        requested_count,
        difficulty,
    )


def generate_mock(
    request: AIMockGenerationRequest,
    user_id: int,
    provider: AIProvider,
) -> dict:
    if request.blueprint_id is not None:
        return _generate_blueprint_mock(request, user_id, provider)

    started = time.monotonic()
    with engine.connect() as connection:
        pools = _candidate_pool(connection, request, user_id)
    selected_by_difficulty = {
        difficulty: _curate(
            provider,
            candidates,
            _difficulty_counts(request)[difficulty],
            difficulty,
            {
                "question_type": request.question_type,
                "track_id": request.track_id,
                "topic_id": request.topic_id,
                "subtopic_id": request.subtopic_id,
            },
        )
        for difficulty, candidates in pools.items()
        if _difficulty_counts(request)[difficulty]
    }
    selected_ids = [
        question_id
        for difficulty in ("EASY", "MEDIUM", "HARD")
        for question_id in selected_by_difficulty.get(difficulty, [])
    ]
    if len(selected_ids) != request.total_questions or len(set(selected_ids)) != len(selected_ids):
        raise HTTPException(status_code=502, detail="AI returned an invalid mock selection.")

    conditions, params = _filter_conditions(request)
    conditions.append("q.question_id IN :selected_ids")
    params["selected_ids"] = tuple(selected_ids)
    where = " AND ".join(f"({condition})" for condition in conditions)
    with engine.begin() as connection:
        rows = connection.execute(
            text(f"""
                SELECT q.question_id, q.difficulty
                FROM questions q
                WHERE {where}
                  AND ({MOCK_ELIGIBLE_QUESTION_SQL})
                FOR UPDATE
            """).bindparams(bindparam("selected_ids", expanding=True)),
            params,
        ).all()
        actual = {int(row[0]): str(row[1]) for row in rows}
        expected = {
            question_id: difficulty
            for difficulty, ids in selected_by_difficulty.items()
            for question_id in ids
        }
        if actual != expected:
            raise HTTPException(
                status_code=409,
                detail="The eligible question pool changed during mock creation.",
            )
        result = blueprint_service.insert_mock_test(
            connection,
            request.title,
            "MOCK",
            request.duration_seconds,
            selected_ids,
            user_id,
            selection_mode="AI_GENERATED",
        )
    result["selected_question_ids"] = selected_ids
    logger.info(
        "AI mock generation completed model=%s prompt_version=%s status=success "
        "candidate_count=%s selected_count=%s latency_ms=%s",
        get_ai_config().model,
        MOCK_SELECTION_PROMPT_VERSION,
        sum(len(rows) for rows in pools.values()),
        len(selected_ids),
        round((time.monotonic() - started) * 1000),
    )
    return result


def _generate_blueprint_mock(
    request: AIMockGenerationRequest,
    user_id: int,
    provider: AIProvider,
) -> dict:
    started = time.monotonic()
    try:
        with engine.connect() as connection:
            preview = blueprint_service.preview_blueprint(
                connection, request.blueprint_id
            )
            if not preview["ready_for_mock"]:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "Blueprint is not ready for mock creation.",
                        "errors": preview["errors"],
                    },
                )
            blueprint, deterministic_selections = (
                blueprint_service.select_blueprint_questions(
                    connection, request.blueprint_id
                )
            )
            if request.exclude_recent_questions:
                recent_ids = {
                    int(question_id)
                    for question_id in connection.execute(
                        text("""
                            SELECT DISTINCT recent_mtq.question_id
                            FROM (
                                SELECT attempt_id, mock_test_id
                                FROM attempts
                                WHERE user_id = :user_id
                                ORDER BY started_at DESC, attempt_id DESC
                                LIMIT 5
                            ) recent_attempt
                            JOIN mock_test_questions recent_mtq
                              ON recent_mtq.mock_test_id = recent_attempt.mock_test_id
                        """),
                        {"user_id": user_id},
                    ).scalars().all()
                }
                if recent_ids:
                    rules = blueprint["rules"]
                    recent_candidates = [
                        [
                            question_id
                            for question_id in blueprint_service._candidate_question_ids(
                                connection, blueprint, rule
                            )
                            if question_id not in recent_ids
                        ]
                        for rule in rules
                    ]
                    try:
                        novelty_selections = blueprint_service._allocate_unique_questions(
                            rules,
                            recent_candidates,
                            preserve_candidate_order=True,
                        )
                    except HTTPException as error:
                        if error.status_code != 409:
                            raise
                    else:
                        base_count = sum(
                            len(selection["question_ids"])
                            for selection in deterministic_selections
                        )
                        novelty_count = sum(
                            len(selection["question_ids"])
                            for selection in novelty_selections
                        )
                        if novelty_count >= base_count:
                            deterministic_selections = novelty_selections
            question_ids = [
                question_id
                for selection in deterministic_selections
                for question_id in selection["question_ids"]
            ]
            rows = _question_context_rows(connection, question_ids)
    except HTTPException:
        raise

    if len(question_ids) != request.total_questions:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "total_questions must match the selected blueprint sections.",
                "requested": request.total_questions,
                "blueprint_total": len(question_ids),
            },
        )
    difficulty_counts = _difficulty_counts(request)
    actual_counts = {difficulty: 0 for difficulty in ("EASY", "MEDIUM", "HARD")}
    for row in rows:
        actual_counts[row["difficulty"]] += 1
    row_by_id = {int(row["question_id"]): row for row in rows}
    if any(row["question_type"] != request.question_type for row in rows):
        raise HTTPException(
            status_code=422,
            detail="Blueprint question types do not match question_type.",
        )
    expected_counts = {key: 0 for key in ("EASY", "MEDIUM", "HARD")}
    expected_counts.update(difficulty_counts)
    if any(actual_counts[difficulty] != count for difficulty, count in expected_counts.items()):
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Blueprint question distribution does not match the requested difficulty.",
                "available": actual_counts,
                "requested": expected_counts,
            },
        )

    final_selections = []
    taken = set()
    for selection in deterministic_selections:
        assigned = selection["question_ids"]
        by_difficulty: dict[str, list[int]] = {}
        for question_id in assigned:
            by_difficulty.setdefault(row_by_id[question_id]["difficulty"], []).append(
                question_id
            )
        curated_section = []
        for difficulty, assigned_ids in by_difficulty.items():
            remaining_count = len(assigned_ids)
            candidates = [
                row_by_id[question_id]
                for question_id in assigned_ids
                if question_id not in taken
            ]
            curated = _curate(
                provider,
                candidates,
                remaining_count,
                difficulty,
                {"blueprint_id": request.blueprint_id},
            )
            curated_section.extend(curated)
            taken.update(curated)
        final_selections.append(
            {
                **selection,
                "question_ids": curated_section,
                "points": selection["points"],
            }
        )
    if len(taken) != request.total_questions:
        raise HTTPException(
            status_code=502,
            detail="AI returned an invalid blueprint selection.",
        )
    conditions, params = _filter_conditions(request)
    conditions.append("q.question_id IN :selected_ids")
    params["selected_ids"] = tuple(taken)
    where = " AND ".join(f"({condition})" for condition in conditions)
    with engine.begin() as connection:
        still_valid = connection.execute(
            text(f"""
                SELECT q.question_id
                FROM questions q
                WHERE {where}
                  AND ({MOCK_ELIGIBLE_QUESTION_SQL})
                FOR UPDATE
            """).bindparams(bindparam("selected_ids", expanding=True)),
            params,
        ).scalars().all()
        if {int(question_id) for question_id in still_valid} != taken:
            raise HTTPException(
                status_code=409,
                detail="The eligible question pool changed during mock creation.",
            )
        result = blueprint_service.create_mock_test_from_blueprint(
            connection,
            request.blueprint_id,
            request.title,
            "MOCK",
            user_id,
            selections=final_selections,
            selection_mode="AI_GENERATED",
            duration_seconds=request.duration_seconds,
        )
    result["selected_question_ids"] = [
        question_id
        for section in final_selections
        for question_id in section["question_ids"]
    ]
    logger.info(
        "AI blueprint mock generation completed model=%s prompt_version=%s "
        "status=success candidate_count=%s selected_count=%s latency_ms=%s",
        get_ai_config().model,
        MOCK_SELECTION_PROMPT_VERSION,
        len(rows),
        request.total_questions,
        round((time.monotonic() - started) * 1000),
    )
    return result


def _question_context_rows(connection, question_ids: list[int]) -> list[dict]:
    if not question_ids:
        return []
    placeholders = ", ".join(f":id_{index}" for index in range(len(question_ids)))
    params = {f"id_{index}": value for index, value in enumerate(question_ids)}
    rows = connection.execute(
        text(f"""
            SELECT q.question_id, q.question_type, q.difficulty,
                   CASE
                       WHEN q.question_type = 'MCQ' THEN mq.question_text
                       ELSE cq.problem_statement
                   END AS question_text,
                   (
                       SELECT t.topic_name
                       FROM question_subtopics qs
                       JOIN subtopics st ON st.subtopic_id = qs.subtopic_id
                       JOIN topics t ON t.topic_id = st.topic_id
                       WHERE qs.question_id = q.question_id
                       ORDER BY qs.is_primary DESC, qs.subtopic_id
                       LIMIT 1
                   ) AS topic_name,
                   (
                       SELECT st.subtopic_name
                       FROM question_subtopics qs
                       JOIN subtopics st ON st.subtopic_id = qs.subtopic_id
                       WHERE qs.question_id = q.question_id
                       ORDER BY qs.is_primary DESC, qs.subtopic_id
                       LIMIT 1
                   ) AS subtopic_name
            FROM questions q
            LEFT JOIN mcq_questions mq ON mq.question_id = q.question_id
            LEFT JOIN coding_questions cq ON cq.question_id = q.question_id
            WHERE q.question_id IN ({placeholders})
        """),
        params,
    ).mappings().all()
    return [dict(row) for row in rows]
