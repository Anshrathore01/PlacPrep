"""Canonical content-based eligibility checks for mock question selection.

Governance, publication, provenance, duplicate, and review metadata remain
available for audit but never gate mock eligibility.
"""

from sqlalchemy import text


MOCK_ELIGIBLE_QUESTION_SQL = """
    q.difficulty IN ('EASY', 'MEDIUM', 'HARD')
    AND (
        (
            q.question_type = 'MCQ'
            AND EXISTS (
                SELECT 1
                FROM mcq_questions mq
                WHERE mq.question_id = q.question_id
                  AND TRIM(COALESCE(mq.question_text, '')) <> ''
                  AND mq.correct_option_key IS NOT NULL
                  AND TRIM(mq.correct_option_key) <> ''
                  AND mq.is_multiple_correct = FALSE
            )
            AND (
                SELECT COUNT(*)
                FROM mcq_options mo
                WHERE mo.question_id = q.question_id
            ) BETWEEN 4 AND 5
            AND NOT EXISTS (
                SELECT 1
                FROM mcq_options mo
                WHERE mo.question_id = q.question_id
                  AND (
                      mo.option_key IS NULL
                      OR mo.option_key NOT IN ('A', 'B', 'C', 'D', 'E')
                      OR TRIM(COALESCE(mo.option_text, '')) = ''
                  )
            )
            AND (
                SELECT COUNT(DISTINCT mo.option_key)
                FROM mcq_options mo
                WHERE mo.question_id = q.question_id
            ) = (
                SELECT COUNT(*)
                FROM mcq_options mo
                WHERE mo.question_id = q.question_id
            )
            AND (
                SELECT COUNT(DISTINCT LOWER(TRIM(mo.option_text)))
                FROM mcq_options mo
                WHERE mo.question_id = q.question_id
            ) = (
                SELECT COUNT(*)
                FROM mcq_options mo
                WHERE mo.question_id = q.question_id
            )
            AND (
                (
                    (SELECT COUNT(*) FROM mcq_options mo
                     WHERE mo.question_id = q.question_id) = 4
                    AND (SELECT COUNT(*) FROM mcq_options mo
                         WHERE mo.question_id = q.question_id
                           AND mo.option_key IN ('A', 'B', 'C', 'D')) = 4
                )
                OR
                (
                    (SELECT COUNT(*) FROM mcq_options mo
                     WHERE mo.question_id = q.question_id) = 5
                    AND (SELECT COUNT(*) FROM mcq_options mo
                         WHERE mo.question_id = q.question_id
                           AND mo.option_key IN ('A', 'B', 'C', 'D', 'E')) = 5
                )
            )
            AND EXISTS (
                SELECT 1
                FROM mcq_questions mq
                JOIN mcq_options correct_opt
                  ON correct_opt.question_id = mq.question_id
                 AND correct_opt.option_key = mq.correct_option_key
                WHERE mq.question_id = q.question_id
                  AND TRIM(COALESCE(correct_opt.option_text, '')) <> ''
            )
        )
        OR
        (
            q.question_type = 'CODING'
            AND EXISTS (
                SELECT 1
                FROM coding_questions cq
                WHERE cq.question_id = q.question_id
                  AND TRIM(COALESCE(cq.problem_statement, '')) <> ''
                  AND TRIM(COALESCE(cq.constraints_text, '')) <> ''
                  AND TRIM(COALESCE(cq.input_format, '')) <> ''
                  AND TRIM(COALESCE(cq.output_format, '')) <> ''
                  AND TRIM(COALESCE(cq.starter_code, '')) <> ''
            )
            AND EXISTS (
                SELECT 1
                FROM question_examples e
                WHERE e.question_id = q.question_id
                  AND TRIM(COALESCE(e.input_data, '')) <> ''
                  AND TRIM(COALESCE(e.output_data, '')) <> ''
            )
            AND EXISTS (
                SELECT 1
                FROM coding_test_cases tc
                WHERE tc.question_id = q.question_id
                  AND tc.is_hidden = FALSE
            )
            AND EXISTS (
                SELECT 1
                FROM coding_test_cases tc
                WHERE tc.question_id = q.question_id
                  AND tc.is_hidden = TRUE
            )
        )
    )
    AND EXISTS (
        SELECT 1
        FROM question_subtopics qs
        JOIN subtopics st ON st.subtopic_id = qs.subtopic_id
        JOIN topics t ON t.topic_id = st.topic_id
        WHERE qs.question_id = q.question_id
          AND t.track_id = q.track_id
    )
    AND NOT EXISTS (
        SELECT 1
        FROM question_subtopics qs
        JOIN subtopics st ON st.subtopic_id = qs.subtopic_id
        JOIN topics t ON t.topic_id = st.topic_id
        WHERE qs.question_id = q.question_id
          AND t.track_id <> q.track_id
    )
"""


def _taxonomy_blockers(connection, question_id: int, track_id: int) -> list[str]:
    blockers = []
    has_matching_topic = connection.execute(
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
        {"question_id": question_id, "track_id": track_id},
    ).scalar_one()
    if not has_matching_topic:
        blockers.append("Question must have a subtopic in its track.")
    has_foreign_topic = connection.execute(
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
        {"question_id": question_id, "track_id": track_id},
    ).scalar_one()
    if has_foreign_topic:
        blockers.append("Every question subtopic must belong to its question track.")
    return blockers


def _mcq_blockers(connection, question_id: int, mcq: dict) -> list[str]:
    blockers = []
    if mcq["question_text"] is None or not str(mcq["question_text"]).strip():
        blockers.append("Question text is required.")
    if mcq["is_multiple_correct"]:
        blockers.append("Multiple-correct MCQs are not supported by the scorer.")

    options = connection.execute(
        text("""
            SELECT option_key, option_text
            FROM mcq_options
            WHERE question_id = :question_id
            ORDER BY display_order, option_id
        """),
        {"question_id": question_id},
    ).mappings().all()
    if len(options) not in (4, 5):
        blockers.append("MCQs must have exactly 4 or 5 options.")
    if any(not (option["option_text"] or "").strip() for option in options):
        blockers.append("Every MCQ option must have non-empty text.")
    keys = [option["option_key"] for option in options]
    if any(key not in {"A", "B", "C", "D", "E"} for key in keys):
        blockers.append("MCQ option keys must be A, B, C, D, or E.")
    if len(keys) != len(set(keys)):
        blockers.append("MCQ option keys must be unique.")
    if len(options) == 4 and set(keys) != {"A", "B", "C", "D"}:
        blockers.append("Four-option MCQs must use option keys A through D.")
    if len(options) == 5 and set(keys) != {"A", "B", "C", "D", "E"}:
        blockers.append("Five-option MCQs must use option keys A through E.")
    option_texts = [
        (option["option_text"] or "").strip().casefold()
        for option in options
        if (option["option_text"] or "").strip()
    ]
    if len(option_texts) != len(set(option_texts)):
        blockers.append("MCQ options must have unique text.")
    correct_key = mcq["correct_option_key"]
    if not correct_key or not str(correct_key).strip():
        blockers.append("A correct option is required.")
    elif not any(
        option["option_key"] == correct_key
        and (option["option_text"] or "").strip()
        for option in options
    ):
        blockers.append("The correct option key must match an existing option.")
    return blockers


def _coding_blockers(connection, question_id: int) -> list[str]:
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
        return ["Coding content is missing."]
    blockers = [
        f"{label} is required."
        for label, value in (
            ("Problem statement", coding["problem_statement"]),
            ("Constraints", coding["constraints_text"]),
            ("Input format", coding["input_format"]),
            ("Output format", coding["output_format"]),
            ("Starter code", coding["starter_code"]),
        )
        if not (value or "").strip()
    ]
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
        blockers.append("At least one complete example is required.")
    for hidden, label in ((False, "public"), (True, "hidden")):
        count = connection.execute(
            text("""
                SELECT COUNT(*)
                FROM coding_test_cases
                WHERE question_id = :question_id
                  AND is_hidden = :is_hidden
            """),
            {"question_id": question_id, "is_hidden": hidden},
        ).scalar_one()
        if count < 1:
            blockers.append(f"At least one {label} coding test case is required.")
    return blockers


def evaluate_mock_eligibility(connection, question_id: int) -> dict:
    """Return content eligibility and concrete content blockers."""
    question = connection.execute(
        text("""
            SELECT q.question_id, q.question_type, q.difficulty, q.track_id,
                   mq.question_text, mq.explanation, mq.correct_option_key,
                   mq.is_multiple_correct
            FROM questions q
            LEFT JOIN mcq_questions mq ON mq.question_id = q.question_id
            WHERE q.question_id = :question_id
        """),
        {"question_id": question_id},
    ).mappings().first()
    if question is None:
        return {
            "question_id": question_id,
            "eligible": False,
            "blockers": ["Question does not exist."],
        }

    blockers = []
    if question["difficulty"] not in {"EASY", "MEDIUM", "HARD"}:
        blockers.append("Question difficulty is missing or invalid.")
    if question["question_type"] == "MCQ":
        if question["question_text"] is None and question["explanation"] is None:
            blockers.append("MCQ content is missing.")
        else:
            blockers.extend(
                _mcq_blockers(connection, question_id, dict(question))
            )
    elif question["question_type"] == "CODING":
        blockers.extend(_coding_blockers(connection, question_id))
    else:
        blockers.append("Unsupported question type.")
    blockers.extend(
        _taxonomy_blockers(connection, question_id, int(question["track_id"]))
    )
    blockers = list(dict.fromkeys(blockers))
    return {
        "question_id": question_id,
        "eligible": not blockers,
        "blockers": blockers,
    }


def is_mock_eligible(connection, question_id: int) -> bool:
    """Return whether a question passes the canonical content eligibility gate."""
    return bool(evaluate_mock_eligibility(connection, question_id)["eligible"])


def count_mock_eligible(connection, question_type: str | None = None) -> int:
    """Count questions accepted by the shared selection predicate."""
    type_filter = ""
    params = {}
    if question_type is not None:
        type_filter = "AND q.question_type = :question_type"
        params["question_type"] = question_type
    return int(
        connection.execute(
            text(f"""
                SELECT COUNT(*)
                FROM questions q
                WHERE ({MOCK_ELIGIBLE_QUESTION_SQL})
                  {type_filter}
            """),
            params,
        ).scalar_one()
    )
