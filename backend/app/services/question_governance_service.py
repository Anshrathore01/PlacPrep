from fastapi import HTTPException
from sqlalchemy import text


QUESTION_STATUSES = {"DRAFT", "REVIEW", "PUBLISHED", "REJECTED", "ARCHIVED"}
RECONSTRUCTION_REVIEW_PREFIX = "MCQ_RECONSTRUCTION_IMPORT:v1:"


def validate_question_for_publication(connection, question_id: int) -> list[str]:
    question = connection.execute(
        text("""
            SELECT q.question_id, q.question_type, q.source_id, q.track_id,
                   q.difficulty, q.content_hash,
                   s.source_id AS existing_source
            FROM questions q
            LEFT JOIN sources s ON s.source_id = q.source_id
            WHERE q.question_id = :question_id
        """),
        {"question_id": question_id},
    ).mappings().first()
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")

    errors = []
    if question["existing_source"] is None:
        errors.append("Question source does not exist.")

    has_classification = connection.execute(
        text("""
            SELECT EXISTS (
                SELECT 1
                FROM question_subtopics qs
                JOIN subtopics st ON st.subtopic_id = qs.subtopic_id
                JOIN topics t ON t.topic_id = st.topic_id
                WHERE qs.question_id = :question_id
                  AND t.track_id = :track_id
            )
        """),
        {"question_id": question_id, "track_id": question["track_id"]},
    ).scalar_one()
    if not has_classification:
        errors.append("Question must have a subtopic in its track.")
    has_inconsistent_classification = connection.execute(
        text("""
            SELECT EXISTS (
                SELECT 1
                FROM question_subtopics qs
                JOIN subtopics st ON st.subtopic_id = qs.subtopic_id
                JOIN topics t ON t.topic_id = st.topic_id
                WHERE qs.question_id = :question_id
                  AND t.track_id <> :track_id
            )
        """),
        {"question_id": question_id, "track_id": question["track_id"]},
    ).scalar_one()
    if has_inconsistent_classification:
        errors.append("Every question subtopic must belong to its question track.")

    if question["difficulty"] not in {"EASY", "MEDIUM", "HARD"}:
        errors.append(
            "Question difficulty must be sourced or reviewed as EASY, MEDIUM, or HARD."
        )

    if question["question_type"] == "MCQ":
        mcq = connection.execute(
            text("""
                SELECT question_text, correct_option_key, is_multiple_correct
                FROM mcq_questions
                WHERE question_id = :question_id
            """),
            {"question_id": question_id},
        ).mappings().first()
        if mcq is None:
            errors.append("MCQ content is missing.")
            return errors

        if not (mcq["question_text"] or "").strip():
            errors.append("Question text is required.")
        if mcq["is_multiple_correct"]:
            errors.append("Multiple-correct MCQs are not supported by the scorer.")
        options = connection.execute(
            text("""
                SELECT option_key, option_text
                FROM mcq_options
                WHERE question_id = :question_id
            """),
            {"question_id": question_id},
        ).mappings().all()
        if len(options) not in (4, 5):
            errors.append("MCQs must have exactly 4 or 5 options.")
        if any(not (option["option_text"] or "").strip() for option in options):
            errors.append("Every MCQ option must have non-empty text.")
        non_empty_option_texts = [
            option["option_text"].strip().casefold()
            for option in options
            if (option["option_text"] or "").strip()
        ]
        if len(non_empty_option_texts) != len(set(non_empty_option_texts)):
            errors.append("MCQ options must have unique text.")
        option_keys = [
            option["option_key"]
            for option in options
            if option["option_key"] is not None
        ]
        if len(option_keys) != len(set(option_keys)):
            errors.append("MCQ option keys must be unique.")
        if not mcq["correct_option_key"]:
            errors.append("A correct option is required.")
        elif not any(
            option["option_key"] == mcq["correct_option_key"]
            for option in options
        ):
            errors.append("The correct option key must match an existing option.")

        duplicate_question = connection.execute(
            text("""
                SELECT q.question_id
                FROM questions q
                JOIN mcq_questions other_mcq
                  ON other_mcq.question_id = q.question_id
                WHERE q.question_id <> :question_id
                  AND (
                    q.content_hash = :content_hash
                    OR (
                      LOWER(TRIM(other_mcq.question_text))
                        = LOWER(TRIM(:question_text))
                      AND TRIM(COALESCE(:question_text, '')) <> ''
                    )
                  )
                LIMIT 1
            """),
            {
                "question_id": question_id,
                "content_hash": question["content_hash"],
                "question_text": mcq["question_text"],
            },
        ).scalar_one_or_none()
        if duplicate_question is not None:
            errors.append(
                f"Question duplicates existing question {int(duplicate_question)}."
            )
    elif question["question_type"] == "CODING":
        coding = connection.execute(
            text("""
                SELECT problem_statement, constraints_text, input_format,
                       output_format, starter_code
                FROM coding_questions
                WHERE question_id = :question_id
            """),
            {"question_id": question_id},
        ).mappings().first()
        if coding is None:
            errors.append("Coding content is missing.")
            return errors

        required_fields = {
            "problem statement": coding["problem_statement"],
            "constraints": coding["constraints_text"],
            "input format": coding["input_format"],
            "output format": coding["output_format"],
            "starter code": coding["starter_code"],
        }
        errors.extend(
            f"{label.capitalize()} is required."
            for label, value in required_fields.items()
            if not (value or "").strip()
        )
        examples = connection.execute(
            text("""
                SELECT COUNT(*)
                FROM question_examples
                WHERE question_id = :question_id
                  AND TRIM(COALESCE(input_data, '')) <> ''
                  AND TRIM(COALESCE(output_data, '')) <> ''
            """),
            {"question_id": question_id},
        ).scalar_one()
        if examples < 1:
            errors.append("At least one complete example is required.")
        public_tests = connection.execute(
            text("""
                SELECT COUNT(*)
                FROM coding_test_cases
                WHERE question_id = :question_id AND is_hidden = FALSE
            """),
            {"question_id": question_id},
        ).scalar_one()
        hidden_tests = connection.execute(
            text("""
                SELECT COUNT(*)
                FROM coding_test_cases
                WHERE question_id = :question_id AND is_hidden = TRUE
            """),
            {"question_id": question_id},
        ).scalar_one()
        if public_tests < 1:
            errors.append("At least one public coding test case is required.")
        if hidden_tests < 1:
            errors.append("At least one hidden coding test case is required.")
    else:
        errors.append("Unsupported question type.")

    return errors


def transition_question_status(
    connection,
    question_id: int,
    target_status: str,
    actor_user_id: int,
    note: str | None = None,
) -> dict:
    if target_status not in QUESTION_STATUSES:
        raise HTTPException(status_code=400, detail="Unsupported question status.")

    question = connection.execute(
        text("""
            SELECT question_id, status
            FROM questions
            WHERE question_id = :question_id
            FOR UPDATE
        """),
        {"question_id": question_id},
    ).mappings().first()
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")
    current_status = question["status"]

    allowed = {
        "REVIEW": {"DRAFT"},
        "PUBLISHED": {"REVIEW"},
        "REJECTED": {"DRAFT", "REVIEW"},
        "ARCHIVED": {"DRAFT", "REVIEW", "PUBLISHED", "REJECTED"},
    }
    if current_status not in allowed.get(target_status, set()):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot transition question from {current_status} to {target_status}.",
        )

    if target_status == "PUBLISHED":
        latest_review = connection.execute(
            text("""
                SELECT decision, notes
                FROM question_reviews
                WHERE question_id = :question_id
                ORDER BY COALESCE(reviewed_at, '1000-01-01 00:00:00') DESC,
                         review_id DESC
                LIMIT 1
            """),
            {"question_id": question_id},
        ).mappings().first()
        if (
            latest_review is not None
            and (latest_review["notes"] or "").startswith(
                RECONSTRUCTION_REVIEW_PREFIX
            )
            and latest_review["decision"] != "APPROVE"
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Reconstruction content review must be approved before "
                    "publication."
                ),
            )
        errors = validate_question_for_publication(connection, question_id)
        if errors:
            raise HTTPException(
                status_code=422,
                detail={"message": "Question failed publication validation.", "errors": errors},
            )

    connection.execute(
        text("UPDATE questions SET status = :status WHERE question_id = :question_id"),
        {"status": target_status, "question_id": question_id},
    )
    connection.execute(
        text("""
            INSERT INTO question_status_history (
                question_id, actor_user_id, previous_status, new_status, note
            )
            VALUES (
                :question_id, :actor_user_id, :previous_status, :new_status, :note
            )
        """),
        {
            "question_id": question_id,
            "actor_user_id": actor_user_id,
            "previous_status": current_status,
            "new_status": target_status,
            "note": note,
        },
    )
    return {
        "question_id": question_id,
        "previous_status": current_status,
        "status": target_status,
    }


def decide_reconstruction_mcq_review(
    connection,
    question_id: int,
    decision: str,
    reviewer_id: int,
    notes: str,
) -> dict:
    if decision not in {"APPROVE", "REJECT"}:
        raise HTTPException(status_code=422, detail="Unsupported content review decision.")

    question = connection.execute(
        text("""
            SELECT question_id, question_type, status
            FROM questions
            WHERE question_id = :question_id
            FOR UPDATE
        """),
        {"question_id": question_id},
    ).mappings().first()
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found.")
    if question["question_type"] != "MCQ":
        raise HTTPException(
            status_code=409,
            detail="Reconstruction content review is only available for MCQs.",
        )
    if question["status"] != "REVIEW":
        raise HTTPException(
            status_code=409,
            detail="Reconstruction content review requires a question in REVIEW status.",
        )

    review = connection.execute(
        text("""
            SELECT review_id, decision, notes
            FROM question_reviews
            WHERE question_id = :question_id
            ORDER BY COALESCE(reviewed_at, '1000-01-01 00:00:00') DESC,
                     review_id DESC
            LIMIT 1
            FOR UPDATE
        """),
        {"question_id": question_id},
    ).mappings().first()
    if (
        review is None
        or review["decision"] != "PENDING"
        or not (review["notes"] or "").startswith(RECONSTRUCTION_REVIEW_PREFIX)
    ):
        raise HTTPException(
            status_code=409,
            detail="No pending reconstruction-import content review exists.",
        )

    result = connection.execute(
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
              AND decision = 'PENDING'
        """),
        {
            "reviewer_id": reviewer_id,
            "decision": decision,
            "reviewer_notes": notes,
            "review_id": review["review_id"],
        },
    )
    if result.rowcount != 1:
        raise HTTPException(
            status_code=409,
            detail="The reconstruction content review was already decided.",
        )

    status = "REVIEW"
    if decision == "REJECT":
        transition_question_status(
            connection,
            question_id,
            "REJECTED",
            reviewer_id,
            note=notes,
        )
        status = "REJECTED"

    return {
        "question_id": question_id,
        "review_id": int(review["review_id"]),
        "decision": decision,
        "status": status,
        "published": False,
    }
