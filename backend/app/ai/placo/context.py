"""Build explicit Placo context while enforcing attempt ownership and safety."""

from fastapi import HTTPException
from sqlalchemy import text

from app.services import attempt_service


def build_context(
    connection,
    user_id: int,
    question_id: int | None,
    attempt_id: int | None,
) -> dict:
    if attempt_id is not None and question_id is None:
        raise HTTPException(
            status_code=422,
            detail="question_id is required when attempt_id is supplied.",
        )

    attempt = None
    if attempt_id is not None:
        attempt = attempt_service.get_attempt_detail(connection, attempt_id)
        if int(attempt["user_id"]) != user_id:
            raise HTTPException(
                status_code=403,
                detail="You do not have permission to use this attempt.",
            )
        belongs = connection.execute(
            text("""
                SELECT EXISTS (
                    SELECT 1
                    FROM mock_test_questions
                    WHERE mock_test_id = :mock_test_id
                      AND question_id = :question_id
                )
            """),
            {
                "mock_test_id": attempt["mock_test_id"],
                "question_id": question_id,
            },
        ).scalar_one()
        if not belongs:
            raise HTTPException(
                status_code=422,
                detail="Question does not belong to the supplied attempt.",
            )
        mode = connection.execute(
            text("SELECT mode FROM mock_tests WHERE mock_test_id = :mock_test_id"),
            {"mock_test_id": attempt["mock_test_id"]},
        ).scalar_one()
        attempt["mode"] = mode
    elif question_id is not None:
        active_attempt_id = connection.execute(
            text("""
                SELECT a.attempt_id
                FROM attempts a
                JOIN mock_test_questions mtq
                  ON mtq.mock_test_id = a.mock_test_id
                WHERE a.user_id = :user_id
                  AND mtq.question_id = :question_id
                  AND a.status = 'IN_PROGRESS'
                ORDER BY a.started_at DESC, a.attempt_id DESC
                LIMIT 1
            """),
            {"user_id": user_id, "question_id": question_id},
        ).scalar_one_or_none()
        if active_attempt_id is not None:
            active = attempt_service.get_attempt_detail(
                connection, int(active_attempt_id)
            )
            if active["status"] == "IN_PROGRESS":
                mode = connection.execute(
                    text("SELECT mode FROM mock_tests WHERE mock_test_id = :mock_test_id"),
                    {"mock_test_id": active["mock_test_id"]},
                ).scalar_one()
                attempt = {**active, "mode": mode}

    question = None
    if question_id is not None:
        question = connection.execute(
            text("""
                SELECT q.question_id, q.question_type, q.difficulty,
                       mq.question_text, mq.explanation AS mcq_explanation,
                       mq.correct_option_key, cq.problem_statement,
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
                WHERE q.question_id = :question_id
            """),
            {"question_id": question_id},
        ).mappings().first()
        if question is None:
            raise HTTPException(status_code=404, detail="Question not found.")

    answer_locked = bool(attempt and attempt["status"] != "SUBMITTED")
    context = {
        "assessment_state": (
            "ACTIVE_ASSESSMENT"
            if answer_locked
            else "PRACTICE"
            if attempt is None or attempt.get("mode") == "PRACTICE"
            else "COMPLETED"
        ),
        "question_id": question_id,
    }
    if question is None:
        return context

    context.update({
        "question_type": question["question_type"],
        "topic": question["topic_name"],
        "subtopic": question["subtopic_name"],
        "difficulty": question["difficulty"],
    })
    if answer_locked:
        return context

    context["question_text"] = (
        question["question_text"]
        if question["question_type"] == "MCQ"
        else question["problem_statement"]
    )
    if question["question_type"] == "MCQ":
        options = connection.execute(
            text("""
                SELECT option_key, option_text
                FROM mcq_options
                WHERE question_id = :question_id
                ORDER BY display_order, option_id
            """),
            {"question_id": question_id},
        ).mappings().all()
        context["options"] = [
            {"key": row["option_key"], "text": row["option_text"]}
            for row in options
        ]
        context["correct_option_key"] = question["correct_option_key"]
        context["answer_key_available"] = question["correct_option_key"] is not None
        context["stored_explanation"] = question["mcq_explanation"]
    else:
        context["coding_reference_solution"] = None
        context["hidden_test_cases"] = None

    if attempt is not None:
        answer = connection.execute(
            text("""
                SELECT selected_option_key, answer_text, is_correct
                FROM attempt_answers
                WHERE attempt_id = :attempt_id
                  AND question_id = :question_id
            """),
            {"attempt_id": attempt_id or attempt["attempt_id"], "question_id": question_id},
        ).mappings().first()
        if answer is not None:
            context["student_answer"] = (
                answer["selected_option_key"] or answer["answer_text"]
            )
            if attempt["status"] != "IN_PROGRESS":
                context["answer_was_correct"] = answer["is_correct"]
    return context
