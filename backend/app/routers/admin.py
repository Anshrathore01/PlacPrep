import json
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.auth.dependencies import require_admin
from app.database import engine
from app.schemas.governance import (
    CompanyCreate,
    CompanyUpdate,
    BlueprintCreate,
    BlueprintRuleCreate,
    BlueprintRuleUpdate,
    BlueprintUpdate,
    QuestionClassificationDecision,
    ReconstructionContentReviewDecision,
)
from app.services import blueprint_service, question_governance_service
from app.services.mock_eligibility_service import (
    count_mock_eligible,
    evaluate_mock_eligibility,
)

router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
    dependencies=[Depends(require_admin)],
)


class StatusNote(BaseModel):
    note: Optional[str] = Field(default=None, max_length=2000)


@router.post("/companies", status_code=201)
def create_company(payload: CompanyCreate):
    with engine.begin() as connection:
        duplicate = connection.execute(
            text("""
                SELECT company_id
                FROM companies
                WHERE company_name = :company_name OR slug = :slug
            """),
            {"company_name": payload.company_name, "slug": payload.slug},
        ).scalar_one_or_none()
        if duplicate is not None:
            raise HTTPException(
                status_code=409,
                detail="A company with this name or slug already exists.",
            )
        result = connection.execute(
            text("""
                INSERT INTO companies (
                    company_name, slug, description, official_pattern_verified
                )
                VALUES (:company_name, :slug, :description, FALSE)
            """),
            payload.model_dump(),
        )
        return connection.execute(
            text("""
                SELECT company_id, company_name, slug, description,
                       official_pattern_verified
                FROM companies
                WHERE company_id = :company_id
            """),
            {"company_id": result.lastrowid},
        ).mappings().one()


@router.put("/companies/{company_id}")
def update_company(company_id: int, payload: CompanyUpdate):
    values = payload.model_dump(exclude_unset=True)
    if not values:
        raise HTTPException(status_code=400, detail="No company fields supplied.")
    if any(
        values.get(field) is None
        for field in ("company_name", "slug")
        if field in values
    ):
        raise HTTPException(
            status_code=422,
            detail="Company name and slug cannot be null.",
        )
    with engine.begin() as connection:
        exists = connection.execute(
            text("""
                SELECT company_id
                FROM companies
                WHERE company_id = :company_id
                FOR UPDATE
            """),
            {"company_id": company_id},
        ).scalar_one_or_none()
        if exists is None:
            raise HTTPException(status_code=404, detail="Company not found.")
        duplicate = connection.execute(
            text("""
                SELECT company_id
                FROM companies
                WHERE company_id <> :company_id
                  AND (
                    (:company_name IS NOT NULL AND company_name = :company_name)
                    OR (:slug IS NOT NULL AND slug = :slug)
                  )
            """),
            {
                "company_id": company_id,
                "company_name": values.get("company_name"),
                "slug": values.get("slug"),
            },
        ).scalar_one_or_none()
        if duplicate is not None:
            raise HTTPException(
                status_code=409,
                detail="A company with this name or slug already exists.",
            )
        assignments = ", ".join(f"{field} = :{field}" for field in values)
        values["company_id"] = company_id
        connection.execute(
            text(f"UPDATE companies SET {assignments} WHERE company_id = :company_id"),
            values,
        )
        return connection.execute(
            text("""
                SELECT company_id, company_name, slug, description,
                       official_pattern_verified
                FROM companies
                WHERE company_id = :company_id
            """),
            {"company_id": company_id},
        ).mappings().one()


def _validate_foreign_reference(
    connection, table: str, column: str, value: int | None, label: str
) -> None:
    if value is None:
        return
    exists = connection.execute(
        text(f"SELECT 1 FROM {table} WHERE {column} = :value"),
        {"value": value},
    ).scalar_one_or_none()
    if exists is None:
        raise HTTPException(status_code=422, detail=f"{label} does not exist.")


def _validate_blueprint_track(connection, track_id: int | None) -> None:
    _validate_foreign_reference(connection, "tracks", "track_id", track_id, "Track")


def _ensure_active_blueprint_remains_valid(connection, blueprint_id: int) -> None:
    status = connection.execute(
        text("SELECT status FROM test_blueprints WHERE blueprint_id = :id"),
        {"id": blueprint_id},
    ).scalar_one()
    if status != "ACTIVE":
        return
    errors = blueprint_service.validate_blueprint(connection, blueprint_id)
    if errors:
        error_code = (
            "INSUFFICIENT_BLUEPRINT_CONTENT"
            if any(
                error.get("code") == "INSUFFICIENT_BLUEPRINT_CONTENT"
                for error in errors
            )
            else "INVALID_BLUEPRINT"
        )
        raise HTTPException(
            status_code=422,
            detail={
                "code": error_code,
                "message": "Active blueprint is invalid.",
                "blueprint_id": blueprint_id,
                "errors": errors,
            },
        )


def _ensure_blueprint_version_mutable(blueprint: dict) -> None:
    if blueprint.get("activated_at") is not None or blueprint["status"] in {
        "ACTIVE",
        "ARCHIVED",
    }:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "IMMUTABLE_PATTERN_VERSION",
                "message": (
                    "Activated pattern versions are immutable; create a new "
                    "version to change the assessment structure."
                ),
                "blueprint_id": blueprint["blueprint_id"],
                "pattern_version": blueprint.get("pattern_version"),
            },
        )


@router.get("/question-health")
def question_health():
    with engine.connect() as connection:
        status_counts = {
            row["status"]: int(row["count"])
            for row in connection.execute(
                text("""
                    SELECT status, COUNT(*) AS count
                    FROM questions
                    GROUP BY status
                """)
            ).mappings().all()
        }
        for status in (
            "DRAFT", "REVIEW", "PUBLISHED", "REJECTED", "ARCHIVED"
        ):
            status_counts.setdefault(status, 0)

        total_questions = connection.execute(
            text("SELECT COUNT(*) FROM questions")
        ).scalar_one()
        mcq_metrics = connection.execute(
            text("""
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN mq.question_id IS NULL THEN 1 ELSE 0 END)
                        AS missing_content,
                    SUM(CASE WHEN mq.question_id IS NOT NULL
                                  AND TRIM(mq.question_text) = ''
                             THEN 1 ELSE 0 END) AS missing_question_text,
                    SUM(CASE WHEN mq.question_id IS NOT NULL
                                  AND mq.correct_option_key IS NULL
                             THEN 1 ELSE 0 END) AS missing_answer_key,
                    SUM(CASE WHEN mq.question_id IS NOT NULL
                                  AND mq.correct_option_key IS NOT NULL
                                  AND NOT EXISTS (
                                      SELECT 1 FROM mcq_options mo
                                      WHERE mo.question_id = q.question_id
                                        AND mo.option_key = mq.correct_option_key
                                  )
                             THEN 1 ELSE 0 END) AS invalid_answer_key,
                    SUM(CASE WHEN mq.question_id IS NOT NULL
                                  AND mq.is_multiple_correct = TRUE
                             THEN 1 ELSE 0 END) AS multiple_correct,
                    SUM(CASE WHEN mq.question_id IS NOT NULL
                                  AND (
                                      SELECT COUNT(*) FROM mcq_options mo
                                      WHERE mo.question_id = q.question_id
                                  ) = 0
                             THEN 1 ELSE 0 END) AS missing_options,
                    SUM(CASE WHEN mq.question_id IS NOT NULL
                                  AND (
                                      SELECT COUNT(*) FROM mcq_options mo
                                      WHERE mo.question_id = q.question_id
                                  ) NOT BETWEEN 4 AND 5
                             THEN 1 ELSE 0 END) AS unsupported_option_count,
                    SUM(CASE WHEN mq.question_id IS NOT NULL
                                  AND TRIM(mq.question_text) <> ''
                                  AND mq.correct_option_key IS NOT NULL
                                  AND mq.is_multiple_correct = FALSE
                                  AND EXISTS (
                                      SELECT 1 FROM mcq_options mo
                                      WHERE mo.question_id = q.question_id
                                        AND mo.option_key = mq.correct_option_key
                                        AND TRIM(mo.option_text) <> ''
                                  )
                                  AND (
                                      SELECT COUNT(*) FROM mcq_options mo
                                      WHERE mo.question_id = q.question_id
                                  ) BETWEEN 4 AND 5
                                  AND NOT EXISTS (
                                      SELECT 1 FROM mcq_options mo
                                      WHERE mo.question_id = q.question_id
                                        AND TRIM(mo.option_text) = ''
                                  )
                             THEN 1 ELSE 0 END) AS valid
                FROM questions q
                LEFT JOIN mcq_questions mq ON mq.question_id = q.question_id
                WHERE q.question_type = 'MCQ'
            """)
        ).mappings().one()
        coding_metrics = connection.execute(
            text("""
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN cq.question_id IS NULL THEN 1 ELSE 0 END)
                        AS missing_content,
                    SUM(CASE WHEN cq.question_id IS NOT NULL
                                  AND (
                                      TRIM(cq.problem_statement) = ''
                                      OR TRIM(COALESCE(cq.input_format, '')) = ''
                                      OR TRIM(COALESCE(cq.output_format, '')) = ''
                                      OR TRIM(COALESCE(cq.constraints_text, '')) = ''
                                      OR TRIM(COALESCE(cq.starter_code, '')) = ''
                                  )
                             THEN 1 ELSE 0 END) AS missing_formats_or_content,
                    SUM(CASE WHEN NOT EXISTS (
                                  SELECT 1 FROM question_examples e
                                  WHERE e.question_id = q.question_id
                              )
                             THEN 1 ELSE 0 END) AS missing_examples,
                    SUM(CASE WHEN NOT EXISTS (
                                  SELECT 1 FROM coding_test_cases tc
                                  WHERE tc.question_id = q.question_id
                              )
                             THEN 1 ELSE 0 END) AS missing_tests,
                    SUM(CASE WHEN NOT EXISTS (
                                  SELECT 1 FROM coding_test_cases tc
                                  WHERE tc.question_id = q.question_id
                                    AND tc.is_hidden = FALSE
                              )
                             THEN 1 ELSE 0 END) AS missing_public_tests,
                    SUM(CASE WHEN NOT EXISTS (
                                  SELECT 1 FROM coding_test_cases tc
                                  WHERE tc.question_id = q.question_id
                                    AND tc.is_hidden = TRUE
                              )
                             THEN 1 ELSE 0 END) AS missing_hidden_tests
                FROM questions q
                LEFT JOIN coding_questions cq ON cq.question_id = q.question_id
                WHERE q.question_type = 'CODING'
            """)
        ).mappings().one()
        classification = connection.execute(
            text("""
                SELECT
                    SUM(CASE WHEN NOT EXISTS (
                        SELECT 1
                        FROM question_subtopics qs
                        JOIN subtopics st ON st.subtopic_id = qs.subtopic_id
                        JOIN topics t ON t.topic_id = st.topic_id
                        WHERE qs.question_id = q.question_id
                          AND t.track_id = q.track_id
                    ) THEN 1 ELSE 0 END) AS without_topic_or_subtopic,
                    SUM(CASE WHEN NOT EXISTS (
                        SELECT 1 FROM question_subtopics qs
                        WHERE qs.question_id = q.question_id
                    ) THEN 1 ELSE 0 END) AS without_subtopic,
                    SUM(CASE WHEN NOT EXISTS (
                        SELECT 1 FROM question_tags qt
                        WHERE qt.question_id = q.question_id
                    ) THEN 1 ELSE 0 END) AS without_tags
                FROM questions q
            """)
        ).mappings().one()
        published_eligible_mcq = count_mock_eligible(connection, "MCQ")

    mcq_response = {key: int(value or 0) for key, value in mcq_metrics.items()}
    mcq_response["invalid"] = mcq_response["total"] - mcq_response["valid"]
    return {
        "total_questions": int(total_questions),
        "status_counts": status_counts,
        "mcq": mcq_response,
        "coding": {key: int(value or 0) for key, value in coding_metrics.items()},
        "classification": {
            key: int(value or 0) for key, value in classification.items()
        },
        "published_eligible_mcq": int(published_eligible_mcq),
        "mock_eligible_mcq": int(published_eligible_mcq),
    }


@router.get("/content/activation-summary")
def content_activation_summary():
    with engine.connect() as connection:
        counts = connection.execute(
            text("""
                SELECT
                    COUNT(*) AS total,
                    SUM(q.status = 'PUBLISHED') AS published,
                    SUM(q.status = 'DRAFT') AS draft,
                    SUM(q.status = 'REVIEW') AS review,
                    SUM(
                        q.status = 'PUBLISHED'
                        AND q.question_type = 'MCQ'
                        AND (""" + blueprint_service.ELIGIBLE_QUESTION_SQL + """)
                    ) AS eligible_mcq,
                    SUM(
                        q.status = 'PUBLISHED'
                        AND q.question_type = 'CODING'
                        AND (""" + blueprint_service.ELIGIBLE_QUESTION_SQL + """)
                        AND (""" + blueprint_service.JUDGE_COMPATIBLE_CODING_SQL + """)
                    ) AS eligible_coding
                FROM questions q
            """)
        ).mappings().one()
    return {key: int(value or 0) for key, value in counts.items()}


def _company_readiness_rows(connection, company_id: int | None = None) -> list[dict]:
    rows = connection.execute(
        text("""
            SELECT b.blueprint_id, b.blueprint_name, b.program_name,
                   b.pattern_version, b.status, b.verification_status,
                   c.company_id, c.company_name
            FROM test_blueprints b
            LEFT JOIN companies c ON c.company_id = b.company_id
            WHERE (:company_id IS NULL OR b.company_id = :company_id)
            ORDER BY c.company_name, b.program_name, b.pattern_version,
                     b.blueprint_id
        """),
        {"company_id": company_id},
    ).mappings().all()
    results = []
    for row in rows:
        preview = blueprint_service.preview_blueprint(
            connection, int(row["blueprint_id"])
        )
        required = [
            rule for rule in preview["rules"] if rule["is_required"]
        ]
        rules_by_section = {
            (rule.get("section_name") or "").strip().casefold(): rule
            for rule in preview["rules"]
        }
        pattern_sections = []
        for section in preview["pattern_sections"]:
            rule = rules_by_section.get(
                (section.get("section_name") or "").strip().casefold()
            )
            question_count = section.get("question_count")
            pattern_sections.append({
                **section,
                "required_count": question_count,
                "eligible_count": rule["eligible_count"] if rule is not None else None,
                "eligible_count_known": rule is not None,
                "selection_supported": section.get(
                    "selection_supported", rule is not None
                ),
                "eligible_published_count": (
                    rule["eligible_count"] if rule is not None else None
                ),
                "readiness_problem": (
                    "UNSUPPORTED_PATTERN_SECTION"
                    if rule is None or section.get("selection_supported") is False
                    else "INSUFFICIENT_BLUEPRINT_CONTENT"
                    if question_count is not None and not rule["sufficient"]
                    else "QUESTION_COUNT_UNRESOLVED"
                    if question_count is None
                    else None
                ),
            })
        results.append({
            **dict(row),
            "valid": preview["valid"],
            "ready_for_mock": preview["ready_for_mock"],
            "required_questions": (
                sum(
                    int(section["required_count"])
                    for section in pattern_sections
                    if isinstance(section.get("required_count"), int)
                )
                if pattern_sections
                else sum(rule["question_count"] for rule in required)
            ),
            "eligible_published_questions": sum(
                rule["eligible_count"] for rule in required
            ),
            "available_questions": sum(
                rule["eligible_count"] for rule in required
            ),
            "sections": pattern_sections or preview["rules"],
            "pattern_sections": pattern_sections,
            "source": {
                "name": preview["source_name"],
                "url": preview["source_url"],
                "type": preview["source_type"],
                "published_at": preview["source_published_at"],
                "accessed_at": preview["source_accessed_at"],
                "notes": preview["source_notes"],
            },
            "problems": preview["errors"],
            "errors": preview["errors"],
        })
    return results


@router.get("/companies/{company_id}/readiness")
def company_readiness_for_company(company_id: int):
    with engine.connect() as connection:
        company = connection.execute(
            text("""
                SELECT company_id, company_name, slug
                FROM companies
                WHERE company_id = :company_id
            """),
            {"company_id": company_id},
        ).mappings().first()
        if company is None:
            raise HTTPException(status_code=404, detail="Company not found.")
        return {
            **dict(company),
            "blueprints": _company_readiness_rows(connection, company_id),
        }


@router.get("/company-readiness")
def company_readiness():
    with engine.connect() as connection:
        return _company_readiness_rows(connection)


@router.get("/questions")
def list_questions(
    status: Optional[str] = Query(default=None),
    question_type: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
):
    statuses = question_governance_service.QUESTION_STATUSES
    if status is not None and status not in statuses:
        raise HTTPException(status_code=400, detail="Unsupported question status.")
    if question_type is not None and question_type not in {"MCQ", "CODING"}:
        raise HTTPException(status_code=400, detail="Unsupported question type.")

    filters = []
    params = {"limit": limit}
    if status is not None:
        filters.append("q.status = :status")
        params["status"] = status
    if question_type is not None:
        filters.append("q.question_type = :question_type")
        params["question_type"] = question_type
    where = f"WHERE {' AND '.join(filters)}" if filters else ""

    with engine.connect() as connection:
        rows = connection.execute(
            text(f"""
                SELECT q.question_id, q.source_id, s.source_name,
                       q.source_question_number, q.question_type, q.track_id,
                       q.title, q.difficulty, q.status, q.content_hash,
                       q.source_metadata, q.created_at, q.updated_at
                FROM questions q
                JOIN sources s ON s.source_id = q.source_id
                {where}
                ORDER BY q.question_id
                LIMIT :limit
            """),
            params,
        ).mappings().all()
        return [dict(row) for row in rows]


def _question_review_details(connection, question_id: int) -> dict:
    question = connection.execute(
        text("""
            SELECT q.question_id, q.source_id, s.source_name, s.source_type,
                   s.source_url, s.source_notes, q.source_question_number,
                   q.question_type, q.track_id, q.title, q.difficulty, q.status,
                   q.content_hash, q.source_metadata, q.created_at, q.updated_at
            FROM questions q
            LEFT JOIN sources s ON s.source_id = q.source_id
            WHERE q.question_id = :question_id
        """),
        {"question_id": question_id},
    ).mappings().first()
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")

    output = dict(question)
    if question["question_type"] == "MCQ":
        content = connection.execute(
            text("""
                SELECT question_text, explanation, correct_option_key,
                       is_multiple_correct
                FROM mcq_questions
                WHERE question_id = :question_id
            """),
            {"question_id": question_id},
        ).mappings().first()
        options = connection.execute(
            text("""
                SELECT option_key, option_text, display_order
                FROM mcq_options
                WHERE question_id = :question_id
                ORDER BY display_order
            """),
            {"question_id": question_id},
        ).mappings().all()
        output["content"] = dict(content) if content else None
        output["options"] = [dict(option) for option in options]
        output["taxonomy"] = [
            dict(row)
            for row in connection.execute(
                text("""
                    SELECT t.topic_id, t.topic_name, st.subtopic_id,
                           st.subtopic_name, t.track_id, qs.is_primary
                    FROM question_subtopics qs
                    JOIN subtopics st ON st.subtopic_id = qs.subtopic_id
                    JOIN topics t ON t.topic_id = st.topic_id
                    WHERE qs.question_id = :question_id
                    ORDER BY qs.is_primary DESC, st.subtopic_id
                """),
                {"question_id": question_id},
            ).mappings().all()
        ]
    else:
        content = connection.execute(
            text("""
                SELECT problem_statement, constraints_text, input_format,
                       output_format, starter_code, solution_pseudocode,
                       solution_explanation
                FROM coding_questions
                WHERE question_id = :question_id
            """),
            {"question_id": question_id},
        ).mappings().first()
        output["content"] = dict(content) if content else None

    latest_review = connection.execute(
        text("""
            SELECT review_id, reviewer_id, decision, notes, reviewed_at
            FROM question_reviews
            WHERE question_id = :question_id
            ORDER BY COALESCE(reviewed_at, '1000-01-01 00:00:00') DESC,
                     review_id DESC
            LIMIT 1
        """),
        {"question_id": question_id},
    ).mappings().first()
    output["latest_review"] = dict(latest_review) if latest_review else None
    output["status_history"] = [
        dict(row)
        for row in connection.execute(
            text("""
                SELECT h.previous_status, h.new_status, h.note,
                       h.created_at, u.user_id, u.email
                FROM question_status_history h
                JOIN users u ON u.user_id = h.actor_user_id
                WHERE h.question_id = :question_id
                ORDER BY h.event_id
            """),
            {"question_id": question_id},
        ).mappings().all()
    ]
    output["source"] = {
        "source_id": question["source_id"],
        "source_name": question["source_name"],
        "source_type": question["source_type"],
        "source_url": question["source_url"],
        "source_notes": question["source_notes"],
        "source_question_number": question["source_question_number"],
        "source_metadata": question["source_metadata"],
    }

    eligibility = evaluate_mock_eligibility(connection, question_id)
    output["mock_eligibility"] = eligibility
    output["provenance_state"] = (
        "SOURCE_MISSING"
        if question["source_type"] is None
        else "AUTHORIZATION_NOT_EVIDENCED"
        if "Scraped-source authorization is not evidenced in source URL/notes."
        in eligibility["blockers"]
        else "AUTHORIZATION_EVIDENCED"
        if question["source_type"] == "SCRAPED"
        else "AUTHORIZATION_NOT_REQUIRED"
    )
    output["source_traceability_state"] = (
        "MISSING"
        if "Question source traceability is missing." in eligibility["blockers"]
        else "PRESENT"
    )
    output["duplicate_matches"] = [
        dict(row)
        for row in connection.execute(
            text("""
                SELECT dm.duplicate_match_id, dm.question_id_a, dm.question_id_b,
                       dm.similarity_score, dm.match_type, dm.resolution,
                       other.question_id AS matched_question_id,
                       other.status AS matched_question_status,
                       (
                           SELECT qr.decision
                           FROM question_reviews qr
                           WHERE qr.question_id = other.question_id
                           ORDER BY COALESCE(
                               qr.reviewed_at, '1000-01-01 00:00:00'
                           ) DESC, qr.review_id DESC
                           LIMIT 1
                       ) AS matched_latest_review_decision
                FROM duplicate_matches dm
                JOIN questions other
                  ON other.question_id = CASE
                      WHEN dm.question_id_a = :question_id
                      THEN dm.question_id_b ELSE dm.question_id_a
                  END
                WHERE dm.question_id_a = :question_id
                   OR dm.question_id_b = :question_id
                ORDER BY dm.duplicate_match_id
            """),
            {"question_id": question_id},
        ).mappings().all()
    ]
    output["duplicate_state"] = (
        "UNRESOLVED"
        if any(
            match["resolution"] == "PENDING"
            for match in output["duplicate_matches"]
        )
        or any(
            blocker.startswith("Question duplicates existing question ")
            for blocker in eligibility["blockers"]
        )
        else "RESOLVED"
        if output["duplicate_matches"]
        else "NO_MATCHES"
    )
    exact_duplicate_blockers = [
        blocker
        for blocker in eligibility["blockers"]
        if blocker.startswith("Question duplicates existing question ")
    ]
    if exact_duplicate_blockers:
        duplicate_ids = [
            int(blocker.removeprefix("Question duplicates existing question ").rstrip("."))
            for blocker in exact_duplicate_blockers
        ]
        duplicate_rows = connection.execute(
            text("""
                SELECT q.question_id, q.status,
                       (
                           SELECT qr.decision
                           FROM question_reviews qr
                           WHERE qr.question_id = q.question_id
                           ORDER BY COALESCE(
                               qr.reviewed_at, '1000-01-01 00:00:00'
                           ) DESC, qr.review_id DESC
                           LIMIT 1
                       ) AS latest_review_decision
                FROM questions q
                WHERE q.question_id IN :question_ids
            """),
            {"question_ids": tuple(duplicate_ids)},
        ).mappings().all()
        duplicate_state_by_id = {
            int(row["question_id"]): dict(row) for row in duplicate_rows
        }
        output["publication_duplicate_blockers"] = [
            {
                "question_id": duplicate_id,
                "match_type": None,
                "resolution": None,
                "resolution_tracking": "NOT_RECORDED",
                "matched_question_status": duplicate_state_by_id.get(
                    duplicate_id, {}
                ).get("status"),
                "matched_latest_review_decision": duplicate_state_by_id.get(
                    duplicate_id, {}
                ).get("latest_review_decision"),
                "reason": blocker,
            }
            for duplicate_id, blocker in zip(
                duplicate_ids, exact_duplicate_blockers, strict=True
            )
        ]
    else:
        output["publication_duplicate_blockers"] = []
    output["open_reports"] = [
        dict(row)
        for row in connection.execute(
            text("""
                SELECT report_id, report_type, details, status
                FROM question_reports
                WHERE question_id = :question_id
                  AND status IN ('OPEN', 'IN_REVIEW')
                ORDER BY report_id
            """),
            {"question_id": question_id},
        ).mappings().all()
    ]
    return output


@router.get("/questions/reconstruction-review-queue")
def list_reconstruction_review_queue(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    with engine.connect() as connection:
        question_ids = connection.execute(
            text("""
                SELECT DISTINCT q.question_id
                FROM questions q
                JOIN question_reviews qr ON qr.question_id = q.question_id
                WHERE q.question_type = 'MCQ'
                  AND q.status = 'REVIEW'
                  AND qr.decision = 'PENDING'
                  AND qr.review_id = (
                      SELECT latest.review_id
                      FROM question_reviews latest
                      WHERE latest.question_id = q.question_id
                      ORDER BY COALESCE(
                          latest.reviewed_at, '1000-01-01 00:00:00'
                      ) DESC, latest.review_id DESC
                      LIMIT 1
                  )
                  AND LEFT(
                      qr.notes,
                      CHAR_LENGTH(:review_prefix)
                  ) = :review_prefix
                ORDER BY q.question_id
                LIMIT :limit OFFSET :offset
            """),
            {
                "review_prefix": question_governance_service.RECONSTRUCTION_REVIEW_PREFIX,
                "limit": limit,
                "offset": offset,
            },
        ).scalars().all()
        candidates = []
        for question_id in question_ids:
            details = _question_review_details(connection, int(question_id))
            candidates.append({
                "question_id": details["question_id"],
                "topic": details["taxonomy"],
                "difficulty": details["difficulty"],
                "source": details["source"],
                "provenance_state": details["provenance_state"],
                "source_traceability_state": details["source_traceability_state"],
                "duplicate_state": details["duplicate_state"],
                "duplicate_matches": details["duplicate_matches"],
                "publication_duplicate_blockers": details[
                    "publication_duplicate_blockers"
                ],
                "mock_eligibility": details["mock_eligibility"],
            })
        return candidates


@router.get("/questions/{question_id}")
def get_question_for_review(question_id: int):
    with engine.connect() as connection:
        return _question_review_details(connection, question_id)


@router.post("/questions/{question_id}/content-review")
def review_reconstructed_mcq_content(
    question_id: int,
    payload: ReconstructionContentReviewDecision,
    current_user: dict = Depends(require_admin),
):
    with engine.begin() as connection:
        return question_governance_service.decide_reconstruction_mcq_review(
            connection,
            question_id,
            payload.decision,
            current_user["user_id"],
            payload.notes,
        )


@router.post("/questions/{question_id}/review")
def submit_question_for_review(
    question_id: int,
    current_user: dict = Depends(require_admin),
):
    with engine.begin() as connection:
        return question_governance_service.transition_question_status(
            connection, question_id, "REVIEW", current_user["user_id"]
        )


@router.post("/questions/{question_id}/publish")
def publish_question(
    question_id: int,
    current_user: dict = Depends(require_admin),
):
    with engine.begin() as connection:
        return question_governance_service.transition_question_status(
            connection, question_id, "PUBLISHED", current_user["user_id"]
        )


@router.post("/questions/{question_id}/reject")
def reject_question(
    question_id: int,
    payload: StatusNote | None = None,
    current_user: dict = Depends(require_admin),
):
    with engine.begin() as connection:
        return question_governance_service.transition_question_status(
            connection,
            question_id,
            "REJECTED",
            current_user["user_id"],
            payload.note if payload else None,
        )


@router.post("/questions/{question_id}/archive")
def archive_question(
    question_id: int,
    payload: StatusNote | None = None,
    current_user: dict = Depends(require_admin),
):
    with engine.begin() as connection:
        return question_governance_service.transition_question_status(
            connection,
            question_id,
            "ARCHIVED",
            current_user["user_id"],
            payload.note if payload else None,
        )


@router.post("/questions/{question_id}/difficulty-review")
def review_question_difficulty(
    question_id: int,
    payload: QuestionClassificationDecision,
    current_user: dict = Depends(require_admin),
):
    with engine.begin() as connection:
        question = connection.execute(
            text("""
                SELECT question_id, status, source_question_number, source_metadata
                FROM questions
                WHERE question_id = :question_id
                FOR UPDATE
            """),
            {"question_id": question_id},
        ).mappings().first()
        if question is None:
            raise HTTPException(status_code=404, detail="Question not found.")
        if question["status"] != "REVIEW":
            raise HTTPException(
                status_code=409,
                detail="Difficulty decisions require a question in REVIEW status.",
            )

        review = connection.execute(
            text("""
                SELECT review_id, notes
                FROM question_reviews
                WHERE question_id = :question_id
                  AND decision = 'PENDING'
                  AND notes LIKE 'QUESTION_CLASSIFICATION:%'
                ORDER BY review_id DESC
                LIMIT 1
                FOR UPDATE
            """),
            {"question_id": question_id},
        ).mappings().first()
        if review is None:
            raise HTTPException(
                status_code=409,
                detail="No pending difficulty classification review exists.",
            )

        metadata = question["source_metadata"]
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except json.JSONDecodeError:
                metadata = None
        source_traceable = bool(
            question["source_question_number"] is not None
            or (
                isinstance(metadata, dict)
                and any(
                    value is not None and value != ""
                    for value in metadata.values()
                )
            )
        )
        if not source_traceable:
            raise HTTPException(
                status_code=422,
                detail="Question source traceability is required for classification.",
            )

        if payload.decision == "APPROVE":
            errors = question_governance_service.validate_question_for_publication(
                connection, question_id
            )
            difficulty_error = (
                "Question difficulty must be sourced or reviewed as EASY, MEDIUM, or HARD."
            )
            blocking_errors = [error for error in errors if error != difficulty_error]
            if blocking_errors:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "message": "Question has unresolved publication errors.",
                        "errors": blocking_errors,
                    },
                )
            connection.execute(
                text("""
                    UPDATE questions
                    SET difficulty = :difficulty
                    WHERE question_id = :question_id
                """),
                {"difficulty": payload.difficulty, "question_id": question_id},
            )
            errors = question_governance_service.validate_question_for_publication(
                connection, question_id
            )
            if errors:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "message": "Question failed publication validation.",
                        "errors": errors,
                    },
                )

        connection.execute(
            text("""
                UPDATE question_reviews
                SET reviewer_id = :reviewer_id,
                    decision = :decision,
                    notes = CONCAT(
                        COALESCE(notes, ''),
                        '\\nREVIEW_DECISION:', :decision,
                        '\\nREVIEW_NOTES:', :reviewer_notes
                    ),
                    reviewed_at = CURRENT_TIMESTAMP
                WHERE review_id = :review_id
            """),
            {
                "reviewer_id": current_user["user_id"],
                "decision": payload.decision,
                "reviewer_notes": payload.reviewer_notes,
                "review_id": review["review_id"],
            },
        )
        if payload.decision == "REJECT":
            question_governance_service.transition_question_status(
                connection,
                question_id,
                "REJECTED",
                current_user["user_id"],
                note=payload.reviewer_notes,
            )
        return {
            "question_id": question_id,
            "decision": payload.decision,
            "difficulty": payload.difficulty if payload.decision == "APPROVE" else None,
            "status": (
                "REJECTED" if payload.decision == "REJECT" else "REVIEW"
            ),
            "publication_ready": payload.decision == "APPROVE",
        }


@router.post("/blueprints")
def create_blueprint(
    payload: BlueprintCreate,
    current_user: dict = Depends(require_admin),
):
    with engine.begin() as connection:
        _validate_foreign_reference(
            connection, "companies", "company_id", payload.company_id, "Company"
        )
        _validate_blueprint_track(connection, payload.track_id)
        duplicate_version = connection.execute(
            text("""
                SELECT blueprint_id
                FROM test_blueprints
                WHERE company_id = :company_id
                  AND program_name = :program_name
                  AND pattern_version = :pattern_version
                LIMIT 1
            """),
            {
                "company_id": payload.company_id,
                "program_name": payload.program_name,
                "pattern_version": payload.pattern_version,
            },
        ).scalar_one_or_none()
        if duplicate_version is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "DUPLICATE_PATTERN_VERSION",
                    "message": (
                        "A pattern version already exists for this company and program."
                    ),
                    "blueprint_id": int(duplicate_version),
                },
            )
        values = payload.model_dump()
        values["pattern_details"] = (
            json.dumps(values["pattern_details"])
            if values["pattern_details"] is not None
            else None
        )
        result = connection.execute(
            text("""
                INSERT INTO test_blueprints (
                    company_id, blueprint_name, track_id, duration_seconds,
                    description, program_name, pattern_version, effective_from,
                    effective_to, source_name, source_url, source_type,
                    source_published_at, source_accessed_at, source_notes,
                    pattern_details, verification_status, verification_notes,
                    status, created_by, updated_by
                )
                VALUES (
                    :company_id, :blueprint_name, :track_id, :duration_seconds,
                    :description, :program_name, :pattern_version, :effective_from,
                    :effective_to, :source_name, :source_url, :source_type,
                    :source_published_at, :source_accessed_at, :source_notes,
                    :pattern_details, :verification_status, :verification_notes,
                    'DRAFT', :created_by, :updated_by
                )
            """),
            {
                **values,
                "created_by": current_user["user_id"],
                "updated_by": current_user["user_id"],
            },
        )
        blueprint_id = result.lastrowid
        return blueprint_service.get_blueprint(connection, blueprint_id)


@router.get("/blueprints")
def list_blueprints(
    status: Optional[str] = Query(default=None),
):
    statuses = {"DRAFT", "ACTIVE", "INACTIVE", "ARCHIVED"}
    if status is not None and status not in statuses:
        raise HTTPException(status_code=400, detail="Unsupported blueprint status.")
    with engine.connect() as connection:
        rows = connection.execute(
            text("""
                SELECT blueprint_id, company_id, blueprint_name, program_name,
                       pattern_version, effective_from, effective_to,
                       source_name, source_url, source_type, source_published_at,
                       source_accessed_at, source_notes, pattern_details,
                       verification_status, verification_notes, activated_at,
                       track_id, duration_seconds, description, status,
                       created_by, updated_by, updated_at
                FROM test_blueprints
                WHERE (:status IS NULL OR status = :status)
                ORDER BY blueprint_id
            """),
            {"status": status},
        ).mappings().all()
        return [dict(row) for row in rows]


@router.get("/blueprints/{blueprint_id}")
def get_blueprint(blueprint_id: int):
    with engine.connect() as connection:
        return blueprint_service.get_blueprint(connection, blueprint_id)


@router.get("/blueprints/{blueprint_id}/preview")
def preview_blueprint(blueprint_id: int):
    with engine.connect() as connection:
        return blueprint_service.preview_blueprint(connection, blueprint_id)


@router.post("/blueprints/{blueprint_id}/rules")
def create_blueprint_rule(
    blueprint_id: int,
    payload: BlueprintRuleCreate,
):
    with engine.begin() as connection:
        blueprint = blueprint_service.get_blueprint(
            connection, blueprint_id, lock=True
        )
        if blueprint["status"] == "ARCHIVED":
            raise HTTPException(status_code=409, detail="Archived blueprints are immutable.")
        rule = payload.model_dump()
        _ensure_blueprint_version_mutable(blueprint)
        errors = blueprint_service.validate_rule_references(
            connection, blueprint, rule
        )
        if errors:
            raise HTTPException(
                status_code=422,
                detail={"message": "Blueprint rule is invalid.", "errors": errors},
            )
        total = sum(item["question_count"] for item in blueprint["rules"])
        if total + payload.question_count > blueprint_service.MAX_BLUEPRINT_QUESTIONS:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Blueprints may request at most "
                    f"{blueprint_service.MAX_BLUEPRINT_QUESTIONS} questions."
                ),
            )
        duplicate_section = connection.execute(
            text("""
                SELECT blueprint_rule_id
                FROM test_blueprint_rules
                WHERE blueprint_id = :blueprint_id
                  AND (
                    section_order = :section_order
                    OR LOWER(TRIM(section_name)) = LOWER(TRIM(:section_name))
                  )
                LIMIT 1
            """),
            {
                "blueprint_id": blueprint_id,
                "section_order": payload.section_order,
                "section_name": payload.section_name or "",
            },
        ).scalar_one_or_none()
        if duplicate_section is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "DUPLICATE_SECTION",
                    "message": "Section names and section orders must be unique.",
                },
            )
        connection.execute(
            text("""
                INSERT INTO test_blueprint_rules (
                    blueprint_id, section_name, section_order, is_required,
                    time_allocation_seconds, selection_strategy,
                    minimum_difficulty, maximum_difficulty,
                    track_id, topic_id, subtopic_id, question_type, difficulty,
                    question_count, selection_weight, points
                )
                VALUES (
                    :blueprint_id, :section_name, :section_order, :is_required,
                    :time_allocation_seconds, :selection_strategy,
                    :minimum_difficulty, :maximum_difficulty,
                    :track_id, :topic_id, :subtopic_id, :question_type, :difficulty,
                    :question_count, :selection_weight, :points
                )
            """),
            {"blueprint_id": blueprint_id, **rule},
        )
        _ensure_active_blueprint_remains_valid(connection, blueprint_id)
        return blueprint_service.get_blueprint(connection, blueprint_id)


@router.put("/blueprints/{blueprint_id}")
def update_blueprint(
    blueprint_id: int,
    payload: BlueprintUpdate,
    current_user: dict = Depends(require_admin),
):
    values = payload.model_dump(exclude_unset=True)
    if not values:
        raise HTTPException(status_code=400, detail="No blueprint fields supplied.")
    if any(values.get(key) is None for key in ("blueprint_name", "status") if key in values):
        raise HTTPException(
            status_code=422,
            detail="blueprint_name and status cannot be null.",
        )
    with engine.begin() as connection:
        blueprint = blueprint_service.get_blueprint(
            connection, blueprint_id, lock=True
        )
        if blueprint["status"] == "ARCHIVED":
            raise HTTPException(status_code=409, detail="Archived blueprints are immutable.")
        if blueprint.get("activated_at") is not None:
            changed_pattern_fields = set(values) - {"status"}
            if changed_pattern_fields:
                _ensure_blueprint_version_mutable(blueprint)
            if values.get("status") not in {"ACTIVE", "INACTIVE", "ARCHIVED"}:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "IMMUTABLE_PATTERN_VERSION",
                        "message": (
                            "An activated pattern version may only be deactivated "
                            "or archived; create a new version to edit its pattern."
                        ),
                    },
                )
        _validate_foreign_reference(
            connection,
            "companies",
            "company_id",
            values.get("company_id", blueprint["company_id"]),
            "Company",
        )
        _validate_blueprint_track(
            connection, values.get("track_id", blueprint["track_id"])
        )
        version_identity = (
            values.get("company_id", blueprint["company_id"]),
            values.get("program_name", blueprint["program_name"]),
            values.get("pattern_version", blueprint["pattern_version"]),
        )
        if all(value is not None for value in version_identity):
            conflict = connection.execute(
                text("""
                    SELECT blueprint_id
                    FROM test_blueprints
                    WHERE company_id = :company_id
                      AND program_name = :program_name
                      AND pattern_version = :pattern_version
                      AND blueprint_id <> :blueprint_id
                    LIMIT 1
                """),
                {
                    "company_id": version_identity[0],
                    "program_name": version_identity[1],
                    "pattern_version": version_identity[2],
                    "blueprint_id": blueprint_id,
                },
            ).scalar_one_or_none()
            if conflict is not None:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "DUPLICATE_PATTERN_VERSION",
                        "message": (
                            "A pattern version already exists for this company "
                            "and program."
                        ),
                        "blueprint_id": int(conflict),
                    },
                )
        if "pattern_details" in values:
            values["pattern_details"] = (
                json.dumps(values["pattern_details"])
                if values["pattern_details"] is not None
                else None
            )
        assignments = [f"{column} = :{column}" for column in values]
        assignments.extend(["updated_by = :updated_by"])
        values["updated_by"] = current_user["user_id"]
        values["blueprint_id"] = blueprint_id
        connection.execute(
            text(f"""
                UPDATE test_blueprints
                SET {", ".join(assignments)}
                WHERE blueprint_id = :blueprint_id
            """),
            values,
        )
        if values.get("status") == "ACTIVE":
            connection.execute(
                text("""
                    UPDATE test_blueprints
                    SET activated_at = COALESCE(activated_at, CURRENT_TIMESTAMP)
                    WHERE blueprint_id = :blueprint_id
                """),
                {"blueprint_id": blueprint_id},
            )
        if values.get("status") == "ACTIVE" or blueprint["status"] == "ACTIVE":
            _ensure_active_blueprint_remains_valid(connection, blueprint_id)
        return blueprint_service.get_blueprint(connection, blueprint_id)


@router.post("/blueprints/{blueprint_id}/activate")
def activate_blueprint(
    blueprint_id: int,
    current_user: dict = Depends(require_admin),
):
    with engine.begin() as connection:
        blueprint = blueprint_service.get_blueprint(
            connection, blueprint_id, lock=True
        )
        if blueprint["status"] == "ARCHIVED":
            raise HTTPException(
                status_code=409,
                detail="Archived blueprints cannot be activated.",
            )
        connection.execute(
            text("""
                UPDATE test_blueprints
                SET status = 'ACTIVE',
                    activated_at = COALESCE(activated_at, CURRENT_TIMESTAMP),
                    updated_by = :updated_by
                WHERE blueprint_id = :blueprint_id
            """),
            {
                "blueprint_id": blueprint_id,
                "updated_by": current_user["user_id"],
            },
        )
        _ensure_active_blueprint_remains_valid(connection, blueprint_id)
        return blueprint_service.get_blueprint(connection, blueprint_id)


@router.put("/blueprints/{blueprint_id}/rules/{rule_id}")
def update_blueprint_rule(
    blueprint_id: int,
    rule_id: int,
    payload: BlueprintRuleUpdate,
):
    values = payload.model_dump(exclude_unset=True)
    if not values:
        raise HTTPException(status_code=400, detail="No rule fields supplied.")
    if any(
        values.get(key) is None
        for key in ("question_count", "points", "selection_weight")
        if key in values
    ):
        raise HTTPException(
            status_code=422,
            detail="question_count, points, and selection_weight cannot be null.",
        )
    with engine.begin() as connection:
        blueprint = blueprint_service.get_blueprint(
            connection, blueprint_id, lock=True
        )
        _ensure_blueprint_version_mutable(blueprint)
        if blueprint["status"] == "ARCHIVED":
            raise HTTPException(status_code=409, detail="Archived blueprints are immutable.")
        existing = connection.execute(
            text("""
                SELECT blueprint_rule_id, track_id, topic_id, subtopic_id,
                       question_type,
                       difficulty, question_count, selection_weight, points,
                       section_name, section_order, is_required,
                       time_allocation_seconds, selection_strategy, minimum_difficulty,
                       maximum_difficulty
                FROM test_blueprint_rules
                WHERE blueprint_id = :blueprint_id
                  AND blueprint_rule_id = :rule_id
                FOR UPDATE
            """),
            {"blueprint_id": blueprint_id, "rule_id": rule_id},
        ).mappings().first()
        if existing is None:
            raise HTTPException(status_code=404, detail="Blueprint rule not found.")
        proposed = {**dict(existing), **values}
        errors = blueprint_service.validate_rule_references(
            connection, blueprint, proposed
        )
        if errors:
            raise HTTPException(
                status_code=422,
                detail={"message": "Blueprint rule is invalid.", "errors": errors},
            )
        all_rules = blueprint["rules"]
        total = sum(
            int(rule["question_count"])
            + (
                int(values["question_count"]) - int(existing["question_count"])
                if rule["blueprint_rule_id"] == rule_id
                and "question_count" in values
                else 0
            )
            for rule in all_rules
        )
        if total > blueprint_service.MAX_BLUEPRINT_QUESTIONS:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Blueprints may request at most "
                    f"{blueprint_service.MAX_BLUEPRINT_QUESTIONS} questions."
                ),
            )
        duplicate_section = connection.execute(
            text("""
                SELECT blueprint_rule_id
                FROM test_blueprint_rules
                WHERE blueprint_id = :blueprint_id
                  AND blueprint_rule_id <> :rule_id
                  AND (
                    (:section_order IS NOT NULL AND section_order = :section_order)
                    OR (
                      :section_name IS NOT NULL
                      AND LOWER(TRIM(section_name)) = LOWER(TRIM(:section_name))
                    )
                  )
                LIMIT 1
            """),
            {
                "blueprint_id": blueprint_id,
                "rule_id": rule_id,
                "section_order": proposed.get("section_order"),
                "section_name": proposed.get("section_name"),
            },
        ).scalar_one_or_none()
        if duplicate_section is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "DUPLICATE_SECTION",
                    "message": "Section names and section orders must be unique.",
                },
            )
        assignments = [f"{column} = :{column}" for column in values]
        values.update({"blueprint_id": blueprint_id, "rule_id": rule_id})
        connection.execute(
            text(f"""
                UPDATE test_blueprint_rules
                SET {", ".join(assignments)}
                WHERE blueprint_id = :blueprint_id
                  AND blueprint_rule_id = :rule_id
            """),
            values,
        )
        _ensure_active_blueprint_remains_valid(connection, blueprint_id)
        return blueprint_service.get_blueprint(connection, blueprint_id)


@router.get("/blueprints/{blueprint_id}/validation")
@router.post("/blueprints/{blueprint_id}/validate")
def validate_blueprint(blueprint_id: int):
    with engine.connect() as connection:
        errors = blueprint_service.validate_blueprint(connection, blueprint_id)
        return {"blueprint_id": blueprint_id, "valid": not errors, "errors": errors}
