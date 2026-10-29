import logging
import os
import time
from contextvars import ContextVar
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import bindparam, event, text

from app.environment import load_environment
from app.database import engine, test_connection
from app.routers import attempts
from app.routers import coding_practice
from app.services import question_service
from app.auth.router import router as auth_router
from app.auth.dependencies import get_current_user, require_admin
from app.auth.dependencies import get_optional_current_user
from app.routers.admin import router as admin_router
from app.routers.analytics import admin_router as admin_analytics_router
from app.routers.analytics import router as analytics_router
from app.routers.adaptive import router as adaptive_router
from app.routers.ai_mock import router as ai_mock_router
from app.routers.placo import router as placo_router
from app.services import blueprint_service
from fastapi import Depends

logger = logging.getLogger("app.performance")
_request_metrics: ContextVar[dict | None] = ContextVar("request_metrics", default=None)


@event.listens_for(engine, "before_cursor_execute")
def _start_query_timer(connection, cursor, statement, parameters, context, executemany):
    context._placprep_query_started = time.perf_counter()


@event.listens_for(engine, "after_cursor_execute")
def _record_query_time(connection, cursor, statement, parameters, context, executemany):
    started = getattr(context, "_placprep_query_started", None)
    metrics = _request_metrics.get()
    if started is not None and metrics is not None:
        metrics["db_queries"] += 1
        metrics["db_time_ms"] += (time.perf_counter() - started) * 1000

load_environment()

app = FastAPI(
    title="Placement Preparation Platform API",
    version="1.0.0",
)


@app.middleware("http")
async def log_slow_requests(request, call_next):
    metrics = {"db_queries": 0, "db_time_ms": 0.0}
    token = _request_metrics.set(metrics)
    started = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        duration_ms = (time.perf_counter() - started) * 1000
        route = request.scope.get("route")
        route_template = getattr(route, "path", "unmatched")
        if duration_ms >= 1000 or status_code == 429:
            logger.warning(
                "slow_request method=%s route=%s status=%s duration_ms=%s db_queries=%s db_time_ms=%s",
                request.method,
                route_template,
                status_code,
                round(duration_ms),
                metrics["db_queries"],
                round(metrics["db_time_ms"]),
            )
        _request_metrics.reset(token)
frontend_origins = [
    origin.strip()
    for origin in os.getenv(
        "FRONTEND_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=frontend_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Retry-After"],
)

app.include_router(attempts.router)
app.include_router(coding_practice.router)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(analytics_router)
app.include_router(admin_analytics_router)
app.include_router(adaptive_router)
app.include_router(ai_mock_router)
app.include_router(placo_router)


def _ready_active_blueprints(connection, company_id: int | None = None) -> list[dict]:
    rows = connection.execute(
        text("""
            SELECT blueprint_id
            FROM test_blueprints
            WHERE status = 'ACTIVE'
              AND (company_id = :company_id OR :company_id IS NULL)
            ORDER BY program_name, pattern_version, blueprint_id
        """),
        {"company_id": company_id},
    ).scalars().all()
    result = []
    for blueprint_id in rows:
        preview = blueprint_service.preview_blueprint(connection, int(blueprint_id))
        if preview["ready_for_mock"]:
            bp = blueprint_service.get_blueprint(connection, int(blueprint_id))
            bp["ready_for_mock"] = True  # explicitly mark as ready for the frontend
            result.append(bp)
    return result


def _company_full_length_mocks(connection, company_id: int) -> list[dict]:
    company = connection.execute(
        text("SELECT company_name, slug FROM companies WHERE company_id = :company_id"),
        {"company_id": company_id},
    ).mappings().first()
    if company is None:
        return []

    if (company["company_name"] or "").strip().lower() != "tcs":
        return []

    rows = connection.execute(
        text("""
            SELECT mt.mock_test_id, mt.title, mt.total_questions, mt.duration_seconds
            FROM mock_tests mt
            WHERE (
                mt.title LIKE 'TCS NQT Full Length Paper %'
                OR mt.title LIKE 'TCS NQT Paper %'
            )
              AND mt.status = 'PUBLISHED'
            ORDER BY mt.title
        """)
    ).mappings().all()

    result = []
    for row in rows:
        sections = connection.execute(
            text("""
                SELECT DISTINCT
                    JSON_UNQUOTE(JSON_EXTRACT(q.source_metadata, '$.section')) AS section_name
                FROM mock_test_questions mtq
                JOIN questions q ON q.question_id = mtq.question_id
                WHERE mtq.mock_test_id = :mock_test_id
                ORDER BY section_name
            """),
            {"mock_test_id": row["mock_test_id"]},
        ).scalars().all()

        coding_count = connection.execute(
            text("""
                SELECT COUNT(*)
                FROM mock_test_questions mtq
                JOIN questions q ON q.question_id = mtq.question_id
                WHERE mtq.mock_test_id = :mock_test_id
                  AND q.question_type = 'CODING'
            """),
            {"mock_test_id": row["mock_test_id"]},
        ).scalar_one()

        paper_number = None
        if isinstance(row["title"], str):
            match = __import__("re").search(r"Paper\s+(\d+)", row["title"])
            if match:
                paper_number = int(match.group(1))

        result.append({
            "mock_test_id": int(row["mock_test_id"]),
            "title": row["title"],
            "paper_number": paper_number,
            "total_questions": int(row["total_questions"]),
            "duration_seconds": row["duration_seconds"],
            "sections": [section for section in sections if section],
            "coding_question_count": int(coding_count),
        })

    result.sort(key=lambda item: (item["paper_number"] if item["paper_number"] is not None else 9999, item["title"]))
    return result


@app.get("/blueprints")
def list_active_blueprints():
    with engine.connect() as connection:
        return _ready_active_blueprints(connection)


@app.get("/companies")
def list_companies():
    with engine.connect() as connection:
        rows = connection.execute(
            text("""
                SELECT DISTINCT c.company_id, c.company_name, c.slug,
                       c.description
                FROM companies c
                WHERE (c.description NOT LIKE '%Disposable%' OR c.description IS NULL)
                ORDER BY c.company_name, c.company_id
            """)
        ).mappings().all()
    return [dict(row) for row in rows]


@app.get("/companies/{company_id}")
def get_company(company_id: int):
    with engine.connect() as connection:
        company = connection.execute(
            text("""
                SELECT company_id, company_name, slug, description
                FROM companies
                WHERE company_id = :company_id
            """),
            {"company_id": company_id},
        ).mappings().first()
        if company is None:
            raise HTTPException(status_code=404, detail="Company not found.")
        blueprints = _ready_active_blueprints(connection, company_id)
        return {
            **dict(company),
            "blueprints": blueprints,
            "full_length_mocks": _company_full_length_mocks(connection, company_id),
        }


@app.get("/companies/{company_id}/blueprints")
def list_company_blueprints(company_id: int):
    with engine.connect() as connection:
        exists = connection.execute(
            text("SELECT 1 FROM companies WHERE company_id = :company_id"),
            {"company_id": company_id},
        ).scalar_one_or_none()
        if exists is None:
            raise HTTPException(status_code=404, detail="Company not found.")
        return _ready_active_blueprints(connection, company_id)


@app.get("/companies/{company_id}/blueprints/{blueprint_id}")
def get_company_blueprint(company_id: int, blueprint_id: int):
    with engine.connect() as connection:
        blueprint = blueprint_service.get_blueprint(connection, blueprint_id)
        if (
            blueprint["company_id"] != company_id
            or blueprint["status"] != "ACTIVE"
            or not blueprint_service.preview_blueprint(
                connection, blueprint_id
            )["ready_for_mock"]
        ):
            raise HTTPException(status_code=404, detail="Blueprint not found.")
        return blueprint


@app.get("/blueprints/{blueprint_id}")
def get_active_blueprint(blueprint_id: int):
    with engine.connect() as connection:
        blueprint = blueprint_service.get_blueprint(connection, blueprint_id)
        if (
            blueprint["status"] != "ACTIVE"
            or not blueprint_service.preview_blueprint(
                connection, blueprint_id
            )["ready_for_mock"]
        ):
            raise HTTPException(status_code=404, detail="Blueprint not found.")
        return blueprint


# ============================================================
# RESPONSE / REQUEST MODELS
# ============================================================

class QuestionListItem(BaseModel):
    question_id: int
    title: Optional[str] = None
    question_type: str
    difficulty: Optional[str] = None


class MCQOption(BaseModel):
    id: Optional[int] = None
    label: str
    text: str
    order: int
    option_key: str
    option_text: str
    display_order: int


class QuestionDetail(BaseModel):
    question_id: int
    title: Optional[str] = None
    question_type: str
    difficulty: Optional[str] = None
    status: Optional[str] = None
    question_text: Optional[str] = None
    is_multiple_correct: Optional[bool] = None
    options: Optional[list[MCQOption]] = None
    problem_statement: Optional[str] = None
    constraints_text: Optional[str] = None
    input_format: Optional[str] = None
    output_format: Optional[str] = None
    starter_code: Optional[str] = None
    examples: Optional[list[dict]] = None


class CreateMockTestRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    total_questions: Optional[int] = Field(default=10, ge=1, le=100)
    question_type: Optional[str] = None
    track_id: Optional[int] = None
    difficulty: Optional[str] = None
    duration_seconds: Optional[int] = Field(default=None, ge=1)
    mode: str = "MOCK"
    blueprint_id: Optional[int] = Field(default=None, ge=1)
    topic_id: Optional[int] = Field(default=None, ge=1)
    subtopic_id: Optional[int] = Field(default=None, ge=1)


class TaxonomySubtopic(BaseModel):
    subtopic_id: int
    subtopic_name: str


class TaxonomyTopic(BaseModel):
    topic_id: int
    topic_name: str
    subtopics: list[TaxonomySubtopic] = []


class TaxonomyTrack(BaseModel):
    track_id: int
    track_name: str
    topics: list[TaxonomyTopic] = []


@app.get("/taxonomy", response_model=list[TaxonomyTrack])
def get_taxonomy():
    with engine.connect() as connection:
        tracks = connection.execute(
            text("""
                SELECT track_id, track_name
                FROM tracks
                ORDER BY track_name, track_id
            """)
        ).mappings().all()

        if not tracks:
            return []

        track_ids = [track["track_id"] for track in tracks]
        topics = connection.execute(
            text("""
                SELECT topic_id, topic_name, track_id
                FROM topics
                WHERE track_id IN :track_ids
                ORDER BY topic_name, topic_id
            """).bindparams(bindparam("track_ids", expanding=True)),
            {"track_ids": track_ids},
        ).mappings().all()

        subtopics_by_topic = {}
        if topics:
            topic_ids = [topic["topic_id"] for topic in topics]
            subtopics = connection.execute(
                text("""
                    SELECT subtopic_id, subtopic_name, topic_id
                    FROM subtopics
                    WHERE topic_id IN :topic_ids
                    ORDER BY subtopic_name, subtopic_id
                """).bindparams(bindparam("topic_ids", expanding=True)),
                {"topic_ids": topic_ids},
            ).mappings().all()

            for subtopic in subtopics:
                subtopics_by_topic.setdefault(subtopic["topic_id"], []).append(
                    {
                        "subtopic_id": int(subtopic["subtopic_id"]),
                        "subtopic_name": subtopic["subtopic_name"],
                    }
                )

        topics_by_track = {}
        for topic in topics:
            topics_by_track.setdefault(topic["track_id"], []).append(
                {
                    "topic_id": int(topic["topic_id"]),
                    "topic_name": topic["topic_name"],
                    "subtopics": subtopics_by_topic.get(topic["topic_id"], []),
                }
            )

        return [
            {
                "track_id": int(track["track_id"]),
                "track_name": track["track_name"],
                "topics": topics_by_track.get(track["track_id"], []),
            }
            for track in tracks
        ]


class MockTestListItem(BaseModel):
    mock_test_id: int
    blueprint_id: Optional[int] = None
    company_id: Optional[int] = None
    company_name: Optional[str] = None
    program_name: Optional[str] = None
    pattern_version: Optional[str] = None
    verification_status: Optional[str] = None
    title: str
    mode: str
    selection_mode: str
    duration_seconds: Optional[int] = None
    total_questions: int
    status: str


class CodingSubmissionRequest(BaseModel):
    attempt_id: int = Field(ge=1)
    question_id: int = Field(ge=1)
    language: str = Field(min_length=1, max_length=10)
    source_code: str = Field(min_length=1, max_length=50_000)


# ============================================================
# HELPERS
# ============================================================

def _validate_question_type(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None

    value = value.upper()

    if value not in {"MCQ", "CODING"}:
        raise HTTPException(
            status_code=400,
            detail="question_type must be MCQ or CODING",
        )

    return value


def _validate_difficulty(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None

    value = value.upper()

    if value not in {"EASY", "MEDIUM", "HARD"}:
        raise HTTPException(
            status_code=400,
            detail="difficulty must be EASY, MEDIUM, or HARD",
        )

    return value


def _get_question_detail(connection, question_id: int) -> dict:
    return question_service.get_question_detail_student(connection, question_id)


# ============================================================
# BASIC ROUTES
# ============================================================

@app.get("/")
def home():
    return {"message": "FastAPI server is running"}


@app.get("/health")
def health():
    # Liveness only; this remains available while a database is recovering.
    return {"status": "ok"}


@app.get("/test-db")
def test_db():
    success = test_connection()

    if success:
        return {"message": "MySQL connection successful"}

    return {"message": "MySQL connection failed"}


# ============================================================
# QUESTIONS
# ============================================================

@app.get("/questions", response_model=list[QuestionListItem])
def get_questions(
    question_type: Optional[str] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
):
    question_type = _validate_question_type(question_type)

    sql = """
        SELECT question_id, title, question_type, difficulty
        FROM questions
        WHERE status = 'PUBLISHED'
    """
    params = {"limit": limit}

    if question_type:
        sql += " AND question_type = :question_type "
        params["question_type"] = question_type

    sql += " ORDER BY question_id LIMIT :limit "

    with engine.connect() as connection:
        rows = connection.execute(text(sql), params).mappings().all()

    return [dict(row) for row in rows]


@app.get("/questions/{question_id}", response_model=QuestionDetail)
def get_question(question_id: int):
    # Never expose answer keys, explanations, solutions, or hidden test outputs.
    with engine.connect() as connection:
        status_value = connection.execute(
            text("SELECT status FROM questions WHERE question_id = :question_id"),
            {"question_id": question_id},
        ).scalar_one_or_none()
        if status_value != "PUBLISHED":
            raise HTTPException(status_code=404, detail="Question not found")
        return _get_question_detail(connection, question_id)


# ============================================================
# MOCK TEST CREATION / RETRIEVAL
# ============================================================

@app.post("/mock-tests", response_model=MockTestListItem)
def create_mock_test(
    payload: CreateMockTestRequest,
    current_user: Optional[dict] = Depends(get_optional_current_user),
):
    question_type = _validate_question_type(payload.question_type)
    difficulty = _validate_difficulty(payload.difficulty)

    mode = payload.mode.upper()
    if mode not in {"MOCK", "PRACTICE"}:
        raise HTTPException(
            status_code=400,
            detail="mode must be MOCK or PRACTICE",
        )

    with engine.begin() as connection:
        if payload.blueprint_id is not None:
            if current_user is None:
                raise HTTPException(status_code=401, detail="Authentication required.")
            return blueprint_service.create_mock_test_from_blueprint(
                connection,
                payload.blueprint_id,
                payload.title,
                mode,
                current_user["user_id"],
            )

        if payload.subtopic_id is not None and payload.topic_id is None:
            raise HTTPException(status_code=400, detail="topic_id is required with subtopic_id.")
        selected_question_ids = blueprint_service.select_filtered_questions(
            connection,
            question_type,
            payload.track_id,
            difficulty,
            payload.topic_id,
            payload.subtopic_id,
            payload.total_questions or 10,
        )
        return blueprint_service.insert_mock_test(
            connection,
            payload.title,
            mode,
            payload.duration_seconds,
            selected_question_ids,
            current_user["user_id"] if current_user else None,
        )


@app.get("/mock-tests/{mock_test_id}")
def get_mock_test(mock_test_id: int):
    with engine.connect() as connection:
        mock_test = connection.execute(
            text("""
                SELECT
                    mt.mock_test_id,
                    mt.blueprint_id,
                    b.company_id,
                    c.company_name,
                    b.program_name,
                    b.pattern_version,
                    b.verification_status,
                    mt.title,
                    mt.mode,
                    mt.selection_mode,
                    mt.duration_seconds,
                    mt.total_questions,
                    mt.status
                FROM mock_tests mt
                LEFT JOIN test_blueprints b ON b.blueprint_id = mt.blueprint_id
                LEFT JOIN companies c ON c.company_id = b.company_id
                WHERE mt.mock_test_id = :mock_test_id
            """),
            {"mock_test_id": mock_test_id},
        ).mappings().first()

        if mock_test is None:
            raise HTTPException(
                status_code=404,
                detail=f"Mock test {mock_test_id} not found",
            )

        rows = connection.execute(
            text("""
                SELECT sequence_no, points, question_id
                FROM mock_test_questions
                WHERE mock_test_id = :mock_test_id
                ORDER BY sequence_no
            """),
            {"mock_test_id": mock_test_id},
        ).mappings().all()

        question_details = question_service.get_question_details_student(
            connection,
            [int(row["question_id"]) for row in rows],
        )
        questions = []
        section_by_sequence = {}
        if mock_test["blueprint_id"] is not None:
            blueprint = blueprint_service.get_blueprint(
                connection, int(mock_test["blueprint_id"])
            )
            next_sequence = 1
            for rule in blueprint["rules"]:
                candidates = blueprint_service._candidate_question_ids(
                    connection, blueprint, rule
                )
                if not rule.get("is_required", True) and len(candidates) < int(
                    rule["question_count"]
                ):
                    continue
                for _ in range(int(rule["question_count"])):
                    section_by_sequence[next_sequence] = {
                        "blueprint_rule_id": rule["blueprint_rule_id"],
                        "section_name": rule.get("section_name"),
                        "section_order": rule.get("section_order"),
                    }
                    next_sequence += 1
        for row, question in zip(rows, question_details):
            question["sequence_no"] = row["sequence_no"]
            question["points"] = float(row["points"])
            question.update(section_by_sequence.get(int(row["sequence_no"]), {}))
            questions.append(question)

    return {
        **dict(mock_test),
        "questions": questions,
    }


# ============================================================
# MCQ BANK HEALTH
# ============================================================

@app.get("/admin/mcq-health")
def mcq_health(current_user: dict = Depends(require_admin)):
    """
    Development diagnostic for MCQ completeness.

    The current scorer supports single-answer MCQs with 4 or 5 options.
    """
    with engine.connect() as connection:
        total_mcq = connection.execute(
            text("""
                SELECT COUNT(*)
                FROM questions
                WHERE question_type = 'MCQ'
            """)
        ).scalar_one()

        mcq_rows = connection.execute(
            text("""
                SELECT COUNT(*)
                FROM questions q
                JOIN mcq_questions mq
                  ON mq.question_id = q.question_id
                WHERE q.question_type = 'MCQ'
            """)
        ).scalar_one()

        missing_options = connection.execute(
            text("""
                SELECT COUNT(*)
                FROM questions q
                JOIN mcq_questions mq
                  ON mq.question_id = q.question_id
                WHERE q.question_type = 'MCQ'
                  AND (
                      SELECT COUNT(*)
                      FROM mcq_options mo
                      WHERE mo.question_id = q.question_id
                  ) = 0
            """)
        ).scalar_one()

        incomplete_options = connection.execute(
            text("""
                SELECT COUNT(*)
                FROM questions q
                JOIN mcq_questions mq
                  ON mq.question_id = q.question_id
                WHERE q.question_type = 'MCQ'
                  AND (
                      SELECT COUNT(*)
                      FROM mcq_options mo
                      WHERE mo.question_id = q.question_id
                  ) NOT BETWEEN 4 AND 5
            """)
        ).scalar_one()

        missing_answer_key = connection.execute(
            text("""
                SELECT COUNT(*)
                FROM questions q
                JOIN mcq_questions mq
                  ON mq.question_id = q.question_id
                WHERE q.question_type = 'MCQ'
                  AND mq.correct_option_key IS NULL
            """)
        ).scalar_one()

        invalid_answer_key = connection.execute(
            text("""
                SELECT COUNT(*)
                FROM questions q
                JOIN mcq_questions mq
                  ON mq.question_id = q.question_id
                WHERE q.question_type = 'MCQ'
                  AND mq.correct_option_key IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1
                      FROM mcq_options mo
                      WHERE mo.question_id = q.question_id
                        AND mo.option_key = mq.correct_option_key
                  )
            """)
        ).scalar_one()

        multiple_correct = connection.execute(
            text("""
                SELECT COUNT(*)
                FROM questions q
                JOIN mcq_questions mq
                  ON mq.question_id = q.question_id
                WHERE q.question_type = 'MCQ'
                  AND mq.is_multiple_correct = TRUE
            """)
        ).scalar_one()

        eligible_mcq = connection.execute(
            text("""
                SELECT COUNT(*)
                FROM questions q
                JOIN mcq_questions mq
                  ON mq.question_id = q.question_id
                WHERE q.question_type = 'MCQ'
                  AND mq.correct_option_key IS NOT NULL
                  AND mq.is_multiple_correct = FALSE
                  AND EXISTS (
                      SELECT 1
                      FROM mcq_options correct_opt
                      WHERE correct_opt.question_id = mq.question_id
                        AND correct_opt.option_key = mq.correct_option_key
                  )
                  AND (
                      SELECT COUNT(*)
                      FROM mcq_options mo
                      WHERE mo.question_id = q.question_id
                  ) BETWEEN 4 AND 5
            """)
        ).scalar_one()

        option_distribution = connection.execute(
            text("""
                SELECT
                    option_count,
                    COUNT(*) AS question_count
                FROM (
                    SELECT
                        q.question_id,
                        COUNT(mo.option_id) AS option_count
                    FROM questions q
                    JOIN mcq_questions mq
                      ON mq.question_id = q.question_id
                    LEFT JOIN mcq_options mo
                      ON mo.question_id = q.question_id
                    WHERE q.question_type = 'MCQ'
                    GROUP BY q.question_id
                ) x
                GROUP BY option_count
                ORDER BY option_count
            """)
        ).mappings().all()

    return {
        "total_mcq": total_mcq,
        "mcq_rows": mcq_rows,
        "missing_options": missing_options,
        "incomplete_options": incomplete_options,
        "missing_answer_key": missing_answer_key,
        "invalid_answer_key": invalid_answer_key,
        "multiple_correct_not_supported_yet": multiple_correct,
        "eligible_mcq": eligible_mcq,
        "option_distribution": [dict(row) for row in option_distribution],
        "status": "OK" if eligible_mcq > 0 else "NO_USABLE_MCQ"
    }


# ============================================================
# ATTEMPTS
# ============================================================

@app.post("/coding-submissions")
def create_coding_submission(payload: CodingSubmissionRequest, current_user: dict = Depends(get_current_user)):
    from app.judge.docker_sandbox import docker_is_ready
    from app.services import coding_service

    if payload.language != "C++17":
        raise HTTPException(status_code=422, detail="Only C++17 submissions are supported.")
    if not payload.source_code.strip():
        raise HTTPException(status_code=422, detail="Source code must not be empty.")
    if not docker_is_ready():
        raise HTTPException(
            status_code=503,
            detail=(
                "The isolated coding judge is unavailable. Start Docker and build "
                "the configured judge image before submitting code."
            ),
        )
    with engine.begin() as connection:
        submission_id = coding_service.create_submission(
            connection,
            payload.attempt_id,
            payload.question_id,
            payload.language,
            payload.source_code,
            current_user,
        )
    return {
        "submission_id": submission_id,
        "attempt_id": payload.attempt_id,
        "question_id": payload.question_id,
        "status": "QUEUED",
        "message": "Coding submission queued for isolated C++17 judging.",
    }


@app.get("/coding-submissions/{submission_id}")
def read_coding_submission(
    submission_id: int,
    current_user: dict = Depends(get_current_user),
):
    from app.services import coding_service

    with engine.connect() as connection:
        return coding_service.get_submission(connection, submission_id, current_user)
