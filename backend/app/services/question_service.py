"""
Question Service — Phase 3
==========================

Provides student-facing question detail assembly.

SECURITY CONTRACT
-----------------
Functions in this module NEVER include the following fields in their output:
  - correct_option_key
  - solution_pseudocode
  - solution_explanation
  - hidden test cases / expected hidden outputs
  - internal review data

If the schema ever adds those fields, they must be explicitly excluded here.
"""

import json
import logging
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import bindparam, text

from app.services.option_text import canonical_option

logger = logging.getLogger(__name__)


def get_question_details_student(conn, question_ids: list[int]) -> list[dict]:
    """Load several student-safe question details with a bounded query count."""
    question_ids = list(question_ids)
    if not question_ids:
        return []

    ids_param = bindparam("question_ids", expanding=True)
    base_rows = conn.execute(
        text("""
            SELECT
                q.question_id,
                q.title,
                q.question_type,
                q.difficulty,
                q.status,
                q.source_metadata
            FROM questions q
            WHERE q.question_id IN :question_ids
        """).bindparams(ids_param),
        {"question_ids": question_ids},
    ).mappings().all()
    questions_by_id = {int(row["question_id"]): dict(row) for row in base_rows}

    mcq_ids = [
        question_id
        for question_id in question_ids
        if question_id in questions_by_id
        and questions_by_id[question_id]["question_type"] == "MCQ"
    ]
    mcqs_by_id = {}
    options_by_question = {}
    if mcq_ids:
        mcq_rows = conn.execute(
            text("""
                SELECT question_id, question_text, is_multiple_correct
                FROM mcq_questions
                WHERE question_id IN :question_ids
            """).bindparams(ids_param),
            {"question_ids": mcq_ids},
        ).mappings().all()
        mcqs_by_id = {int(row["question_id"]): dict(row) for row in mcq_rows}

        option_rows = conn.execute(
            text("""
                SELECT
                    question_id,
                    option_id,
                    option_key,
                    option_text,
                    display_order
                FROM mcq_options
                WHERE question_id IN :question_ids
                ORDER BY question_id, display_order
            """).bindparams(ids_param),
            {"question_ids": mcq_ids},
        ).mappings().all()
        for row in option_rows:
            options_by_question.setdefault(int(row["question_id"]), []).append(
                canonical_option(dict(row))
            )

    coding_ids = [
        question_id
        for question_id in question_ids
        if question_id in questions_by_id
        and questions_by_id[question_id]["question_type"] == "CODING"
    ]
    coding_by_id = {}
    examples_by_question = {}
    if coding_ids:
        coding_rows = conn.execute(
            text("""
                SELECT
                    question_id,
                    problem_statement,
                    constraints_text,
                    input_format,
                    output_format,
                    starter_code,
                    solution_pseudocode,
                    solution_explanation
                FROM coding_questions
                WHERE question_id IN :question_ids
            """).bindparams(ids_param),
            {"question_ids": coding_ids},
        ).mappings().all()
        coding_by_id = {int(row["question_id"]): dict(row) for row in coding_rows}

        example_rows = conn.execute(
            text("""
                SELECT
                    question_id,
                    example_number,
                    input_data,
                    output_data,
                    explanation
                FROM question_examples
                WHERE question_id IN :question_ids
                ORDER BY question_id, example_number
            """).bindparams(ids_param),
            {"question_ids": coding_ids},
        ).mappings().all()
        for row in example_rows:
            example = dict(row)
            example.pop("question_id")
            examples_by_question.setdefault(int(row["question_id"]), []).append(example)

    result = []
    for question_id in question_ids:
        base = questions_by_id.get(question_id)
        if base is None:
            raise HTTPException(status_code=404, detail=f"Question {question_id} not found")

        question = dict(base)
        metadata = {}
        if question.get("source_metadata"):
            try:
                raw_meta = question["source_metadata"]
                metadata = json.loads(raw_meta) if isinstance(raw_meta, str) else dict(raw_meta)
            except Exception:
                metadata = {}

        if question["question_type"] == "MCQ":
            mcq = mcqs_by_id.get(question_id)
            if mcq is None:
                raise HTTPException(
                    status_code=500,
                    detail="MCQ content is missing for this question",
                )
            result.append({
                **question,
                "section": metadata.get("section"),
                "passage": metadata.get("passage"),
                "question_text": mcq["question_text"],
                "is_multiple_correct": bool(mcq["is_multiple_correct"]),
                "options": options_by_question.get(question_id, []),
            })
        elif question["question_type"] == "CODING":
            coding = coding_by_id.get(question_id)
            if coding is None:
                raise HTTPException(
                    status_code=500,
                    detail="Coding content is missing for this question",
                )
            coding = dict(coding)
            coding.pop("question_id")
            result.append({
                **question,
                "section": metadata.get("section"),
                **coding,
                "examples": examples_by_question.get(question_id, []),
            })
        else:
            raise HTTPException(
                status_code=500,
                detail=f"Unsupported question type: {question['question_type']}",
            )

    return result


def get_question_detail_student(
    conn,
    question_id: int,
    include_correct_key: bool = False,
) -> dict:
    """
    Return student-facing question detail (no answer keys by default).

    Pass include_correct_key=True ONLY for internal scoring use — never
    include the key in a response returned to the client.
    """
    base_row = conn.execute(
        text("""
            SELECT
                q.question_id,
                q.title,
                q.question_type,
                q.difficulty,
                q.status,
                q.source_metadata
            FROM questions q
            WHERE q.question_id = :question_id
        """),
        {"question_id": question_id},
    ).mappings().first()

    if base_row is None:
        raise HTTPException(
            status_code=404,
            detail=f"Question {question_id} not found",
        )

    question = dict(base_row)
    metadata = {}
    if question.get("source_metadata"):
        try:
            raw_meta = question["source_metadata"]
            metadata = __import__("json").loads(raw_meta) if isinstance(raw_meta, str) else dict(raw_meta)
        except Exception:
            metadata = {}

    if question["question_type"] == "MCQ":
        mcq_cols = "question_text, is_multiple_correct"
        if include_correct_key:
            mcq_cols += ", correct_option_key"

        mcq = conn.execute(
            text(f"""
                SELECT {mcq_cols}
                FROM mcq_questions
                WHERE question_id = :question_id
            """),
            {"question_id": question_id},
        ).mappings().first()

        if mcq is None:
            raise HTTPException(
                status_code=500,
                detail="MCQ content is missing for this question",
            )

        options = conn.execute(
            text("""
                SELECT
                    option_id,
                    option_key,
                    option_text,
                    display_order
                FROM mcq_options
                WHERE question_id = :question_id
                ORDER BY display_order
            """),
            {"question_id": question_id},
        ).mappings().all()

        return {
            **question,
            "section":           metadata.get("section"),
            "passage":           metadata.get("passage"),
            "question_text":     mcq["question_text"],
            "is_multiple_correct": bool(mcq["is_multiple_correct"]),
            "options":           [canonical_option(dict(x)) for x in options],
        }

    if question["question_type"] == "CODING":
        coding = conn.execute(
            text("""
                SELECT
                    problem_statement,
                    constraints_text,
                    input_format,
                    output_format,
                    starter_code,
                    solution_pseudocode,
                    solution_explanation
                FROM coding_questions
                WHERE question_id = :question_id
            """),
            {"question_id": question_id},
        ).mappings().first()

        if coding is None:
            raise HTTPException(
                status_code=500,
                detail="Coding content is missing for this question",
            )

        examples = conn.execute(
            text("""
                SELECT
                    example_number,
                    input_data,
                    output_data,
                    explanation
                FROM question_examples
                WHERE question_id = :question_id
                ORDER BY example_number
            """),
            {"question_id": question_id},
        ).mappings().all()

        return {
            **question,
            "section": metadata.get("section"),
            **dict(coding),
            "examples": [dict(x) for x in examples],
        }

    raise HTTPException(
        status_code=500,
        detail=f"Unsupported question type: {question['question_type']}",
    )
