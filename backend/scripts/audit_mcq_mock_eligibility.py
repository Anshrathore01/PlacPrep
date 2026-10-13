"""Audit MCQ mock eligibility and queue unsafe target questions for review."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import engine
from app.services import blueprint_service, question_governance_service
from app.services.mock_eligibility_service import (
    MOCK_ELIGIBLE_QUESTION_SQL,
    is_mock_eligible,
)


BACKEND = Path(__file__).resolve().parents[1]
REPORTS = BACKEND / "reports"
BEFORE_JSON = REPORTS / "mcq_mock_eligibility_before.json"
BEFORE_CSV = REPORTS / "mcq_mock_eligibility_before.csv"
AFTER_JSON = REPORTS / "mcq_mock_eligibility_after.json"
AFTER_CSV = REPORTS / "mcq_mock_eligibility_after.csv"
REVIEW_CSV = REPORTS / "mcq_mock_eligibility_review_queue.csv"
SUMMARY_MD = REPORTS / "mcq_mock_eligibility_summary.md"
REVIEW_MARKER = "MCQ_MOCK_ELIGIBILITY_REVIEW:v1:"
REVIEWER_ID = 7
EXPECTED_MCQ_TOTAL = 1917
EXPECTED_TARGET_COUNTS = {
    "Quantitative Aptitude": 456,
    "Logical Reasoning": 654,
    "Verbal Ability": 341,
    "Technical": 230,
}
TARGET_CATEGORIES = tuple(EXPECTED_TARGET_COUNTS)
SNAPSHOT_TABLES = (
    "questions",
    "mcq_questions",
    "mcq_options",
    "coding_questions",
    "question_examples",
    "coding_test_cases",
    "question_reviews",
    "question_status_history",
    "question_subtopics",
    "question_tags",
    "sources",
    "tracks",
    "topics",
    "subtopics",
    "tags",
    "duplicate_matches",
    "question_reports",
    "attempts",
    "attempt_answers",
    "mock_tests",
    "mock_test_questions",
    "coding_submissions",
)
CSV_FIELDS = (
    "question_id",
    "category",
    "source_id",
    "source_name",
    "source_type",
    "source_authorization_status",
    "source_question_number",
    "title",
    "topic",
    "subtopic",
    "difficulty",
    "status",
    "question_text",
    "option_count",
    "option_keys",
    "correct_option_key",
    "correct_key_exists",
    "explanation_present",
    "source_present",
    "duplicate_group",
    "governance_errors",
    "eligible_before_repair",
    "eligible_after_repair",
    "classification",
    "blocker_reason",
    "proposed_action",
)


def _json_default(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def _decode_json(value: Any) -> Any:
    if value is None or isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return value


def _normalize(value: str | None) -> str:
    return " ".join((value or "").casefold().split())


def _has_source_traceability(row: dict) -> bool:
    metadata = _decode_json(row.get("source_metadata"))
    return row.get("source_question_number") is not None or bool(metadata)


def _authorization_status(row: dict) -> str:
    if not row.get("source_present"):
        return "SOURCE_MISSING"
    if row.get("source_type") == "SCRAPED":
        notes = (row.get("source_notes") or "").casefold()
        has_evidence = any(
            marker in notes
            for marker in (
                "authorization_status=authorized",
                "authorization_status=licensed",
                "authorization_status=public_domain",
                "authorization_status=permission_granted",
            )
        )
        return "EVIDENCE_RECORDED" if has_evidence else "NOT_RECORDED"
    if row.get("source_type") == "CUSTOM":
        return "USER_PROVIDED_SOURCE; RIGHTS_NOT_INDEPENDENTLY_ATTESTED"
    return "NOT_RECORDED"


def _category(row: dict, mappings: list[dict]) -> str:
    primary = next(
        (
            mapping
            for mapping in sorted(
                mappings,
                key=lambda item: (
                    not bool(item.get("is_primary")),
                    int(item.get("subtopic_id") or 0),
                ),
            )
            if mapping.get("topic_name") is not None
        ),
        None,
    )
    if row.get("track_name") == "Technical" or int(row.get("track_id") or 0) == 2:
        return "Technical"
    if primary is not None:
        topic_name = primary["topic_name"]
        if topic_name in TARGET_CATEGORIES:
            return topic_name
        if topic_name == "Data Interpretation":
            return "OUT_OF_SCOPE: Data Interpretation"
    return "OUT_OF_SCOPE: Other"


def _load_bank(connection) -> tuple[str | None, list[dict], dict]:
    database = connection.execute(text("SELECT DATABASE()")).scalar_one_or_none()
    rows = [
        dict(row)
        for row in connection.execute(
            text("""
                SELECT q.question_id, q.source_id, q.source_question_number,
                       q.source_metadata, q.question_type, q.track_id,
                       tr.track_name, q.title, q.difficulty, q.status,
                       q.content_hash, s.source_name, s.source_type,
                       s.source_url, s.source_notes,
                       mq.question_text, mq.explanation,
                       mq.correct_option_key, mq.is_multiple_correct
                FROM questions q
                LEFT JOIN tracks tr ON tr.track_id = q.track_id
                LEFT JOIN sources s ON s.source_id = q.source_id
                LEFT JOIN mcq_questions mq ON mq.question_id = q.question_id
                WHERE q.question_type = 'MCQ'
                ORDER BY q.question_id
            """)
        ).mappings()
    ]
    options_by_id: dict[int, list[dict]] = defaultdict(list)
    for option in connection.execute(
        text("""
            SELECT question_id, option_key, option_text, display_order
            FROM mcq_options
            ORDER BY question_id, display_order, option_id
        """)
    ).mappings():
        options_by_id[int(option["question_id"])].append(dict(option))

    mappings_by_id: dict[int, list[dict]] = defaultdict(list)
    for mapping in connection.execute(
        text("""
            SELECT qs.question_id, qs.subtopic_id, qs.is_primary,
                   st.subtopic_name, st.topic_id, t.topic_name, t.track_id
            FROM question_subtopics qs
            LEFT JOIN subtopics st ON st.subtopic_id = qs.subtopic_id
            LEFT JOIN topics t ON t.topic_id = st.topic_id
            JOIN questions q ON q.question_id = qs.question_id
            WHERE q.question_type = 'MCQ'
            ORDER BY qs.question_id, qs.is_primary DESC, qs.subtopic_id
        """)
    ).mappings():
        mappings_by_id[int(mapping["question_id"])].append(dict(mapping))

    review_rows = connection.execute(
        text("""
            SELECT question_id, review_id, decision, notes, reviewed_at
            FROM question_reviews
            WHERE question_id IN (
                SELECT question_id FROM questions WHERE question_type = 'MCQ'
            )
            ORDER BY question_id, review_id
        """)
    ).mappings().all()
    latest_review_by_id = {}
    review_count_by_id = Counter()
    for review in review_rows:
        question_id = int(review["question_id"])
        review_count_by_id[question_id] += 1
        previous = latest_review_by_id.get(question_id)
        review_key = (
            review["reviewed_at"] or datetime.min,
            int(review["review_id"]),
        )
        if previous is None or review_key > previous[0]:
            latest_review_by_id[question_id] = (review_key, dict(review))

    reports_by_id = defaultdict(list)
    for report in connection.execute(
        text("""
            SELECT question_id, report_id, report_type, details, status
            FROM question_reports
            WHERE status IN ('OPEN', 'IN_REVIEW')
        """)
    ).mappings():
        reports_by_id[int(report["question_id"])].append(dict(report))

    duplicate_matches_by_id = defaultdict(list)
    for match in connection.execute(
        text("""
            SELECT duplicate_match_id, question_id_a, question_id_b,
                   similarity_score, match_type, resolution
            FROM duplicate_matches
            ORDER BY question_id_a, question_id_b
        """)
    ).mappings():
        item = dict(match)
        duplicate_matches_by_id[int(item["question_id_a"])].append(item)
        duplicate_matches_by_id[int(item["question_id_b"])].append(item)

    hash_groups: dict[str, list[int]] = defaultdict(list)
    text_groups: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        if row.get("content_hash"):
            hash_groups[str(row["content_hash"])].append(int(row["question_id"]))
        normalized_text = _normalize(row.get("question_text"))
        if normalized_text:
            text_groups[normalized_text].append(int(row["question_id"]))

    eligible_ids = {
        int(question_id)
        for question_id in connection.execute(
            text(f"""
                SELECT q.question_id
                FROM questions q
                WHERE q.question_type = 'MCQ'
                  AND ({MOCK_ELIGIBLE_QUESTION_SQL})
            """)
        ).scalars()
    }

    records = []
    for row in rows:
        question_id = int(row["question_id"])
        options = options_by_id.get(question_id, [])
        mappings = mappings_by_id.get(question_id, [])
        primary_mapping = next(
            (item for item in mappings if item.get("is_primary")),
            mappings[0] if mappings else None,
        )
        row["options"] = options
        row["mappings"] = mappings
        row["category"] = _category(row, mappings)
        row["topic"] = (
            primary_mapping.get("topic_name") if primary_mapping else None
        )
        row["subtopic"] = (
            primary_mapping.get("subtopic_name") if primary_mapping else None
        )
        row["source_present"] = bool(row.get("source_name"))
        row["source_traceable"] = _has_source_traceability(row)
        row["source_authorization_status"] = _authorization_status(row)
        row["review_count"] = int(review_count_by_id[question_id])
        latest_review = latest_review_by_id.get(question_id)
        row["latest_review"] = latest_review[1] if latest_review else None
        row["open_reports"] = reports_by_id.get(question_id, [])
        row["duplicate_matches"] = duplicate_matches_by_id.get(question_id, [])
        duplicate_groups = []
        for kind, groups, value in (
            ("CONTENT_HASH", hash_groups, row.get("content_hash")),
            ("NORMALIZED_QUESTION_TEXT", text_groups, _normalize(row.get("question_text"))),
        ):
            if value and len(groups[value]) > 1:
                duplicate_groups.append(
                    {"kind": kind, "question_ids": sorted(groups[value])}
                )
        row["duplicate_groups"] = duplicate_groups
        row["duplicate_group"] = (
            duplicate_groups
            or [
                {
                    "kind": match["match_type"],
                    "question_ids": [
                        int(match["question_id_a"]),
                        int(match["question_id_b"]),
                    ],
                    "resolution": match["resolution"],
                }
                for match in row["duplicate_matches"]
            ]
            or None
        )
        governance_errors = question_governance_service.validate_question_for_publication(
            connection, question_id
        )
        row["governance_errors"] = list(governance_errors)

        blockers = list(governance_errors)
        if not (row.get("question_text") or "").strip():
            blockers.append("Question text is empty.")
        if row["difficulty"] not in {"EASY", "MEDIUM", "HARD"}:
            blockers.append("Difficulty is missing or invalid.")
        if not row["source_present"]:
            blockers.append("Source record is missing.")
        if not row["source_traceable"]:
            blockers.append("Source question number/provenance metadata is missing.")
        if row["source_type"] == "SCRAPED" and (
            row["source_authorization_status"] == "NOT_RECORDED"
        ):
            blockers.append(
                "Scraped source has no recorded license/permission evidence."
            )
        option_keys = [option.get("option_key") for option in options]
        non_null_keys = [
            str(key).casefold() for key in option_keys if key is not None
        ]
        if len(options) == 0:
            blockers.append("No options are stored.")
        elif len(options) not in (4, 5):
            blockers.append(f"Unsupported option count: {len(options)}; expected 4 or 5.")
        if any(not (option.get("option_text") or "").strip() for option in options):
            blockers.append("One or more option texts are empty.")
        if any(key is None or not str(key).strip() for key in option_keys):
            blockers.append("One or more option keys are missing.")
        if len(non_null_keys) != len(set(non_null_keys)):
            blockers.append("Option keys are duplicated.")
        normalized_option_texts = [
            _normalize(option.get("option_text"))
            for option in options
            if _normalize(option.get("option_text"))
        ]
        if len(normalized_option_texts) != len(set(normalized_option_texts)):
            blockers.append("Option texts are duplicated.")
        correct_key = row.get("correct_option_key")
        correct_key_exists = any(
            (option.get("option_key") or "").casefold()
            == (correct_key or "").casefold()
            and (option.get("option_text") or "").strip()
            for option in options
        )
        if not correct_key or not str(correct_key).strip():
            blockers.append("Correct answer key is missing.")
        elif not correct_key_exists:
            blockers.append("Correct answer key does not match a stored option.")
        if row.get("is_multiple_correct"):
            blockers.append("Multiple-correct question is unsupported by the scorer.")
        if row["duplicate_groups"]:
            blockers.append("Question belongs to an exact duplicate group.")
        if any(match.get("resolution") == "PENDING" for match in row["duplicate_matches"]):
            blockers.append("Question has unresolved duplicate-match review.")
        if row["open_reports"]:
            blockers.append("Question has one or more open/in-review user reports.")
        if (
            row["latest_review"] is not None
            and row["latest_review"]["decision"] != "APPROVE"
        ):
            blockers.append(
                f"Latest review decision is {row['latest_review']['decision']}."
            )
        if row["status"] == "ARCHIVED":
            blockers.append("Question is ARCHIVED.")
        elif row["status"] != "PUBLISHED":
            blockers.append(
                f"Question is {row['status']}, not PUBLISHED; reviewer approval is pending."
            )
        row["blocker_reason"] = list(dict.fromkeys(blockers))
        row["eligible_before_repair"] = question_id in eligible_ids
        row["eligible_after_repair"] = row["eligible_before_repair"]
        if row["eligible_before_repair"]:
            row["classification"] = "ELIGIBLE"
            row["proposed_action"] = "No change; retain as eligible."
        elif any(
            blocker
            for blocker in row["blocker_reason"]
            if any(
                term in blocker.casefold()
                for term in (
                    "option",
                    "answer key",
                    "correct answer",
                    "question text",
                    "difficulty",
                    "source record",
                    "source question number",
                    "track",
                    "subtopic",
                    "topic",
                    "duplicate",
                    "scraped source",
                )
            )
        ):
            row["classification"] = "BLOCKED"
            row["proposed_action"] = (
                "Keep in governance review; require source-backed human correction "
                "for each listed blocker. Do not infer answers or add options."
            )
        elif row["status"] == "ARCHIVED":
            row["classification"] = "BLOCKED"
            row["proposed_action"] = "Keep archived; do not reactivate automatically."
        else:
            row["classification"] = "NEEDS_REVIEW"
            row["proposed_action"] = (
                "Require authorized reviewer decision through the existing workflow; "
                "do not publish automatically."
            )
        row["option_count"] = len(options)
        row["option_keys"] = option_keys
        row["correct_key_exists"] = correct_key_exists
        row["explanation_present"] = bool((row.get("explanation") or "").strip())
        records.append(row)

    counts = {
        "total_mcq": len(records),
        "target_total": sum(row["category"] in TARGET_CATEGORIES for row in records),
        "eligible_before": sum(
            row["eligible_before_repair"]
            and row["category"] in TARGET_CATEGORIES
            for row in records
        ),
        "eligible_after": sum(
            row["eligible_after_repair"]
            and row["category"] in TARGET_CATEGORIES
            for row in records
        ),
        "repaired": 0,
        "eligible": sum(
            row["classification"] == "ELIGIBLE"
            and row["category"] in TARGET_CATEGORIES
            for row in records
        ),
        "repairable": sum(
            row["classification"] == "REPAIRABLE"
            and row["category"] in TARGET_CATEGORIES
            for row in records
        ),
        "needs_review": sum(
            row["classification"] == "NEEDS_REVIEW"
            and row["category"] in TARGET_CATEGORIES
            for row in records
        ),
        "blocked": sum(
            row["classification"] == "BLOCKED"
            and row["category"] in TARGET_CATEGORIES
            for row in records
        ),
        "by_category": {},
        "issue_counts": Counter(),
    }
    for category in TARGET_CATEGORIES:
        members = [row for row in records if row["category"] == category]
        counts["by_category"][category] = {
            "total": len(members),
            "eligible": sum(row["classification"] == "ELIGIBLE" for row in members),
            "repairable": sum(row["classification"] == "REPAIRABLE" for row in members),
            "needs_review": sum(
                row["classification"] == "NEEDS_REVIEW" for row in members
            ),
            "blocked": sum(row["classification"] == "BLOCKED" for row in members),
        }
    issue_map = {
        "answer_key_problems": (
            "Correct answer key is missing.",
            "Correct answer key does not match a stored option.",
        ),
        "option_problems": (
            "No options are stored.",
            "Unsupported option count:",
            "One or more option texts are empty.",
            "One or more option keys are missing.",
            "Option keys are duplicated.",
            "Option texts are duplicated.",
        ),
        "difficulty_problems": ("Difficulty is missing or invalid.",),
        "topic_problems": (
            "Question must have a subtopic in its track.",
            "Every question subtopic must belong to its question track.",
        ),
        "source_problems": (
            "Source record is missing.",
            "Source question number/provenance metadata is missing.",
            "Scraped source has no recorded license/permission evidence.",
        ),
        "duplicate_problems": (
            "Question belongs to an exact duplicate group.",
            "Question has unresolved duplicate-match review.",
        ),
        "governance_problems": (),
    }
    for row in records:
        if row["category"] not in TARGET_CATEGORIES:
            continue
        blockers = row["blocker_reason"]
        for issue_name, needles in issue_map.items():
            if issue_name == "governance_problems":
                recognized = {
                    "Question source does not exist.",
                    "Question must have a subtopic in its track.",
                    "Every question subtopic must belong to its question track.",
                    "Question difficulty must be sourced or reviewed as EASY, MEDIUM, or HARD.",
                    "Question text is required.",
                    "Multiple-correct MCQs are not supported by the scorer.",
                    "MCQs must have exactly 4 or 5 options.",
                    "Every MCQ option must have non-empty text.",
                    "MCQ options must have unique text.",
                    "MCQ option keys must be unique.",
                    "A correct option is required.",
                    "The correct option key must match an existing option.",
                }
                if any(error in recognized for error in row["governance_errors"]):
                    counts["issue_counts"][issue_name] += 1
            elif any(
                blocker.startswith(needle) if needle.endswith(":") else blocker == needle
                for blocker in blockers
                for needle in needles
            ):
                counts["issue_counts"][issue_name] += 1
        if not row["explanation_present"]:
            counts["issue_counts"]["missing_explanations"] += 1
        if row["status"] != "PUBLISHED":
            counts["issue_counts"]["not_published"] += 1
    counts["issue_counts"] = dict(sorted(counts["issue_counts"].items()))
    category_totals = {
        category: sum(row["category"] == category for row in records)
        for category in TARGET_CATEGORIES
    }
    return database, records, counts, category_totals


def _record_view(row: dict) -> dict:
    return {key: row.get(key) for key in CSV_FIELDS} | {
        "options": row.get("options", []),
        "mappings": row.get("mappings", []),
        "source_url": row.get("source_url"),
        "source_notes": row.get("source_notes"),
        "source_metadata": _decode_json(row.get("source_metadata")),
        "source_traceable": row.get("source_traceable"),
        "latest_review": row.get("latest_review"),
        "open_reports": row.get("open_reports", []),
        "duplicate_matches": row.get("duplicate_matches", []),
        "duplicate_groups": row.get("duplicate_groups", []),
        "is_multiple_correct": bool(row.get("is_multiple_correct")),
        "content_hash": row.get("content_hash"),
    }


def _write_audit(path_json: Path, path_csv: Path, payload: dict) -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    path_json.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default) + "\n",
        encoding="utf-8",
    )
    with path_csv.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in payload["records"]:
            writer.writerow(
                {
                    field: json.dumps(row.get(field), ensure_ascii=False, default=_json_default)
                    if field in {"option_keys", "duplicate_group", "governance_errors", "blocker_reason"}
                    else row.get(field)
                    for field in CSV_FIELDS
                }
            )


def _snapshot_integrity(connection) -> dict:
    counts = {
        table: int(connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one())
        for table in SNAPSHOT_TABLES
    }
    question_ids_hashes = [
        dict(row)
        for row in connection.execute(
            text("""
                SELECT question_id, question_type, content_hash, status,
                       source_id, difficulty, track_id
                FROM questions
                ORDER BY question_id
            """)
        ).mappings()
    ]
    protected_queries = {
        "question_immutable_fields": """
            SELECT question_id, question_type, source_id, source_question_number,
                   source_metadata, track_id, title, difficulty, expected_time_seconds,
                   content_hash
            FROM questions ORDER BY question_id
        """,
        "mcq_content": """
            SELECT question_id, question_text, explanation, correct_option_key,
                   is_multiple_correct
            FROM mcq_questions ORDER BY question_id
        """,
        "mcq_options": """
            SELECT option_id, question_id, option_key, option_text, display_order
            FROM mcq_options ORDER BY option_id
        """,
        "sources": """
            SELECT source_id, source_name, source_type, source_url, source_notes
            FROM sources ORDER BY source_id
        """,
        "taxonomy": """
            SELECT tr.track_id, tr.track_name, t.topic_id, t.topic_name,
                   st.subtopic_id, st.subtopic_name
            FROM tracks tr
            LEFT JOIN topics t ON t.track_id = tr.track_id
            LEFT JOIN subtopics st ON st.topic_id = t.topic_id
            ORDER BY tr.track_id, t.topic_id, st.subtopic_id
        """,
        "question_subtopics": """
            SELECT question_id, subtopic_id, is_primary
            FROM question_subtopics ORDER BY question_id, subtopic_id
        """,
        "question_tags": """
            SELECT question_id, tag_id
            FROM question_tags ORDER BY question_id, tag_id
        """,
        "tags": """
            SELECT tag_id, tag_name
            FROM tags ORDER BY tag_id
        """,
    }
    protected_data_hashes = {}
    for name, query in protected_queries.items():
        rows = [
            dict(row)
            for row in connection.execute(text(query)).mappings()
        ]
        canonical = json.dumps(
            rows,
            ensure_ascii=False,
            sort_keys=True,
            default=_json_default,
            separators=(",", ":"),
        ).encode("utf-8")
        protected_data_hashes[name] = hashlib.sha256(canonical).hexdigest()
    return {
        "counts": counts,
        "question_ids_hashes": question_ids_hashes,
        "protected_data_hashes": protected_data_hashes,
    }


def _make_payload(
    database: str | None,
    records: list[dict],
    counts: dict,
    category_totals: dict,
    integrity: dict,
    *,
    read_only: bool,
) -> dict:
    return {
        "generated_at": datetime.now().astimezone().isoformat(),
        "database": database,
        "read_only": read_only,
        "question_count": len(records),
        "target_categories": list(TARGET_CATEGORIES),
        "category_totals": category_totals,
        "counts": counts,
        "integrity": integrity,
        "records": [_record_view(row) for row in records],
    }


def _repair_signature(row: dict) -> dict:
    return {
        "content_hash": row.get("content_hash"),
        "source_id": row.get("source_id"),
        "source_question_number": row.get("source_question_number"),
        "title": row.get("title"),
        "question_text": row.get("question_text"),
        "correct_option_key": row.get("correct_option_key"),
        "difficulty": row.get("difficulty"),
        "track_id": row.get("track_id"),
        "options": row.get("options"),
        "mappings": row.get("mappings"),
    }


def _apply_review_queue(before: dict, current_audit: dict) -> dict:
    target_rows = [
        row
        for row in before["records"]
        if row["category"] in TARGET_CATEGORIES
        and row["classification"] != "ELIGIBLE"
    ]
    if before["database"] != "placement_platform":
        raise RuntimeError("Refusing to apply review changes to an unexpected database.")
    if len(before["records"]) != EXPECTED_MCQ_TOTAL:
        raise RuntimeError("The before snapshot does not contain all 1,917 MCQs.")
    category_counts = Counter(row["category"] for row in target_rows)
    if dict(
        (category, category_counts.get(category, 0) + before["counts"]["by_category"][category]["eligible"])
        for category in TARGET_CATEGORIES
    ) != EXPECTED_TARGET_COUNTS:
        raise RuntimeError("The target taxonomy totals changed since the audit.")

    with engine.connect() as connection:
        reviewer = connection.execute(
            text("""
                SELECT user_id
                FROM users
                WHERE user_id = :reviewer_id
                  AND role = 'ADMIN'
                  AND is_active = TRUE
            """),
            {"reviewer_id": REVIEWER_ID},
        ).scalar_one_or_none()
        if reviewer is None:
            raise RuntimeError("The designated active administrator is unavailable.")
        live_integrity = _snapshot_integrity(connection)
        existing_markers = int(
            connection.execute(
                text("""
                    SELECT COUNT(*)
                    FROM question_reviews
                    WHERE LEFT(notes, CHAR_LENGTH(:marker)) = :marker
                """),
                {"marker": REVIEW_MARKER},
            ).scalar_one()
        )
        transition_note = (
            "MCQ mock-eligibility audit: human review required; "
            "no answer/content invented."
        )
        existing_transition_events = int(
            connection.execute(
                text("""
                    SELECT COUNT(*)
                    FROM question_status_history
                    WHERE note = :note
                """),
                {"note": transition_note},
            ).scalar_one()
        )
        expected_counts = before["integrity"]["counts"].copy()
        expected_counts["question_reviews"] += existing_markers
        expected_counts["question_status_history"] += existing_transition_events
        if live_integrity["counts"] != expected_counts:
            raise RuntimeError(
                "Live table counts differ from the before snapshot plus this "
                "script's already-committed idempotent review records."
            )
        before_questions = {
            int(row["question_id"]): row
            for row in before["integrity"]["question_ids_hashes"]
        }
        live_questions = {
            int(row["question_id"]): row
            for row in live_integrity["question_ids_hashes"]
        }
        if before_questions.keys() != live_questions.keys():
            raise RuntimeError("Question IDs changed after the before snapshot.")
        for question_id, original in before_questions.items():
            current = live_questions[question_id]
            for field in (
                "question_type",
                "content_hash",
                "source_id",
                "difficulty",
                "track_id",
            ):
                if current[field] != original[field]:
                    raise RuntimeError(
                        f"Question {question_id} field {field} changed since the snapshot."
                    )
            if current["status"] != original["status"]:
                allowed = (
                    question_id in {int(row["question_id"]) for row in target_rows}
                    and original["status"] == "DRAFT"
                    and current["status"] == "REVIEW"
                )
                if not allowed:
                    raise RuntimeError(
                        f"Question {question_id} status changed outside the allowed review flow."
                    )
        baseline_by_id = {
            int(row["question_id"]): row for row in before["records"]
        }
        current_by_id = {
            int(row["question_id"]): row
            for row in current_audit["records"]
        }
        if baseline_by_id.keys() != current_by_id.keys():
            raise RuntimeError("MCQ IDs changed after the before snapshot.")
        immutable_fields = (
            "question_type",
            "source_id",
            "source_name",
            "source_type",
            "source_url",
            "source_notes",
            "source_question_number",
            "source_metadata",
            "title",
            "difficulty",
            "track_id",
            "content_hash",
            "question_text",
            "explanation",
            "correct_option_key",
            "is_multiple_correct",
            "options",
            "mappings",
        )
        for question_id, original in baseline_by_id.items():
            latest = current_by_id[question_id]
            if any(original.get(field) != latest.get(field) for field in immutable_fields):
                raise RuntimeError(
                    f"Question {question_id} content/provenance changed since the snapshot."
                )

    moved_to_review = 0
    reviews_created = 0
    for row in target_rows:
        question_id = int(row["question_id"])
        with engine.begin() as connection:
            current = connection.execute(
                text("""
                    SELECT q.question_type, q.status, q.content_hash,
                           mq.question_text, mq.correct_option_key
                    FROM questions q
                    JOIN mcq_questions mq ON mq.question_id = q.question_id
                    WHERE q.question_id = :question_id
                    FOR UPDATE
                """),
                {"question_id": question_id},
            ).mappings().one_or_none()
            if current is None or current["question_type"] != "MCQ":
                raise RuntimeError(f"Question {question_id} is no longer an MCQ.")
            current_signature = {
                "content_hash": current["content_hash"],
                "question_text": current["question_text"],
                "correct_option_key": current["correct_option_key"],
            }
            expected_signature = {
                key: row.get(key)
                for key in ("content_hash", "question_text", "correct_option_key")
            }
            if current_signature != expected_signature:
                raise RuntimeError(
                    f"Question {question_id} content changed after its audit."
                )
            if current["status"] == "DRAFT":
                question_governance_service.transition_question_status(
                    connection,
                    question_id,
                    "REVIEW",
                    REVIEWER_ID,
                    note=(
                        "MCQ mock-eligibility audit: human review required; "
                        "no answer/content invented."
                    ),
                )
                moved_to_review += 1
            elif current["status"] not in {"REVIEW", "ARCHIVED"}:
                raise RuntimeError(
                    f"Question {question_id} has unexpected status {current['status']}."
                )

            marker = f"{REVIEW_MARKER}{question_id}:"
            has_audit_review = connection.execute(
                text("""
                    SELECT review_id
                    FROM question_reviews
                    WHERE question_id = :question_id
                      AND LEFT(notes, CHAR_LENGTH(:marker)) = :marker
                    LIMIT 1
                """),
                {"question_id": question_id, "marker": marker},
            ).scalar_one_or_none()
            if has_audit_review is None:
                evidence = {
                    "classification": row["classification"],
                    "category": row["category"],
                    "blockers": row["blocker_reason"],
                    "source": {
                        "source_id": row["source_id"],
                        "source_name": row["source_name"],
                        "source_type": row["source_type"],
                        "source_url": row["source_url"],
                        "source_notes": row["source_notes"],
                        "source_question_number": row["source_question_number"],
                        "source_authorization_status": row["source_authorization_status"],
                    },
                    "required_human_action": row["proposed_action"],
                    "content_change": "None. Question text, options, answer, explanation, taxonomy, source, difficulty, and status history are not rewritten.",
                }
                connection.execute(
                    text("""
                        INSERT INTO question_reviews (
                            question_id, reviewer_id, decision, notes
                        )
                        VALUES (:question_id, :reviewer_id, 'PENDING', :notes)
                    """),
                    {
                        "question_id": question_id,
                        "reviewer_id": REVIEWER_ID,
                        "notes": marker + json.dumps(evidence, ensure_ascii=False),
                    },
                )
                reviews_created += 1
    with engine.connect() as connection:
        reviews_total = int(
            connection.execute(
                text("""
                    SELECT COUNT(*)
                    FROM question_reviews
                    WHERE LEFT(notes, CHAR_LENGTH(:marker)) = :marker
                """),
                {"marker": REVIEW_MARKER},
            ).scalar_one()
        )
        history_total = int(
            connection.execute(
                text("""
                    SELECT COUNT(*)
                    FROM question_status_history
                    WHERE note = :note
                """),
                {
                    "note": (
                        "MCQ mock-eligibility audit: human review required; "
                        "no answer/content invented."
                    ),
                },
            ).scalar_one()
        )
    return {
        "target_questions_queued": len(target_rows),
        "questions_moved_from_draft_to_review": history_total,
        "question_specific_review_records_created": reviews_total,
        "questions_moved_this_run": moved_to_review,
        "review_records_created_this_run": reviews_created,
        "questions_published": 0,
        "mcq_content_rows_updated": 0,
        "options_inserted_or_changed": 0,
        "difficulty_values_changed": 0,
    }


def _write_review_queue(records: list[dict]) -> None:
    queue = [
        row
        for row in records
        if row["category"] in TARGET_CATEGORIES
        and row["classification"] != "ELIGIBLE"
    ]
    with REVIEW_CSV.open("w", encoding="utf-8", newline="") as output:
        fields = (
            "question_id",
            "category",
            "source_name",
            "source_type",
            "source_authorization_status",
            "title",
            "topic",
            "subtopic",
            "difficulty",
            "status",
            "correct_option_key",
            "option_count",
            "option_keys",
            "duplicate_group",
            "governance_errors",
            "blocker_reason",
            "proposed_action",
        )
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for row in queue:
            writer.writerow(
                {
                    key: json.dumps(row.get(key), ensure_ascii=False, default=_json_default)
                    if key in {
                        "option_keys",
                        "duplicate_group",
                        "governance_errors",
                        "blocker_reason",
                    }
                    else row.get(key)
                    for key in fields
                }
            )


def _write_summary(before: dict, after: dict, actions: dict) -> None:
    rows = after["records"]
    lines = [
        "# MCQ Mock Eligibility Audit",
        "",
        f"Database: `{after['database']}`",
        f"Generated: {after['generated_at']}",
        "",
        "## Verified outcome",
        "",
        f"- All MCQs individually audited: {len(rows)}",
        f"- Target-category MCQs: {after['counts']['target_total']}",
        f"- Eligible before changes: {before['counts']['eligible_before']}",
        f"- Repaired: {actions.get('repaired', 0)}",
        f"- Eligible after changes: {after['counts']['eligible_after']}",
        f"- Needs review: {after['counts']['needs_review']}",
        f"- Blocked: {after['counts']['blocked']}",
        f"- Review records created: {actions.get('question_specific_review_records_created', 0)}",
        f"- Draft questions moved to REVIEW: {actions.get('questions_moved_from_draft_to_review', 0)}",
        "- Questions published by this task: 0",
        "",
        "## By target category",
        "",
        "| Category | Total | Eligible | Repairable | Needs Review | Blocked |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for category in TARGET_CATEGORIES:
        metric = after["counts"]["by_category"][category]
        lines.append(
            f"| {category} | {metric['total']} | {metric['eligible']} | "
            f"{metric['repairable']} | {metric['needs_review']} | {metric['blocked']} |"
        )
    lines.extend(
        [
            "",
            "Data Interpretation was not included in the target totals. Other unmapped/out-of-scope MCQs remain individually recorded in the JSON/CSV audit.",
            "",
            "## Issue counts (target categories)",
            "",
            "| Issue | Questions |",
            "|---|---:|",
        ]
    )
    lines.extend(
        f"| {issue} | {count} |"
        for issue, count in after["counts"]["issue_counts"].items()
    )
    lines.extend(
        [
            "",
            "## Temporary mock-selector verification",
            "",
            "| Category | Difficulty | Selected | Outcome |",
            "|---|---|---:|---|",
        ]
    )
    lines.extend(
        f"| {item['category']} | {item['difficulty']} | "
        f"{item['selected_count']} | {item['outcome']} |"
        for item in after.get("mock_selection_test", [])
    )
    lines.extend(
        [
            "",
            "All 12 category/difficulty requests used the production selector and canonical eligibility predicate. No mock or attempt rows were created by this temporary test.",
            "",
            "## Non-eligible target question exceptions",
            "",
            "Each listed ID has its exact blockers in the review-queue CSV and question-level JSON record. No answer keys, options, explanations, taxonomy, source, or difficulty values were fabricated or rewritten.",
            "",
            "| Question ID | Category | Final classification | Status | Blockers |",
            "|---:|---|---|---|---|",
        ]
    )
    for row in rows:
        if row["category"] not in TARGET_CATEGORIES or row["classification"] == "ELIGIBLE":
            continue
        escaped = "; ".join(row["blocker_reason"]).replace("|", "\\|")
        lines.append(
            f"| {row['question_id']} | {row['category']} | "
            f"{row['classification']} | {row['status']} | {escaped} |"
        )
    lines.extend(
        [
            "",
            "## Integrity",
            "",
            f"- Question IDs and content hashes unchanged: {after['integrity']['question_ids_hashes_unchanged']}",
            f"- MCQ content/options unchanged: {after['integrity']['question_content_unchanged']}",
            f"- Protected taxonomy/source/tag data unchanged: {after['integrity']['protected_data_unchanged']}",
            f"- Protected historical rows unchanged: {after['integrity']['protected_counts_unchanged']}",
            f"- Only intended status/review tables changed: {after['integrity']['only_review_workflow_changed']}",
            "- MCQ content/options/difficulty were not updated.",
            "- No mock tests, mock assignments, attempts, answers, coding content, or coding submissions were created or deleted.",
        ]
    )
    SUMMARY_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _finalize_integrity(before: dict, after: dict, actions: dict) -> None:
    before_counts = before["integrity"]["counts"]
    after_counts = after["integrity"]["counts"]
    expected = {table: before_counts[table] for table in SNAPSHOT_TABLES}
    expected["question_reviews"] += actions.get(
        "question_specific_review_records_created", 0
    )
    expected["question_status_history"] += actions.get(
        "questions_moved_from_draft_to_review", 0
    )
    after_ids = [
        {key: row[key] for key in ("question_id", "question_type", "content_hash", "source_id", "difficulty", "track_id")}
        for row in after["integrity"]["question_ids_hashes"]
    ]
    before_ids = [
        {key: row[key] for key in ("question_id", "question_type", "content_hash", "source_id", "difficulty", "track_id")}
        for row in before["integrity"]["question_ids_hashes"]
    ]
    ids_unchanged = before_ids == after_ids
    question_before_by_id = {
        int(row["question_id"]): row for row in before["records"]
    }
    question_after_by_id = {
        int(row["question_id"]): row for row in after["records"]
    }
    immutable_record_fields = (
        "question_type",
        "source_id",
        "source_name",
        "source_type",
        "source_url",
        "source_notes",
        "source_question_number",
        "source_metadata",
        "title",
        "topic",
        "subtopic",
        "difficulty",
        "question_text",
        "option_count",
        "option_keys",
        "correct_option_key",
        "correct_key_exists",
        "explanation_present",
        "source_present",
        "duplicate_group",
        "content_hash",
        "is_multiple_correct",
        "options",
        "mappings",
    )
    question_content_unchanged = (
        question_before_by_id.keys() == question_after_by_id.keys()
        and all(
            all(
                question_before_by_id[question_id].get(field)
                == question_after_by_id[question_id].get(field)
                for field in immutable_record_fields
            )
            for question_id in question_before_by_id
        )
    )
    target_ids = {
        int(row["question_id"])
        for row in before["records"]
        if row["category"] in TARGET_CATEGORIES
        and row["classification"] != "ELIGIBLE"
    }
    statuses_as_expected = (
        question_before_by_id.keys() == question_after_by_id.keys()
        and all(
            question_after_by_id[question_id]["status"]
            == (
                "REVIEW"
                if question_id in target_ids
                and question_before_by_id[question_id]["status"] == "DRAFT"
                else question_before_by_id[question_id]["status"]
            )
            for question_id in question_before_by_id
        )
    )
    protected_data_unchanged = (
        before["integrity"]["protected_data_hashes"]
        == after["integrity"]["protected_data_hashes"]
    )
    protected = {
        table
        for table in SNAPSHOT_TABLES
        if table
        not in {"questions", "question_reviews", "question_status_history"}
    }
    protected_counts_unchanged = all(
        before_counts[table] == after_counts[table] for table in protected
    )
    allowed_changes = all(
        after_counts[table] == expected[table] for table in SNAPSHOT_TABLES
    )
    if (
        not ids_unchanged
        or not question_content_unchanged
        or not statuses_as_expected
        or not protected_counts_unchanged
        or not protected_data_unchanged
        or not allowed_changes
    ):
        raise RuntimeError(
            "Database integrity verification failed: "
            f"IDs unchanged={ids_unchanged}, "
            f"MCQ content unchanged={question_content_unchanged}, "
            f"statuses expected={statuses_as_expected}, "
            f"protected counts unchanged={protected_counts_unchanged}, "
            f"protected data unchanged={protected_data_unchanged}, "
            f"allowed deltas={allowed_changes}."
        )
    after["integrity"]["expected_counts_after"] = expected
    after["integrity"]["question_ids_hashes_unchanged"] = ids_unchanged
    after["integrity"]["question_content_unchanged"] = question_content_unchanged
    after["integrity"]["question_status_changes_expected"] = statuses_as_expected
    after["integrity"]["protected_counts_unchanged"] = protected_counts_unchanged
    after["integrity"]["protected_data_unchanged"] = protected_data_unchanged
    after["integrity"]["only_review_workflow_changed"] = allowed_changes
    after["actions"] = actions


def _selection_smoke_test(connection) -> list[dict]:
    category_filters = (
        ("Quantitative Aptitude", 1, 1),
        ("Logical Reasoning", 1, 2),
        ("Verbal Ability", 1, 5),
        ("Technical", 2, None),
    )
    matrix = []
    for category, track_id, topic_id in category_filters:
        for difficulty in ("EASY", "MEDIUM", "HARD"):
            try:
                selected = blueprint_service.select_filtered_questions(
                    connection,
                    "MCQ",
                    track_id,
                    difficulty,
                    topic_id,
                    None,
                    1,
                )
                eligible = all(
                    is_mock_eligible(connection, question_id)
                    for question_id in selected
                )
                if not eligible:
                    raise RuntimeError(
                        f"Selector returned a non-eligible {category} question."
                    )
                matrix.append(
                    {
                        "category": category,
                        "difficulty": difficulty,
                        "selected_count": len(selected),
                        "selected_question_ids": selected,
                        "all_selected_pass_canonical_eligibility": eligible,
                        "outcome": "SELECTED",
                    }
                )
            except HTTPException as error:
                if error.status_code != 409:
                    raise
                detail = error.detail if isinstance(error.detail, dict) else {}
                matrix.append(
                    {
                        "category": category,
                        "difficulty": difficulty,
                        "selected_count": 0,
                        "selected_question_ids": [],
                        "all_selected_pass_canonical_eligibility": True,
                        "outcome": "NO_ELIGIBLE_QUESTIONS",
                        "selector_detail": detail,
                    }
                )
    return matrix


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Move non-eligible target questions into governance review and record blockers.",
    )
    args = parser.parse_args()
    with engine.connect() as connection:
        database, rows, counts, category_totals = _load_bank(connection)
        integrity = _snapshot_integrity(connection)
    if database != "placement_platform":
        raise SystemExit(f"Refusing unexpected database: {database!r}")
    if len(rows) != EXPECTED_MCQ_TOTAL:
        raise SystemExit(f"Expected {EXPECTED_MCQ_TOTAL} MCQs; found {len(rows)}.")
    if category_totals != EXPECTED_TARGET_COUNTS:
        raise SystemExit(
            f"Live taxonomy target totals changed: {category_totals}."
        )
    before = _make_payload(
        database,
        rows,
        counts,
        category_totals,
        integrity,
        read_only=True,
    )

    if args.apply:
        if not BEFORE_JSON.exists() or not BEFORE_CSV.exists():
            raise SystemExit(
                "Create and inspect the before snapshot first by running this script "
                "without --apply."
            )
        previous = json.loads(BEFORE_JSON.read_text(encoding="utf-8"))
        if (
            previous.get("database") != database
            or previous.get("question_count") != EXPECTED_MCQ_TOTAL
        ):
            raise SystemExit("The before snapshot does not match the live database.")
        actions = _apply_review_queue(previous, before)
        with engine.connect() as connection:
            after_database, after_rows, after_counts, after_category_totals = _load_bank(
                connection
            )
            after_integrity = _snapshot_integrity(connection)
        after = _make_payload(
            after_database,
            after_rows,
            after_counts,
            after_category_totals,
            after_integrity,
            read_only=False,
        )
        _finalize_integrity(previous, after, actions)
        with engine.connect() as connection:
            after["mock_selection_test"] = _selection_smoke_test(connection)
        _write_audit(AFTER_JSON, AFTER_CSV, after)
        _write_review_queue(after["records"])
        _write_summary(previous, after, actions)
        print(
            json.dumps(
                {
                    "counts": after["counts"],
                    "actions": actions,
                    "mock_selection_test": after["mock_selection_test"],
                    "integrity": {
                        key: after["integrity"][key]
                        for key in (
                            "question_ids_hashes_unchanged",
                            "protected_counts_unchanged",
                            "only_review_workflow_changed",
                        )
                    },
                    "reports": [
                        str(AFTER_JSON),
                        str(AFTER_CSV),
                        str(REVIEW_CSV),
                        str(SUMMARY_MD),
                    ],
                },
                indent=2,
                default=_json_default,
            )
        )
    else:
        _write_audit(BEFORE_JSON, BEFORE_CSV, before)
        print(
            json.dumps(
                {
                    "counts": counts,
                    "category_totals": category_totals,
                    "reports": [str(BEFORE_JSON), str(BEFORE_CSV)],
                },
                indent=2,
                default=_json_default,
            )
        )


if __name__ == "__main__":
    main()
