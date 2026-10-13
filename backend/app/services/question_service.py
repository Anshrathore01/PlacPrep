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

import logging
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import text

from app.services.option_text import canonical_option

logger = logging.getLogger(__name__)


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
