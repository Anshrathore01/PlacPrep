"""Safely remediate MCQs using only evidence already stored in the database."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.database import engine
from scripts.audit_mcq_mock_eligibility import (
    EXPECTED_MCQ_TOTAL,
    EXPECTED_TARGET_COUNTS,
    SNAPSHOT_TABLES,
    TARGET_CATEGORIES,
    _load_bank,
    _snapshot_integrity,
)


REPORTS = BACKEND / "reports"
BEFORE_JSON = REPORTS / "mcq_content_remediation_before.json"
BEFORE_CSV = REPORTS / "mcq_content_remediation_before.csv"
AFTER_JSON = REPORTS / "mcq_content_remediation_after.json"
AFTER_CSV = REPORTS / "mcq_content_remediation_after.csv"
REVIEW_CSV = REPORTS / "mcq_content_remediation_review_queue.csv"
SUMMARY_MD = REPORTS / "mcq_content_remediation_summary.md"
PROGRESS_JSON = REPORTS / "mcq_content_remediation_progress.json"
REVIEW_MARKER = "MCQ_CONTENT_REMEDIATION:v1:"
REVIEWER_ID = 7
BATCH_SIZE = 50

CSV_FIELDS = (
    "question_id",
    "question_type",
    "source_id",
    "source_question_number",
    "title",
    "category",
    "topic",
    "subtopic",
    "difficulty",
    "status_before",
    "status_after",
    "option_count_before",
    "option_count_after",
    "answer_before",
    "answer_after",
    "explanation_before",
    "explanation_after",
    "defect",
    "action",
    "source_evidence",
    "confidence",
    "mock_eligible_after",
    "review_required",
    "blocker",
)

CONTENT_BLOCKER_PREFIXES = (
    "Question text is empty.",
    "Question text is required.",
    "Question difficulty",
    "Difficulty is missing or invalid.",
    "Question source does not exist.",
    "Source record is missing.",
    "Source question number/provenance metadata is missing.",
    "Question must have a subtopic",
    "Every question subtopic",
    "No options are stored.",
    "Unsupported option count:",
    "One or more option",
    "Option keys are duplicated.",
    "Option texts are duplicated.",
    "Correct answer key is missing.",
    "Correct answer key does not match",
    "A correct option is required.",
    "The correct option key must match",
    "Multiple-correct question",
    "Multiple-correct MCQs",
    "Question belongs to an exact duplicate group.",
    "Question duplicates existing question",
)

BLOCKER_ACTIONS = (
    (
        ("option",),
        "Recover the original options from the identified source record; "
        "if unavailable, author/review valid options without guessing.",
    ),
    (
        ("answer", "correct option", "correct answer"),
        "Verify the intended answer independently against the identified source "
        "and map it to exactly one stored option.",
    ),
    (
        ("authorization", "scraped source"),
        "Record verified source authorization/licensing evidence or exclude this "
        "source from production use.",
    ),
    (
        ("duplicate",),
        "Review the duplicate group and resolve its disposition without deleting "
        "any question or source record.",
    ),
    (
        ("difficulty",),
        "Have a reviewer validate the existing difficulty or provide an evidence-backed correction.",
    ),
    (
        ("subtopic", "topic", "track"),
        "Review the existing taxonomy mapping and correct it only with supporting evidence.",
    ),
    (
        ("question text",),
        "Recover the original question text from the source or have an authorized "
        "reviewer correct it without changing its meaning.",
    ),
)


def _json_default(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return value


def _label_signature(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.strip().casefold().split())
    if normalized.startswith("option "):
        normalized = normalized[7:].strip()
    if re.fullmatch(r"[a-e]|[1-5]", normalized):
        return normalized
    return None


def normalize_answer_key(
    answer_key: str | None, options: list[dict]
) -> str | None:
    """Return an existing option key only for a unique, obvious label match."""
    signature = _label_signature(answer_key)
    if signature is None:
        return None
    matches = [
        str(option["option_key"])
        for option in options
        if option.get("option_key") is not None
        and _label_signature(str(option["option_key"])) == signature
    ]
    if len(matches) != 1 or matches[0] == answer_key:
        return None
    return matches[0]


def _target_rows(records: list[dict]) -> list[dict]:
    return [row for row in records if row["category"] in TARGET_CATEGORIES]


def _source_evidence(row: dict) -> dict:
    metadata = _json_value(row.get("source_metadata"))
    return {
        "source_id": row.get("source_id"),
        "source_name": row.get("source_name"),
        "source_type": row.get("source_type"),
        "source_url": row.get("source_url"),
        "source_question_number": row.get("source_question_number"),
        "source_metadata": metadata,
        "source_notes": row.get("source_notes"),
        "available_local_source_payload": False,
    }


def _content_blockers(row: dict) -> list[str]:
    return [
        blocker
        for blocker in row["blocker_reason"]
        if blocker.startswith(CONTENT_BLOCKER_PREFIXES)
    ]


def _review_required(row: dict) -> bool:
    latest = row.get("latest_review")
    return (
        row.get("status") != "PUBLISHED"
        or (latest is not None and latest.get("decision") != "APPROVE")
        or bool(row.get("open_reports"))
        or any(
            "authorization" in blocker.casefold()
            or "scraped source" in blocker.casefold()
            for blocker in row.get("blocker_reason", [])
        )
    )


def _classification(row: dict, safe_repair_applied: bool) -> str:
    if row.get("eligible_after_repair"):
        return "VALID"
    if row.get("status") == "ARCHIVED":
        return "BLOCKED"
    if _content_blockers(row) or any(
        "authorization" in blocker.casefold()
        or "scraped source" in blocker.casefold()
        or "duplicate" in blocker.casefold()
        for blocker in row.get("blocker_reason", [])
    ):
        return "BLOCKED"
    if safe_repair_applied:
        return "SAFE_REPAIR"
    return "NEEDS_REVIEW"


def _reason_and_action(row: dict) -> tuple[list[str], str]:
    defects = list(dict.fromkeys(row.get("blocker_reason", [])))
    if not defects:
        defects = ["No canonical eligibility blocker found."]
    actions = []
    lowered = [defect.casefold() for defect in defects]
    for terms, action in BLOCKER_ACTIONS:
        if any(any(term in defect for term in terms) for defect in lowered):
            actions.append(action)
    if any("status" in defect or "review" in defect for defect in lowered):
        actions.append(
            "Complete human governance review through the existing workflow; "
            "do not publish automatically."
        )
    if not actions:
        actions.append(
            "Review the listed question-specific blockers and resolve them through "
            "the existing governance workflow."
        )
    return defects, " ".join(dict.fromkeys(actions))


def _build_records(rows: list[dict], before_by_id: dict[int, dict] | None = None) -> list[dict]:
    output = []
    before_by_id = before_by_id or {}
    for row in rows:
        question_id = int(row["question_id"])
        original = before_by_id.get(question_id, row)
        defects, required_action = _reason_and_action(row)
        safe_repair_applied = bool(row.get("safe_repair_applied"))
        classification = _classification(row, safe_repair_applied)
        content_blockers = _content_blockers(row)
        source_evidence = _source_evidence(row)
        review_required = _review_required(row)
        content_ready = not content_blockers
        action_parts = list(row.get("actions_applied", []))
        if not action_parts:
            action_parts.append(
                "No content change; source evidence was insufficient for any further automatic repair."
            )
        if row.get("status") == "ARCHIVED":
            action_parts.append("Retained ARCHIVED status; no reactivation attempted.")
        answer_before = original.get("correct_option_key")
        answer_after = row.get("correct_option_key")
        output.append(
            {
                "question_id": question_id,
                "question_type": row.get("question_type"),
                "source_id": row.get("source_id"),
                "source_question_number": row.get("source_question_number"),
                "title": row.get("title"),
                "category": row.get("category"),
                "topic": row.get("topic"),
                "subtopic": row.get("subtopic"),
                "difficulty": row.get("difficulty"),
                "status_before": original.get("status"),
                "status_after": row.get("status"),
                "option_count_before": len(original.get("options", [])),
                "option_count_after": len(row.get("options", [])),
                "answer_before": answer_before,
                "answer_after": answer_after,
                "explanation_before": original.get("explanation"),
                "explanation_after": row.get("explanation"),
                "defect": defects,
                "action": action_parts,
                "source_evidence": source_evidence,
                "source_authorization_status": row.get("source_authorization_status"),
                "confidence": (
                    "HIGH"
                    if safe_repair_applied
                    else "HIGH"
                    if row.get("eligible_after_repair")
                    else "LOW"
                    if content_blockers
                    else "MEDIUM"
                ),
                "classification": classification,
                "mock_content_ready": content_ready,
                "mock_eligible_after": bool(row.get("eligible_after_repair")),
                "review_required": review_required,
                "blocker": defects,
                "required_human_action": required_action,
            }
        )
    return output


def _write_json_csv(json_path: Path, csv_path: Path, payload: dict) -> None:
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default) + "\n",
        encoding="utf-8",
    )
    with csv_path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for record in payload["records"]:
            writer.writerow(
                {
                    field: json.dumps(
                        record[field], ensure_ascii=False, default=_json_default
                    )
                    if isinstance(record[field], (list, dict))
                    else record[field]
                    for field in CSV_FIELDS
                }
            )


def _summary_counts(records: list[dict]) -> dict:
    classes = Counter(record["classification"] for record in records)
    return {
        "target": len(records),
        "VALID_BEFORE": sum(record["mock_eligible_before"] for record in records),
        "SAFE_REPAIRED": sum(record["safe_repair_applied"] for record in records),
        "MOCK_CONTENT_READY": sum(record["mock_content_ready"] for record in records),
        "REVIEW_REQUIRED": sum(record["review_required"] for record in records),
        "BLOCKED": classes["BLOCKED"],
        "classification_counts": {
            state: classes[state]
            for state in ("VALID", "SAFE_REPAIR", "NEEDS_REVIEW", "BLOCKED")
        },
        "by_category": {},
        "by_difficulty": {},
        "option_count_distribution": dict(
            sorted(Counter(record["option_count_after"] for record in records).items())
        ),
        "invalid_answer_count": sum(
            record["answer_after"] is None
            or not record["answer_key_matches_option"]
            for record in records
        ),
        "unresolved_source_count": sum(
            record["source_authorization_status"] in {"NOT_RECORDED", "SOURCE_MISSING"}
            for record in records
        ),
        "unresolved_duplicate_count": sum(
            record["duplicate_group"] is not None for record in records
        ),
        "status_distribution": dict(
            sorted(Counter(record["status_after"] for record in records).items())
        ),
        "source_authorization_distribution": dict(
            sorted(
                Counter(
                    record["source_authorization_status"] for record in records
                ).items()
            )
        ),
        "defect_counts": dict(
            sorted(
                Counter(
                    defect
                    for record in records
                    for defect in record["defect"]
                ).items()
            )
        ),
    }


def _write_review_queue(records: list[dict]) -> None:
    fields = (
        "question_id",
        "defect_type",
        "observed_problem",
        "source_evidence",
        "why_automatic_repair_was_unsafe",
        "required_human_action",
        "remediation_version",
        "timestamp",
    )
    with REVIEW_CSV.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for record in records:
            if not record["review_required"]:
                continue
            defects = record["defect"] or ["Governance review required."]
            for defect in defects:
                writer.writerow(
                    {
                        "question_id": record["question_id"],
                        "defect_type": _defect_type(defect),
                        "observed_problem": defect,
                        "source_evidence": json.dumps(
                            record["source_evidence"], ensure_ascii=False
                        ),
                        "why_automatic_repair_was_unsafe": (
                            "No local original-source content payload was available to "
                            "verify a repair; answers/options were not inferred."
                        ),
                        "required_human_action": record["required_human_action"],
                        "remediation_version": "v1",
                        "timestamp": datetime.now().astimezone().isoformat(),
                    }
                )


def _defect_type(defect: str) -> str:
    normalized = defect.casefold()
    for needle, defect_type in (
        ("no options", "OPTIONS_MISSING"),
        ("option count", "OPTION_COUNT_INVALID"),
        ("option", "OPTIONS_INVALID"),
        ("correct answer key is missing", "ANSWER_MISSING"),
        ("correct answer", "ANSWER_KEY_INVALID"),
        ("multiple-correct", "MULTIPLE_CORRECT_UNSUPPORTED"),
        ("difficulty", "DIFFICULTY_INVALID"),
        ("subtopic", "TAXONOMY_INVALID"),
        ("topic", "TAXONOMY_INVALID"),
        ("duplicate", "DUPLICATE_REVIEW"),
        ("scraped source", "SOURCE_AUTHORIZATION_UNRESOLVED"),
        ("source", "SOURCE_PROVENANCE_INVALID"),
        ("archived", "ARCHIVED_STATUS"),
        ("review", "GOVERNANCE_REVIEW_PENDING"),
        ("published", "GOVERNANCE_REVIEW_PENDING"),
        ("question text", "QUESTION_TEXT_INVALID"),
    ):
        if needle in normalized:
            return defect_type
    return "CANONICAL_ELIGIBILITY_BLOCKER"


def _prepare_plan(records: list[dict]) -> list[dict]:
    for row in records:
        row["safe_repair_applied"] = False
        row["actions_applied"] = []
        row["mock_eligible_before"] = bool(row["eligible_before_repair"])
        row["answer_key_matches_option"] = bool(row["correct_key_exists"])
        row["source_evidence"] = _source_evidence(row)
        row["safe_repair"] = None
        proposed = normalize_answer_key(row.get("correct_option_key"), row["options"])
        if proposed is not None:
            row["safe_repair"] = {
                "field": "correct_option_key",
                "old_value": row["correct_option_key"],
                "new_value": proposed,
                "reason": "Unique case/whitespace/Option-prefix normalization to an existing option label.",
                "confidence": "HIGH",
            }
    return records


def _snapshot_start() -> dict:
    with engine.connect() as connection:
        database, rows, counts, category_totals = _load_bank(connection)
        integrity = _snapshot_integrity(connection)
        integrity["coding_data_hashes"] = _hash_tables(
            connection,
            (
                "coding_questions",
                "coding_test_cases",
                "question_examples",
                "coding_submissions",
            ),
        )
        integrity["historical_data_hashes"] = _hash_tables(
            connection,
            ("attempts", "attempt_answers", "mock_tests", "mock_test_questions"),
        )
    if database != "placement_platform":
        raise RuntimeError(f"Refusing unexpected database {database!r}.")
    if len(rows) != EXPECTED_MCQ_TOTAL:
        raise RuntimeError(f"Expected {EXPECTED_MCQ_TOTAL} MCQs, found {len(rows)}.")
    if category_totals != EXPECTED_TARGET_COUNTS:
        raise RuntimeError(f"Target category totals changed: {category_totals}.")
    target = _target_rows(rows)
    if len(target) != sum(EXPECTED_TARGET_COUNTS.values()):
        raise RuntimeError(f"Expected 1,681 target MCQs, found {len(target)}.")
    if len({int(row["question_id"]) for row in rows}) != len(rows):
        raise RuntimeError("Question IDs are not unique.")
    _prepare_plan(target)
    return database, rows, target, counts, category_totals, integrity


def _hash_tables(connection, table_names: tuple[str, ...]) -> dict[str, str]:
    from hashlib import sha256
    from sqlalchemy import inspect

    hashes = {}
    inspector = inspect(connection)
    for table in table_names:
        primary_keys = inspector.get_pk_constraint(table)["constrained_columns"]
        order = ", ".join(primary_keys) if primary_keys else "1"
        rows = [
            dict(row)
            for row in connection.execute(
                text(f"SELECT * FROM {table} ORDER BY {order}")
            ).mappings()
        ]
        serialized = json.dumps(
            rows,
            ensure_ascii=False,
            sort_keys=True,
            default=_json_default,
            separators=(",", ":"),
        ).encode("utf-8")
        hashes[table] = sha256(serialized).hexdigest()
    return hashes


def _record_review(
    connection, reviewer_id: int, row: dict, now_iso: str
) -> bool:
    question_id = int(row["question_id"])
    marker = f"{REVIEW_MARKER}{question_id}:"
    existing = connection.execute(
        text("""
            SELECT review_id
            FROM question_reviews
            WHERE question_id = :question_id
              AND LEFT(notes, CHAR_LENGTH(:marker)) = :marker
            LIMIT 1
        """),
        {"question_id": question_id, "marker": marker},
    ).scalar_one_or_none()
    if existing is not None:
        return False
    defects, required_action = _reason_and_action(row)
    evidence = {
        "question_id": question_id,
        "defect_type": [_defect_type(defect) for defect in defects],
        "observed_problem": defects,
        "source_evidence": row["source_evidence"],
        "why_automatic_repair_was_unsafe": (
            "No local original-source content payload was available to verify a "
            "repair. Existing explanations were not used as answer evidence; no "
            "options, answers, question text, or licensing facts were guessed."
        ),
        "required_human_action": required_action,
        "content_repair": row.get("safe_repair"),
        "actions_applied": row.get("actions_applied", []),
        "remediation_version": "v1",
        "timestamp": now_iso,
        "classification": row["classification"],
    }
    connection.execute(
        text("""
            INSERT INTO question_reviews (question_id, reviewer_id, decision, notes)
            VALUES (:question_id, :reviewer_id, 'PENDING', :notes)
        """),
        {
            "question_id": question_id,
            "reviewer_id": reviewer_id,
            "notes": marker + json.dumps(evidence, ensure_ascii=False),
        },
    )
    return True


def _apply_batches(target_rows: list[dict], planned: dict[int, dict], batch_size: int) -> dict:
    if not BEFORE_JSON.exists() or not BEFORE_CSV.exists():
        raise RuntimeError("Before reports must be persisted before --apply.")
    with engine.connect() as connection:
        reviewer_id = connection.execute(
            text("""
                SELECT user_id
                FROM users
                WHERE user_id = :reviewer_id
                  AND role = 'ADMIN'
                  AND is_active = TRUE
            """),
            {"reviewer_id": REVIEWER_ID},
        ).scalar_one_or_none()
    if reviewer_id is None:
        raise RuntimeError("The existing designated active administrator is unavailable.")

    review_inserted = 0
    repair_count = 0
    batch_total = (len(target_rows) + batch_size - 1) // batch_size
    with engine.connect() as connection:
        initial_marker_count = int(
            connection.execute(
                text("""
                    SELECT COUNT(*)
                    FROM question_reviews
                    WHERE LEFT(notes, CHAR_LENGTH(:marker)) = :marker
                """),
                {"marker": REVIEW_MARKER},
            ).scalar_one()
        )
    for batch_number, start in enumerate(range(0, len(target_rows), batch_size), 1):
        batch = target_rows[start : start + batch_size]
        batch_review_count = 0
        batch_repair_count = 0
        with engine.begin() as connection:
            for row in batch:
                question_id = int(row["question_id"])
                current = connection.execute(
                    text("""
                        SELECT q.question_type, q.status, q.content_hash,
                               q.source_id, q.source_question_number, q.source_metadata,
                               q.track_id, q.difficulty, mq.question_text,
                               mq.correct_option_key, mq.explanation,
                               mq.is_multiple_correct
                        FROM questions q
                        JOIN mcq_questions mq ON mq.question_id = q.question_id
                        WHERE q.question_id = :question_id
                        FOR UPDATE
                    """),
                    {"question_id": question_id},
                ).mappings().one_or_none()
                expected = planned[question_id]
                if current is None or current["question_type"] != "MCQ":
                    raise RuntimeError(f"Question {question_id} is no longer an MCQ.")
                for field in (
                    "content_hash",
                    "source_id",
                    "source_question_number",
                    "source_metadata",
                    "track_id",
                    "difficulty",
                    "question_text",
                    "explanation",
                    "is_multiple_correct",
                ):
                    if current[field] != expected.get(field):
                        raise RuntimeError(
                            f"Question {question_id} changed after planning ({field})."
                        )
                if current["status"] != expected["status"]:
                    raise RuntimeError(
                        f"Question {question_id} status changed after planning."
                    )
                if current["correct_option_key"] != expected["correct_option_key"]:
                    raise RuntimeError(
                        f"Question {question_id} answer key changed after planning."
                    )
                current_options = [
                    dict(option)
                    for option in connection.execute(
                        text("""
                            SELECT question_id, option_key, option_text, display_order
                            FROM mcq_options
                            WHERE question_id = :question_id
                            ORDER BY display_order, option_id
                            FOR UPDATE
                        """),
                        {"question_id": question_id},
                    ).mappings()
                ]
                if current_options != expected["options"]:
                    raise RuntimeError(
                        f"Question {question_id} options changed after planning."
                    )

                repair = row.get("safe_repair")
                if repair is not None:
                    if current["correct_option_key"] != repair["old_value"]:
                        raise RuntimeError(
                            f"Question {question_id} answer key changed after planning."
                        )
                    connection.execute(
                        text("""
                            UPDATE mcq_questions
                            SET correct_option_key = :answer_key
                            WHERE question_id = :question_id
                              AND correct_option_key = :old_answer_key
                        """),
                        {
                            "answer_key": repair["new_value"],
                            "question_id": question_id,
                            "old_answer_key": repair["old_value"],
                        },
                    )
                    batch_repair_count += 1

                candidate = dict(row)
                if repair:
                    candidate["correct_option_key"] = repair["new_value"]
                    candidate["correct_key_exists"] = True
                    candidate["answer_key_matches_option"] = True
                    candidate["safe_repair_applied"] = True
                    candidate["actions_applied"] = [
                        f"Normalized correct_option_key from {repair['old_value']!r} "
                        f"to existing option key {repair['new_value']!r}."
                    ]
                candidate["blocker_reason"] = [
                    blocker
                    for blocker in candidate["blocker_reason"]
                    if not (
                        "Correct answer key does not match" in blocker
                        or "correct option key must match" in blocker
                    )
                ]
                candidate["classification"] = _classification(
                    candidate, bool(repair)
                )
                if _record_review(
                    connection,
                    int(reviewer_id),
                    candidate,
                    datetime.now().astimezone().isoformat(),
                ):
                    batch_review_count += 1
        review_inserted += batch_review_count
        repair_count += batch_repair_count
        with engine.connect() as connection:
            counts = {
                table: int(
                    connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
                )
                for table in SNAPSHOT_TABLES
            }
        if counts["questions"] != planned["__question_count__"]:
            raise RuntimeError("Question count changed during a remediation batch.")
        for table in SNAPSHOT_TABLES:
            if table != "question_reviews" and counts[table] != planned["__table_counts__"][table]:
                raise RuntimeError(f"Unexpected {table} row-count change after batch {batch_number}.")
        with engine.connect() as connection:
            marker_count = int(
                connection.execute(
                    text("""
                        SELECT COUNT(*)
                        FROM question_reviews
                        WHERE LEFT(notes, CHAR_LENGTH(:marker)) = :marker
                    """),
                    {"marker": REVIEW_MARKER},
                ).scalar_one()
            )
        if marker_count != initial_marker_count + review_inserted:
            raise RuntimeError(
                f"Remediation review markers are not idempotent after batch {batch_number}."
            )
        PROGRESS_JSON.write_text(
            json.dumps(
                {
                    "updated_at": datetime.now().astimezone().isoformat(),
                    "batch": batch_number,
                    "batch_count": batch_total,
                    "questions_processed": min(start + len(batch), len(target_rows)),
                    "target_count": len(target_rows),
                    "safe_repairs_committed": repair_count,
                    "review_records_added_this_run": review_inserted,
                    "review_markers_verified": marker_count,
                    "database_question_count": counts["questions"],
                    "table_counts": counts,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(
            f"Batch {batch_number}/{batch_total}: processed {min(start + len(batch), len(target_rows))}/{len(target_rows)}; "
            f"repairs={repair_count}; review records added={review_inserted}"
        )
    return {
        "safe_repairs_this_run": repair_count,
        "review_records_added_this_run": review_inserted,
        "batches_committed": batch_total,
    }


def _finalize(
    before_rows: list[dict],
    after_rows: list[dict],
    before_integrity: dict,
    after_integrity: dict,
    actions: dict,
) -> tuple[list[dict], dict]:
    before_by_id = {int(row["question_id"]): row for row in before_rows}
    after_by_id = {int(row["question_id"]): row for row in after_rows}
    if before_by_id.keys() != after_by_id.keys():
        raise RuntimeError("MCQ question IDs changed during remediation.")
    expected_review_count = (
        before_integrity["counts"]["question_reviews"]
        + actions["review_records_added_this_run"]
    )
    for table in SNAPSHOT_TABLES:
        expected = (
            expected_review_count
            if table == "question_reviews"
            else before_integrity["counts"][table]
        )
        if after_integrity["counts"][table] != expected:
            raise RuntimeError(f"Unexpected {table} count after remediation.")

    protected_before = before_integrity["protected_data_hashes"]
    protected_after = after_integrity["protected_data_hashes"]
    ignored_protected_hash = {"mcq_content"}
    for key in protected_before:
        if key not in ignored_protected_hash and protected_before[key] != protected_after[key]:
            raise RuntimeError(f"Protected data changed unexpectedly: {key}.")
    if before_integrity["coding_data_hashes"] != after_integrity["coding_data_hashes"]:
        raise RuntimeError("Coding-question data changed during MCQ remediation.")
    if before_integrity["historical_data_hashes"] != after_integrity["historical_data_hashes"]:
        raise RuntimeError("Existing attempts or mock data changed during remediation.")

    action_by_id = {
        int(row["question_id"]): row
        for row in before_rows
        if row.get("safe_repair") is not None
    }
    for question_id, original in before_by_id.items():
        current = after_by_id[question_id]
        allowed_answer_change = (
            question_id in action_by_id
            and current["correct_option_key"]
            == action_by_id[question_id]["safe_repair"]["new_value"]
        )
        for field in (
            "question_type",
            "source_id",
            "source_name",
            "source_type",
            "source_url",
            "source_notes",
            "source_question_number",
            "source_metadata",
            "track_id",
            "track_name",
            "title",
            "difficulty",
            "status",
            "content_hash",
            "question_text",
            "explanation",
            "is_multiple_correct",
            "options",
            "mappings",
        ):
            if original.get(field) != current.get(field):
                raise RuntimeError(
                    f"Question {question_id} changed outside permitted fields ({field})."
                )
        if (
            original.get("correct_option_key") != current.get("correct_option_key")
            and not allowed_answer_change
        ):
            raise RuntimeError(f"Unplanned answer-key change for question {question_id}.")

    finalized_rows = []
    for row in after_rows:
        original = before_by_id[int(row["question_id"])]
        question_id = int(row["question_id"])
        repair = action_by_id.get(question_id, {}).get("safe_repair")
        row["mock_eligible_before"] = bool(original["eligible_before_repair"])
        row["safe_repair_applied"] = bool(repair)
        row["answer_key_matches_option"] = bool(row["correct_key_exists"])
        row["actions_applied"] = (
            [
                f"Normalized correct_option_key from {repair['old_value']!r} "
                f"to existing option key {repair['new_value']!r}."
            ]
            if repair
            else []
        )
        row["classification"] = _classification(row, bool(repair))
        finalized_rows.append(row)

    records = _build_records(finalized_rows, before_by_id)
    for record, row in zip(records, finalized_rows, strict=True):
        record["classification"] = row["classification"]
        record["safe_repair_applied"] = row["safe_repair_applied"]
        record["mock_eligible_before"] = row["mock_eligible_before"]
        record["answer_key_matches_option"] = row["answer_key_matches_option"]
        record["source_authorization_status"] = row["source_authorization_status"]
        record["duplicate_group"] = row.get("duplicate_group")
        record["option_count_after"] = len(row.get("options", []))
        record["mock_content_ready"] = not _content_blockers(row)
        record["review_required"] = _review_required(row)
    counts = _summary_counts(records)
    if sum(counts["classification_counts"].values()) != len(records):
        raise RuntimeError("Final classification counts do not cover every target MCQ.")
    for category in TARGET_CATEGORIES:
        members = [record for record in records if record["category"] == category]
        counts["by_category"][category] = {
            "total": len(members),
            "mock_content_ready": sum(item["mock_content_ready"] for item in members),
            "review_required": sum(item["review_required"] for item in members),
            "blocked": sum(item["classification"] == "BLOCKED" for item in members),
            "mock_eligible": sum(item["mock_eligible_after"] for item in members),
        }
    for difficulty in ("EASY", "MEDIUM", "HARD", "INVALID_OR_MISSING"):
        members = [
            record
            for record in records
            if (record["difficulty"] or "INVALID_OR_MISSING") == difficulty
        ]
        counts["by_difficulty"][difficulty] = {
            "total": len(members),
            "mock_content_ready": sum(item["mock_content_ready"] for item in members),
            "review_required": sum(item["review_required"] for item in members),
            "blocked": sum(item["classification"] == "BLOCKED" for item in members),
            "mock_eligible": sum(item["mock_eligible_after"] for item in members),
        }
    return records, counts


def _assert_all_mcqs_preserved(
    before_rows: list[dict], after_rows: list[dict], planned: dict[int, dict]
) -> None:
    before_by_id = {int(row["question_id"]): row for row in before_rows}
    after_by_id = {int(row["question_id"]): row for row in after_rows}
    if before_by_id.keys() != after_by_id.keys():
        raise RuntimeError("MCQ IDs changed during remediation.")
    permitted_repairs = {
        question_id: plan["safe_repair"]
        for question_id, plan in planned.items()
        if isinstance(question_id, int) and plan.get("safe_repair") is not None
    }
    for question_id, original in before_by_id.items():
        current = after_by_id[question_id]
        for field in (
            "question_type",
            "source_id",
            "source_name",
            "source_type",
            "source_url",
            "source_notes",
            "source_question_number",
            "source_metadata",
            "track_id",
            "track_name",
            "title",
            "difficulty",
            "status",
            "content_hash",
            "question_text",
            "explanation",
            "is_multiple_correct",
            "options",
            "mappings",
        ):
            if original.get(field) != current.get(field):
                raise RuntimeError(
                    f"MCQ {question_id} changed outside the permitted field: {field}."
                )
        old_answer = original.get("correct_option_key")
        new_answer = current.get("correct_option_key")
        if old_answer == new_answer:
            continue
        repair = permitted_repairs.get(question_id)
        if repair is None or (
            old_answer != repair["old_value"] or new_answer != repair["new_value"]
        ):
            raise RuntimeError(f"Unexpected answer-key change for MCQ {question_id}.")


def _write_summary(before: dict, after: dict, counts: dict, actions: dict) -> None:
    lines = [
        "# MCQ content remediation",
        "",
        f"- Database: `{after['database']}`",
        f"- Target MCQs: {counts['target']}",
        f"- Canonically eligible before: {counts['VALID_BEFORE']}",
        f"- Safe repairs applied: {counts['SAFE_REPAIRED']}",
        f"- Mock-content-ready (structural/content checks only): {counts['MOCK_CONTENT_READY']}",
        f"- Review required: {counts['REVIEW_REQUIRED']}",
        f"- Blocked: {counts['BLOCKED']}",
        f"- Canonically mock-eligible after: {sum(record['mock_eligible_after'] for record in after['records'])}",
        f"- Stored answer missing/unmatched to an option: {counts['invalid_answer_count']} (this does not independently verify answer correctness)",
        f"- Unresolved source authorization/provenance: {counts['unresolved_source_count']}",
        f"- Questions in a duplicate group: {counts['unresolved_duplicate_count']}",
        f"- Option-count distribution: `{json.dumps(counts['option_count_distribution'], sort_keys=True)}`",
        f"- MCQ status distribution: `{json.dumps(counts['status_distribution'], sort_keys=True)}`",
        "",
        "## Classifications",
        "",
        "| Class | Questions |",
        "|---|---:|",
    ]
    lines.extend(
        f"| {state} | {count} |"
        for state, count in counts["classification_counts"].items()
    )
    lines.extend(
        [
            "",
            "## By category",
            "",
            "| Category | Total | Content ready | Review required | Blocked | Eligible |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for category, values in counts["by_category"].items():
        lines.append(
            f"| {category} | {values['total']} | {values['mock_content_ready']} | "
            f"{values['review_required']} | {values['blocked']} | {values['mock_eligible']} |"
        )
    lines.extend(
        [
            "",
            "## By difficulty",
            "",
            "| Difficulty | Total | Content ready | Review required | Blocked | Eligible |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for difficulty, values in counts["by_difficulty"].items():
        lines.append(
            f"| {difficulty} | {values['total']} | {values['mock_content_ready']} | "
            f"{values['review_required']} | {values['blocked']} | {values['mock_eligible']} |"
        )
    lines.extend(
        [
            "",
            "## Data integrity",
            "",
            f"- Safe answer-key normalizations applied this run: {actions['safe_repairs_this_run']}",
            f"- Question-specific review records added this run: {actions['review_records_added_this_run']}",
            f"- Question count unchanged: {before['integrity_before']['counts']['questions'] == after['integrity_after']['counts']['questions']}",
            f"- Coding question data unchanged: {before['integrity_before']['coding_data_hashes'] == after['integrity_after']['coding_data_hashes']}",
            f"- Existing attempts/mocks/history retained: table counts are unchanged except for newly inserted `question_reviews` records.",
            "- Question text, options, explanations, source, taxonomy, difficulty, and status were not changed by this run.",
            "- No questions were published or reactivated.",
            "",
            "The available local source data contains source identifiers/metadata but no original source payload for restoring missing options or verifying contradictory answer keys. Such records remain blocked or in review; no answer was inferred from an explanation and no external payload was fetched.",
        ]
    )
    SUMMARY_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Commit safe label normalizations and review records in batches.")
    parser.add_argument("--dry-run", action="store_true", help="Write the before plan without database changes.")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    args = parser.parse_args()
    if args.batch_size < 1 or args.batch_size > 100:
        raise SystemExit("--batch-size must be between 1 and 100.")
    if args.apply and args.dry_run:
        raise SystemExit("Choose either --apply or --dry-run.")

    database, all_rows, target_rows, counts, category_totals, integrity = _snapshot_start()
    before_records = _build_records(target_rows)
    before_payload = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "database": database,
        "mode": "APPLY_PLAN" if args.apply else "DRY_RUN",
        "target_count": len(target_rows),
        "category_totals": category_totals,
        "integrity_before": integrity,
        "source_material_inspection": {
            "source_material_found": (
                "Only the imported database content and source metadata were "
                "available. No original MCQ export or payload was found in the "
                "backend repository."
            ),
            "external_source_payload_fetched": False,
        },
        "records": before_records,
        "planned_safe_repairs": [
            {
                "question_id": row["question_id"],
                **row["safe_repair"],
            }
            for row in target_rows
            if row.get("safe_repair") is not None
        ],
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    preserve_original_before = (
        args.apply
        and BEFORE_JSON.exists()
        and PROGRESS_JSON.exists()
    )
    preserve_completed_reports = (
        args.apply
        and BEFORE_JSON.exists()
        and AFTER_JSON.exists()
    )
    if not preserve_original_before:
        _write_json_csv(BEFORE_JSON, BEFORE_CSV, before_payload)
    if len(before_payload["records"]) != 1681:
        raise RuntimeError("Before report does not contain every target MCQ.")

    if not args.apply:
        print(
            json.dumps(
                {
                    "mode": "DRY_RUN",
                    "target": len(target_rows),
                    "planned_safe_repairs": len(before_payload["planned_safe_repairs"]),
                    "before_reports": [str(BEFORE_JSON), str(BEFORE_CSV)],
                },
                indent=2,
            )
        )
        return

    planned = {
        int(row["question_id"]): row
        for row in target_rows
    }
    planned["__question_count__"] = integrity["counts"]["questions"]
    planned["__table_counts__"] = integrity["counts"]
    actions = _apply_batches(target_rows, planned, args.batch_size)

    with engine.connect() as connection:
        after_database, after_rows_all, after_counts, after_categories = _load_bank(connection)
        after_integrity = _snapshot_integrity(connection)
        after_integrity["coding_data_hashes"] = _hash_tables(
            connection,
            (
                "coding_questions",
                "coding_test_cases",
                "question_examples",
                "coding_submissions",
            ),
        )
        after_integrity["historical_data_hashes"] = _hash_tables(
            connection,
            ("attempts", "attempt_answers", "mock_tests", "mock_test_questions"),
        )
    if after_database != database or after_categories != category_totals:
        raise RuntimeError("Database identity or target taxonomy changed.")
    after_target = _target_rows(after_rows_all)
    for row in after_target:
        row["eligible_after_repair"] = bool(row["eligible_before_repair"])
        row["answer_key_matches_option"] = bool(row["correct_key_exists"])
        repair = planned[int(row["question_id"])].get("safe_repair")
        row["safe_repair_applied"] = bool(
            repair
            and row["correct_option_key"] == repair["new_value"]
        )
        row["actions_applied"] = (
            [
                f"Normalized correct_option_key from {repair['old_value']!r} "
                f"to existing option key {repair['new_value']!r}."
            ]
            if row["safe_repair_applied"]
            else []
        )
    _assert_all_mcqs_preserved(all_rows, after_rows_all, planned)
    after_records, summary_counts = _finalize(
        target_rows,
        after_target,
        integrity,
        after_integrity,
        actions,
    )
    report_before_payload = before_payload
    report_actions = actions
    if preserve_completed_reports:
        report_before_payload = json.loads(BEFORE_JSON.read_text(encoding="utf-8"))
        previous_after_payload = json.loads(AFTER_JSON.read_text(encoding="utf-8"))
        for record in report_before_payload["records"]:
            before_row = {
                "status": record["status_before"],
                "eligible_after_repair": record["mock_eligible_after"],
                "blocker_reason": record["blocker"],
            }
            record["classification"] = _classification(before_row, False)
        report_actions = previous_after_payload["actions"]
    after_payload = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "database": database,
        "mode": "APPLIED",
        "target_count": len(after_records),
        "category_totals": category_totals,
        "counts": summary_counts,
        "actions": report_actions,
        "integrity_before": report_before_payload["integrity_before"],
        "integrity_after": after_integrity,
        "source_material_inspection": report_before_payload.get("source_material_inspection"),
        "records": after_records,
    }
    _write_json_csv(BEFORE_JSON, BEFORE_CSV, report_before_payload)
    _write_json_csv(AFTER_JSON, AFTER_CSV, after_payload)
    _write_review_queue(after_records)
    _write_summary(report_before_payload, after_payload, summary_counts, report_actions)
    if len(after_records) != 1681 or any(
        record["difficulty"] not in {"EASY", "MEDIUM", "HARD"}
        for record in after_records
    ):
        raise RuntimeError("Final per-question report failed completeness validation.")
    with engine.connect() as connection:
        review_records = int(
            connection.execute(
                text("""
                    SELECT COUNT(DISTINCT qr.question_id)
                    FROM question_reviews qr
                    JOIN questions q ON q.question_id = qr.question_id
                    WHERE LEFT(qr.notes, CHAR_LENGTH(:marker)) = :marker
                      AND q.question_type = 'MCQ'
                      AND (
                          q.track_id = 2
                          OR EXISTS (
                              SELECT 1
                              FROM question_subtopics qs
                              JOIN subtopics st ON st.subtopic_id = qs.subtopic_id
                              JOIN topics t ON t.topic_id = st.topic_id
                              WHERE qs.question_id = q.question_id
                                AND t.topic_name IN (
                                    'Quantitative Aptitude',
                                    'Logical Reasoning',
                                    'Verbal Ability'
                                )
                          )
                      )
                """),
                {"marker": REVIEW_MARKER},
            ).scalar_one()
        )
    if review_records != len(after_records):
        raise RuntimeError(
            f"Expected remediation reviews for {len(after_records)} target MCQs; found {review_records}."
        )
    print(
        json.dumps(
            {
                "counts": summary_counts,
                "actions": actions,
                "reports": [
                    str(BEFORE_JSON),
                    str(BEFORE_CSV),
                    str(AFTER_JSON),
                    str(AFTER_CSV),
                    str(REVIEW_CSV),
                    str(SUMMARY_MD),
                    str(PROGRESS_JSON),
                ],
            },
            indent=2,
            default=_json_default,
        )
    )


if __name__ == "__main__":
    main()
