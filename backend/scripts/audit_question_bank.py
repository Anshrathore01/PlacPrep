"""Read-only audit of question-bank structure, taxonomy, duplicates and governance."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import engine
from app.services import blueprint_service, question_governance_service


ISSUE_CODES = {
    "MISSING_SOURCE",
    "MISSING_SOURCE_TRACEABILITY",
    "MISSING_OPTIONS",
    "INCOMPLETE_OPTIONS",
    "EMPTY_OPTION_TEXT",
    "DUPLICATE_OPTION_KEYS",
    "NULL_ANSWER_KEY",
    "INVALID_ANSWER_KEY",
    "DUPLICATE_OPTIONS",
    "DUPLICATE_CONTENT",
    "MISSING_QUESTION_TEXT",
    "MULTIPLE_CORRECT_UNSUPPORTED",
    "MISSING_SUBTOPIC",
    "INVALID_SUBTOPIC",
    "MISSING_TOPIC",
    "INCONSISTENT_TRACK",
    "MISSING_DIFFICULTY",
    "INVALID_DIFFICULTY",
    "OTHER_GOVERNANCE_ERROR",
}

STRUCTURAL_ISSUES = ISSUE_CODES - {
    "MISSING_SOURCE",
    "MISSING_SOURCE_TRACEABILITY",
    "MISSING_DIFFICULTY",
    "INVALID_DIFFICULTY",
}


def normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").casefold()).strip()


def incomplete_option_question_count(option_counts: dict[int, int]) -> int:
    return sum(
        question_count
        for option_count, question_count in option_counts.items()
        if option_count not in (0, 4, 5)
    )


def has_source_traceability(
    *,
    source_id: int | None,
    source_name: str | None,
    source_question_number: int | None,
    source_metadata,
) -> bool:
    if not source_id or not source_name:
        return False
    if source_question_number is not None:
        return True
    if isinstance(source_metadata, str):
        try:
            source_metadata = json.loads(source_metadata)
        except json.JSONDecodeError:
            return False
    return bool(
        isinstance(source_metadata, dict)
        and any(value is not None and value != "" for value in source_metadata.values())
    )


def classify_mcq_issues(
    *,
    question_text: str | None,
    correct_option_key: str | None,
    is_multiple_correct: bool,
    difficulty: str | None,
    options: list[dict],
    mappings: list[dict],
    duplicate_content: bool = False,
) -> list[str]:
    issues = set()
    if difficulty is None:
        issues.add("MISSING_DIFFICULTY")
    elif difficulty not in {"EASY", "MEDIUM", "HARD"}:
        issues.add("INVALID_DIFFICULTY")
    if not options:
        issues.add("MISSING_OPTIONS")
    elif len(options) not in (4, 5):
        issues.add("INCOMPLETE_OPTIONS")
    if any(not normalize_text(option.get("option_text")) for option in options):
        issues.add("EMPTY_OPTION_TEXT")
    option_keys = [
        str(option.get("option_key"))
        for option in options
        if option.get("option_key") is not None
    ]
    if len(option_keys) != len(set(option_keys)):
        issues.add("DUPLICATE_OPTION_KEYS")

    if correct_option_key is None or not str(correct_option_key).strip():
        issues.add("NULL_ANSWER_KEY")
    elif not any(option.get("option_key") == correct_option_key for option in options):
        issues.add("INVALID_ANSWER_KEY")

    normalized_options = [
        normalize_text(option.get("option_text"))
        for option in options
        if normalize_text(option.get("option_text"))
    ]
    if len(normalized_options) != len(set(normalized_options)):
        issues.add("DUPLICATE_OPTIONS")
    if duplicate_content:
        issues.add("DUPLICATE_CONTENT")

    if not mappings:
        issues.add("MISSING_SUBTOPIC")
    else:
        if any(mapping.get("subtopic_id") is None for mapping in mappings):
            issues.add("INVALID_SUBTOPIC")
        if any(
            mapping.get("subtopic_id") is not None
            and mapping.get("topic_id") is None
            for mapping in mappings
        ):
            issues.add("MISSING_TOPIC")
        if any(
            mapping.get("track_id") is None
            or mapping.get("question_track_id") != mapping.get("track_id")
            for mapping in mappings
            if mapping.get("subtopic_id") is not None
        ):
            issues.add("INCONSISTENT_TRACK")

    if not normalize_text(question_text):
        issues.add("MISSING_QUESTION_TEXT")
    if is_multiple_correct:
        issues.add("MULTIPLE_CORRECT_UNSUPPORTED")
    return sorted(issues)


def _governance_issue_code(error: str) -> str:
    normalized = error.casefold()
    if "difficulty" in normalized:
        return "MISSING_DIFFICULTY" if "sourced or reviewed" in normalized else "INVALID_DIFFICULTY"
    if "source does not exist" in normalized:
        return "MISSING_SOURCE"
    if "every question subtopic" in normalized:
        return "INCONSISTENT_TRACK"
    if "subtopic" in normalized:
        return "MISSING_SUBTOPIC" if "must have" in normalized else "INVALID_SUBTOPIC"
    if "track" in normalized:
        return "INCONSISTENT_TRACK"
    if "topic" in normalized:
        return "MISSING_TOPIC"
    if "question text" in normalized:
        return "MISSING_QUESTION_TEXT"
    if "option" in normalized and "unique text" in normalized:
        return "DUPLICATE_OPTIONS"
    if "option" in normalized and "exactly 4 or 5" in normalized:
        return "INCOMPLETE_OPTIONS"
    if "option" in normalized and "non-empty" in normalized:
        return "EMPTY_OPTION_TEXT"
    if "correct option" in normalized and "required" in normalized:
        return "NULL_ANSWER_KEY"
    if "correct option key" in normalized:
        return "INVALID_ANSWER_KEY"
    if "duplicates existing question" in normalized:
        return "DUPLICATE_CONTENT"
    if "multiple-correct" in normalized:
        return "MULTIPLE_CORRECT_UNSUPPORTED"
    return "OTHER_GOVERNANCE_ERROR"


def _duplicate_keys(rows: list[dict], key) -> set[int]:
    groups: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        value = key(row)
        if value:
            groups[value].append(int(row["question_id"]))
    return {
        question_id
        for question_ids in groups.values()
        if len(question_ids) > 1
        for question_id in question_ids
    }


def audit() -> dict:
    with engine.connect() as connection:
        questions = connection.execute(
            text("""
                SELECT q.question_id, q.source_id, s.source_name, s.source_type,
                       s.source_url, q.source_question_number, q.source_metadata,
                       q.question_type,
                       q.track_id AS question_track_id, tr.track_name,
                       q.title, q.difficulty, q.status, q.content_hash,
                       mq.question_text, mq.correct_option_key,
                       mq.is_multiple_correct
                FROM questions q
                LEFT JOIN sources s ON s.source_id = q.source_id
                LEFT JOIN tracks tr ON tr.track_id = q.track_id
                LEFT JOIN mcq_questions mq ON mq.question_id = q.question_id
                ORDER BY q.question_id
            """)
        ).mappings().all()
        options_by_question: dict[int, list[dict]] = defaultdict(list)
        for row in connection.execute(
            text("""
                SELECT question_id, option_key, option_text, display_order
                FROM mcq_options
                ORDER BY question_id, display_order
            """)
        ).mappings():
            options_by_question[int(row["question_id"])].append(dict(row))

        mappings_by_question: dict[int, list[dict]] = defaultdict(list)
        for row in connection.execute(
            text("""
                SELECT qs.question_id, qs.subtopic_id,
                       st.subtopic_id AS existing_subtopic_id,
                       st.topic_id, t.topic_id AS existing_topic_id,
                       t.track_id, q.track_id AS question_track_id
                FROM question_subtopics qs
                JOIN questions q ON q.question_id = qs.question_id
                LEFT JOIN subtopics st ON st.subtopic_id = qs.subtopic_id
                LEFT JOIN topics t ON t.topic_id = st.topic_id
                ORDER BY qs.question_id, qs.subtopic_id
            """)
        ).mappings():
            mappings_by_question[int(row["question_id"])].append(
                {
                    "subtopic_id": row["existing_subtopic_id"],
                    "topic_id": row["existing_topic_id"],
                    "track_id": row["track_id"],
                    "question_track_id": row["question_track_id"],
                }
            )

        mcq_rows = [
            dict(row)
            for row in questions
            if row["question_type"] == "MCQ"
        ]
        duplicate_hash_ids = _duplicate_keys(
            mcq_rows,
            lambda row: normalize_text(row.get("content_hash")),
        )
        duplicate_text_ids = _duplicate_keys(
            mcq_rows,
            lambda row: normalize_text(row.get("question_text")),
        )
        duplicate_ids = duplicate_hash_ids | duplicate_text_ids

        results = []
        issue_counts: Counter[str] = Counter({issue: 0 for issue in ISSUE_CODES})
        status_counts: Counter[str] = Counter()
        type_counts: Counter[str] = Counter()
        source_counts: dict[str, Counter[str]] = defaultdict(Counter)
        option_counts: Counter[int] = Counter()
        valid_by_track: Counter[tuple[str, str]] = Counter()

        for row in questions:
            question_id = int(row["question_id"])
            status_counts[str(row["status"] or "UNKNOWN")] += 1
            type_counts[str(row["question_type"] or "UNKNOWN")] += 1
            source_name = row["source_name"] or "MISSING_SOURCE"
            source_counts[source_name][str(row["status"] or "UNKNOWN")] += 1
            options = options_by_question.get(question_id, [])
            if row["question_type"] == "MCQ":
                option_counts[len(options)] += 1
            mappings = mappings_by_question.get(question_id, [])
            structural_issues = set()
            if row["question_type"] == "MCQ":
                structural_issues.update(
                    classify_mcq_issues(
                        question_text=row["question_text"],
                        correct_option_key=row["correct_option_key"],
                        is_multiple_correct=bool(row["is_multiple_correct"]),
                        difficulty=row["difficulty"],
                        options=options,
                        mappings=mappings,
                        duplicate_content=question_id in duplicate_ids,
                    )
                )
            else:
                if not mappings:
                    structural_issues.add("MISSING_SUBTOPIC")
                else:
                    if any(mapping.get("subtopic_id") is None for mapping in mappings):
                        structural_issues.add("INVALID_SUBTOPIC")
                    if any(
                        mapping.get("subtopic_id") is not None
                        and mapping.get("topic_id") is None
                        for mapping in mappings
                    ):
                        structural_issues.add("MISSING_TOPIC")
                    if any(
                        mapping.get("track_id") is None
                        or row["question_track_id"] != mapping.get("track_id")
                        for mapping in mappings
                        if mapping.get("subtopic_id") is not None
                    ):
                        structural_issues.add("INCONSISTENT_TRACK")

            governance_errors = (
                question_governance_service.validate_question_for_publication(
                    connection, question_id
                )
            )
            if question_id in duplicate_ids:
                structural_issues.add("DUPLICATE_CONTENT")
            governance_issue_codes = (
                {_governance_issue_code(error) for error in governance_errors}
                if row["question_type"] != "MCQ"
                else set()
            )
            if row["question_type"] != "MCQ":
                structural_issues.update(
                    code for code in governance_issue_codes if code in STRUCTURAL_ISSUES
                )
            issues = sorted(structural_issues | governance_issue_codes)
            source_metadata = row["source_metadata"]
            has_source_trace = has_source_traceability(
                source_id=row["source_id"],
                source_name=row["source_name"],
                source_question_number=row["source_question_number"],
                source_metadata=source_metadata,
            )
            readiness_errors = list(governance_errors)
            if question_id in duplicate_ids and not any(
                _governance_issue_code(error) == "DUPLICATE_CONTENT"
                for error in governance_errors
            ):
                readiness_errors.append("Question is part of a duplicate-content group.")
            if not has_source_trace:
                issues.append("MISSING_SOURCE_TRACEABILITY")
                readiness_errors.append("Question source traceability is incomplete.")
            issues = sorted(set(issues))
            structural_valid = not (structural_issues & STRUCTURAL_ISSUES)
            governance_ready = not governance_errors and question_id not in duplicate_ids
            publish_ready = governance_ready and has_source_trace
            for issue in issues:
                issue_counts[issue] += 1
            if publish_ready:
                issue_counts["PUBLISH_READY"] += 1
                valid_by_track[
                    (
                        row["track_name"] or "MISSING_TRACK",
                        row["question_type"],
                    )
                ] += 1
            results.append(
                {
                    "question_id": question_id,
                    "source_id": row["source_id"],
                    "source_name": source_name,
                    "source_type": row["source_type"],
                    "source_url": row["source_url"],
                    "source_question_number": row["source_question_number"],
                    "source_metadata": source_metadata,
                    "question_type": row["question_type"],
                    "track_id": row["question_track_id"],
                    "track_name": row["track_name"],
                    "difficulty": row["difficulty"],
                    "status": row["status"],
                    "content_hash": row["content_hash"],
                    "option_count": len(options) if row["question_type"] == "MCQ" else None,
                    "correct_option_key": row["correct_option_key"],
                    "mapping": mappings,
                    "issues": issues,
                    "structural_valid": structural_valid,
                    "governance_ready": governance_ready,
                    "publish_ready": publish_ready,
                    "governance_errors": governance_errors,
                    "readiness_errors": readiness_errors,
                }
            )

        topic_counts = connection.execute(
            text("""
                SELECT t.topic_id, t.topic_name, q.question_type, q.status,
                       COUNT(DISTINCT q.question_id) AS question_count
                FROM questions q
                JOIN question_subtopics qs ON qs.question_id = q.question_id
                JOIN subtopics st ON st.subtopic_id = qs.subtopic_id
                JOIN topics t ON t.topic_id = st.topic_id
                GROUP BY t.topic_id, t.topic_name, q.question_type, q.status
                ORDER BY t.topic_id, q.question_type, q.status
            """)
        ).mappings().all()
        subtopic_counts = connection.execute(
            text("""
                SELECT st.subtopic_id, st.subtopic_name, t.topic_id,
                       t.topic_name, q.question_type, q.status,
                       COUNT(DISTINCT q.question_id) AS question_count
                FROM questions q
                JOIN question_subtopics qs ON qs.question_id = q.question_id
                JOIN subtopics st ON st.subtopic_id = qs.subtopic_id
                JOIN topics t ON t.topic_id = st.topic_id
                GROUP BY st.subtopic_id, st.subtopic_name, t.topic_id,
                         t.topic_name, q.question_type, q.status
                ORDER BY t.topic_id, st.subtopic_id, q.question_type, q.status
            """)
        ).mappings().all()
        published_eligible = connection.execute(
            text(f"""
                SELECT q.question_type, COUNT(DISTINCT q.question_id) AS n
                FROM questions q
                WHERE {blueprint_service.ELIGIBLE_QUESTION_SQL}
                GROUP BY q.question_type
            """)
        ).mappings().all()
        company_readiness = []
        blueprints = connection.execute(
            text("""
                SELECT b.blueprint_id, b.company_id, c.company_name,
                       b.program_name, b.pattern_version, b.status,
                       b.verification_status, b.duration_seconds
                FROM test_blueprints b
                LEFT JOIN companies c ON c.company_id = b.company_id
                WHERE b.company_id IS NOT NULL
                ORDER BY c.company_name, b.program_name, b.pattern_version
            """)
        ).mappings().all()
        for blueprint in blueprints:
            preview = blueprint_service.preview_blueprint(
                connection, int(blueprint["blueprint_id"])
            )
            company_readiness.append(
                {
                    **dict(blueprint),
                    "ready_for_mock": preview["ready_for_mock"],
                    "sections": preview["rules"],
                    "problems": preview["errors"],
                }
            )

    normalized_text_counts = Counter(
        normalize_text(row["question_text"])
        for row in mcq_rows
        if normalize_text(row["question_text"])
    )
    content_hash_counts = Counter(
        row["content_hash"] for row in mcq_rows if row["content_hash"]
    )
    duplicate_groups = {
        "normalized_question_text": sum(
            count > 1 for count in normalized_text_counts.values()
        ),
        "content_hash": sum(
            count > 1 for count in content_hash_counts.values()
        ),
    }
    return {
        "read_only": True,
        "question_total": len(questions),
        "counts": {
            "questions_by_status": dict(sorted(status_counts.items())),
            "questions_by_type": dict(sorted(type_counts.items())),
            "structurally_valid_questions": sum(
                bool(row["structural_valid"]) for row in results
            ),
            "structurally_valid_by_type": {
                question_type: sum(
                    row["question_type"] == question_type
                    and row["structural_valid"]
                    for row in results
                )
                for question_type in sorted(type_counts)
            },
            "governance_ready_questions": sum(
                bool(row["governance_ready"]) for row in results
            ),
            "publish_ready_questions": sum(
                bool(row["publish_ready"]) for row in results
            ),
            "publish_ready_by_type": {
                question_type: sum(
                    row["question_type"] == question_type and row["publish_ready"]
                    for row in results
                )
                for question_type in sorted(type_counts)
            },
            "valid_mcq_count": sum(
                row["question_type"] == "MCQ" and row["structural_valid"]
                for row in results
            ),
            "publish_ready_mcq_count": sum(
                row["question_type"] == "MCQ" and row["publish_ready"]
                for row in results
            ),
            "published_with_governance_errors": sum(
                row["status"] == "PUBLISHED" and not row["governance_ready"]
                for row in results
            ),
            "mcq_option_count": dict(
                sorted(option_counts.items())
            ),
            "mcqs_with_incomplete_options": incomplete_option_question_count(
                option_counts
            ),
            "valid_questions_by_track": {
                f"{track} / {question_type}": count
                for (track, question_type), count in sorted(valid_by_track.items())
            },
            "mcq_null_answer_key": issue_counts["NULL_ANSWER_KEY"],
            "mcq_invalid_answer_key": issue_counts["INVALID_ANSWER_KEY"],
            "missing_difficulty": issue_counts["MISSING_DIFFICULTY"],
            "invalid_difficulty": issue_counts["INVALID_DIFFICULTY"],
            "duplicate_option_questions": issue_counts["DUPLICATE_OPTIONS"],
            "duplicate_content_question_ids": issue_counts["DUPLICATE_CONTENT"],
            "duplicate_content_groups": duplicate_groups,
            "published_eligible_by_type": {
                row["question_type"]: int(row["n"])
                for row in published_eligible
            },
            "issue_counts": dict(sorted(issue_counts.items())),
            "question_status_by_source": {
                source: dict(sorted(counts.items()))
                for source, counts in sorted(source_counts.items())
            },
        },
        "published_by_topic": [dict(row) for row in topic_counts if row["status"] == "PUBLISHED"],
        "published_by_subtopic": [dict(row) for row in subtopic_counts if row["status"] == "PUBLISHED"],
        "published_coding_by_topic": [
            dict(row)
            for row in topic_counts
            if row["status"] == "PUBLISHED"
            and row["question_type"] == "CODING"
        ],
        "company_blueprint_readiness": company_readiness,
        "questions": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        help="Write JSON to this file instead of stdout.",
    )
    args = parser.parse_args()
    report = audit()
    rendered = json.dumps(report, indent=2, default=str)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
        print(
            json.dumps(
                {
                    "output": str(args.output),
                    "question_total": report["question_total"],
                    "issues": report["counts"]["issue_counts"],
                },
                indent=2,
            )
        )
    else:
        print(rendered)


if __name__ == "__main__":
    main()
