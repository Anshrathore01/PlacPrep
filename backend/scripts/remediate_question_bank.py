"""Snapshot, audit, and conservatively remediate the live question bank."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import engine
from app.judge.docker_sandbox import docker_is_ready
from app.services import question_governance_service
from scripts.audit_question_bank import audit as audit_question_bank
from scripts.audit_question_bank import normalize_text
from scripts.repair_coding_questions import _review_reason


EXPECTED_TOTAL = 2207
EXPECTED_BY_TYPE = {"MCQ": 1917, "CODING": 290}
MAX_BATCH_SIZE = 25
REVIEW_MARKER = "QUESTION_BANK_REMEDIATION:v1:"
REPORT_DIRECTORY = Path(__file__).resolve().parents[1] / "reports"
BEFORE_JSON = REPORT_DIRECTORY / "question_bank_before_remediation.json"
BEFORE_CSV = REPORT_DIRECTORY / "question_bank_before_remediation.csv"
FINAL_JSON = REPORT_DIRECTORY / "question_bank_remediation_final.json"
FINAL_CSV = REPORT_DIRECTORY / "question_bank_remediation_final.csv"
REVIEW_QUEUE_CSV = REPORT_DIRECTORY / "question_bank_review_queue.csv"
HISTORICAL_TABLES = (
    "users",
    "attempts",
    "attempt_answers",
    "mock_tests",
    "mock_test_questions",
    "coding_submissions",
    "question_reviews",
    "question_status_history",
)

QUESTION_QUERY = """
    SELECT q.question_id, q.source_id, s.source_name, s.source_type,
           s.source_url, s.source_notes, q.source_question_number,
           q.source_metadata, q.content_hash, q.question_type, q.track_id,
           tr.track_name, q.title, q.difficulty, q.status,
           q.expected_time_seconds, q.created_at, q.updated_at,
           mq.question_text, mq.correct_option_key, mq.is_multiple_correct,
           mq.explanation AS mcq_explanation,
           cq.problem_statement, cq.constraints_text, cq.input_format,
           cq.output_format, cq.starter_code, cq.solution_pseudocode,
           cq.solution_explanation, cq.time_complexity, cq.space_complexity,
           cq.solution_visibility,
           (SELECT st.subtopic_id
            FROM question_subtopics qs
            JOIN subtopics st ON st.subtopic_id = qs.subtopic_id
            WHERE qs.question_id = q.question_id
            ORDER BY qs.is_primary DESC, st.subtopic_id
            LIMIT 1) AS subtopic_id,
           (SELECT st.subtopic_name
            FROM question_subtopics qs
            JOIN subtopics st ON st.subtopic_id = qs.subtopic_id
            WHERE qs.question_id = q.question_id
            ORDER BY qs.is_primary DESC, st.subtopic_id
            LIMIT 1) AS subtopic_name,
           (SELECT t.topic_id
            FROM question_subtopics qs
            JOIN subtopics st ON st.subtopic_id = qs.subtopic_id
            JOIN topics t ON t.topic_id = st.topic_id
            WHERE qs.question_id = q.question_id
            ORDER BY qs.is_primary DESC, st.subtopic_id
            LIMIT 1) AS topic_id,
           (SELECT t.topic_name
            FROM question_subtopics qs
            JOIN subtopics st ON st.subtopic_id = qs.subtopic_id
            JOIN topics t ON t.topic_id = st.topic_id
            WHERE qs.question_id = q.question_id
            ORDER BY qs.is_primary DESC, st.subtopic_id
            LIMIT 1) AS topic_name,
           (SELECT t.track_id
            FROM question_subtopics qs
            JOIN subtopics st ON st.subtopic_id = qs.subtopic_id
            JOIN topics t ON t.topic_id = st.topic_id
            WHERE qs.question_id = q.question_id
            ORDER BY qs.is_primary DESC, st.subtopic_id
            LIMIT 1) AS taxonomy_track_id,
           (SELECT COUNT(*) FROM question_reviews qr
            WHERE qr.question_id = q.question_id) AS review_count,
           (SELECT COUNT(*) FROM question_examples e
            WHERE e.question_id = q.question_id) AS example_count,
           (SELECT COUNT(*) FROM coding_test_cases tc
            WHERE tc.question_id = q.question_id) AS test_case_count,
           (SELECT COUNT(*) FROM coding_test_cases tc
            WHERE tc.question_id = q.question_id AND tc.is_hidden = FALSE)
             AS public_test_case_count,
           (SELECT COUNT(*) FROM coding_test_cases tc
            WHERE tc.question_id = q.question_id AND tc.is_hidden = TRUE)
             AS hidden_test_case_count
    FROM questions q
    LEFT JOIN sources s ON s.source_id = q.source_id
    LEFT JOIN tracks tr ON tr.track_id = q.track_id
    LEFT JOIN mcq_questions mq ON mq.question_id = q.question_id
    LEFT JOIN coding_questions cq ON cq.question_id = q.question_id
    ORDER BY q.question_id
"""

OPTIONS_QUERY = """
    SELECT question_id, option_key, option_text, display_order
    FROM mcq_options
    ORDER BY question_id, display_order, option_id
"""
EXAMPLES_QUERY = """
    SELECT question_id, example_number, input_data, output_data, explanation
    FROM question_examples
    ORDER BY question_id, example_number
"""
DUPLICATE_MATCHES_QUERY = """
    SELECT question_id_a, question_id_b, similarity_score, match_type, resolution
    FROM duplicate_matches
    ORDER BY question_id_a, question_id_b
"""
DATABASE_NAME_QUERY = "SELECT DATABASE()"

FINAL_FIELDS = (
    "question_id",
    "source_id",
    "source_question_number",
    "title",
    "question_type",
    "old_status",
    "new_status",
    "old_answer_key",
    "new_answer_key",
    "old_option_count",
    "new_option_count",
    "duplicate_group",
    "duplicate_resolution",
    "old_input_format",
    "new_input_format",
    "old_output_format",
    "new_output_format",
    "old_constraints",
    "new_constraints",
    "starter_code_created",
    "examples_created",
    "public_test_cases",
    "hidden_test_cases",
    "reference_solution_valid",
    "expected_outputs_verified",
    "starter_code_compiles",
    "judge_validated",
    "source_traceable",
    "source_authorized",
    "governance_ready",
    "publish_ready",
    "repair_status",
    "errors",
    "warnings",
    "review_reason",
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


def _json_cell(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=_json_default)


def capture_live_bank(connection) -> tuple[str | None, list[dict], dict, list[dict]]:
    database_name = connection.execute(text(DATABASE_NAME_QUERY)).scalar_one_or_none()
    rows = [dict(row) for row in connection.execute(text(QUESTION_QUERY)).mappings()]
    for row in rows:
        row["source_metadata"] = _decode_json(row.get("source_metadata"))
    options_by_id: dict[int, list[dict]] = defaultdict(list)
    for option in connection.execute(text(OPTIONS_QUERY)).mappings():
        options_by_id[int(option["question_id"])].append(dict(option))
    examples_by_id: dict[int, list[dict]] = defaultdict(list)
    for example in connection.execute(text(EXAMPLES_QUERY)).mappings():
        examples_by_id[int(example["question_id"])].append(dict(example))
    duplicate_matches = [
        dict(row) for row in connection.execute(text(DUPLICATE_MATCHES_QUERY)).mappings()
    ]
    duplicate_ids_by_question: dict[int, list[dict]] = defaultdict(list)
    for match in duplicate_matches:
        left = int(match["question_id_a"])
        right = int(match["question_id_b"])
        duplicate_ids_by_question[left].append(match)
        duplicate_ids_by_question[right].append(match)

    mcqs = [row for row in rows if row["question_type"] == "MCQ"]
    duplicate_hash_groups: dict[str, list[int]] = defaultdict(list)
    duplicate_text_groups: dict[str, list[int]] = defaultdict(list)
    for row in mcqs:
        if row.get("content_hash"):
            duplicate_hash_groups[str(row["content_hash"])].append(int(row["question_id"]))
        normalized = normalize_text(row.get("question_text"))
        if normalized:
            duplicate_text_groups[normalized].append(int(row["question_id"]))

    for row in rows:
        question_id = int(row["question_id"])
        options = options_by_id.get(question_id, [])
        row["options"] = options if row["question_type"] == "MCQ" else []
        row["examples"] = examples_by_id.get(question_id, [])
        row["duplicate_matches"] = duplicate_ids_by_question.get(question_id, [])
        row["duplicate_groups"] = []
        if row["question_type"] == "MCQ":
            if row.get("content_hash"):
                group = duplicate_hash_groups[str(row["content_hash"])]
                if len(group) > 1:
                    row["duplicate_groups"].append(
                        {"kind": "CONTENT_HASH", "question_ids": group}
                    )
            normalized = normalize_text(row.get("question_text"))
            if normalized and len(duplicate_text_groups[normalized]) > 1:
                row["duplicate_groups"].append(
                    {
                        "kind": "NORMALIZED_QUESTION_TEXT",
                        "question_ids": duplicate_text_groups[normalized],
                    }
                )
        row["duplicate_group"] = bool(row["duplicate_matches"] or row["duplicate_groups"])
    historical_counts = {}
    for table in HISTORICAL_TABLES:
        historical_counts[table] = int(
            connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
        )
    return database_name, rows, historical_counts, duplicate_matches


def _snapshot_record(row: dict) -> dict:
    return {
        "question_id": int(row["question_id"]),
        "source_id": row["source_id"],
        "source_name": row["source_name"],
        "source_type": row["source_type"],
        "source_url": row["source_url"],
        "source_notes": row["source_notes"],
        "source_question_number": row["source_question_number"],
        "source_metadata": row["source_metadata"],
        "title": row["title"],
        "question_type": row["question_type"],
        "difficulty": row["difficulty"],
        "status": row["status"],
        "track_id": row["track_id"],
        "track_name": row["track_name"],
        "topic_id": row["topic_id"],
        "topic_name": row["topic_name"],
        "subtopic_id": row["subtopic_id"],
        "subtopic_name": row["subtopic_name"],
        "question_text": row["question_text"],
        "options": row["options"],
        "correct_option_key": row["correct_option_key"],
        "is_multiple_correct": row["is_multiple_correct"],
        "explanation": row["mcq_explanation"],
        "problem_statement": row["problem_statement"],
        "constraints_text": row["constraints_text"],
        "input_format": row["input_format"],
        "output_format": row["output_format"],
        "starter_code": row["starter_code"],
        "solution_pseudocode": row["solution_pseudocode"],
        "solution_explanation": row["solution_explanation"],
        "time_complexity": row["time_complexity"],
        "space_complexity": row["space_complexity"],
        "solution_visibility": row["solution_visibility"],
        "examples": row["examples"],
        "example_count": int(row["example_count"] or 0),
        "test_case_count": int(row["test_case_count"] or 0),
        "public_test_case_count": int(row["public_test_case_count"] or 0),
        "hidden_test_case_count": int(row["hidden_test_case_count"] or 0),
        "review_count": int(row["review_count"] or 0),
        "duplicate_matches": row["duplicate_matches"],
        "duplicate_groups": row["duplicate_groups"],
    }


def write_before_snapshot(
    database_name: str | None,
    rows: list[dict],
    historical_counts: dict,
    duplicate_matches: list[dict],
    refresh: bool = False,
) -> None:
    if (BEFORE_JSON.exists() or BEFORE_CSV.exists()) and not refresh:
        if not BEFORE_JSON.exists() or not BEFORE_CSV.exists():
            raise RuntimeError(
                "Baseline snapshot is incomplete; use --refresh-snapshot only after "
                "reviewing the existing file."
            )
        try:
            existing = json.loads(BEFORE_JSON.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError(
                f"Existing baseline snapshot is unreadable: {BEFORE_JSON}"
            ) from error
        if existing.get("question_total") != len(rows):
            raise RuntimeError(
                "Existing baseline snapshot has a different bank size; "
                "use --refresh-snapshot only after reviewing the baseline."
            )
        existing_ids = {
            int(record["question_id"]) for record in existing.get("records", [])
        }
        current_ids = {int(row["question_id"]) for row in rows}
        if existing.get("database") != database_name or existing_ids != current_ids:
            raise RuntimeError(
                "Existing baseline belongs to a different database/question ID set; "
                "use --refresh-snapshot only after reviewing the baseline."
            )
        return

    REPORT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    records = [_snapshot_record(row) for row in rows]
    payload = {
        "snapshot_version": "v1",
        "read_only": True,
        "database": database_name,
        "captured_at": datetime.now().astimezone().isoformat(),
        "question_total": len(records),
        "question_type_counts": dict(Counter(r["question_type"] for r in records)),
        "historical_table_counts": historical_counts,
        "duplicate_match_record_count": len(duplicate_matches),
        "records": records,
    }
    BEFORE_JSON.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default) + "\n",
        encoding="utf-8",
    )
    csv_fields = [
        "question_id",
        "source_id",
        "source_name",
        "source_type",
        "source_url",
        "source_question_number",
        "source_metadata",
        "title",
        "question_type",
        "difficulty",
        "status",
        "track_id",
        "track_name",
        "topic_id",
        "topic_name",
        "subtopic_id",
        "subtopic_name",
        "question_text",
        "options",
        "correct_option_key",
        "is_multiple_correct",
        "explanation",
        "problem_statement",
        "constraints_text",
        "input_format",
        "output_format",
        "starter_code",
        "solution_pseudocode",
        "solution_explanation",
        "time_complexity",
        "space_complexity",
        "solution_visibility",
        "examples",
        "example_count",
        "test_case_count",
        "public_test_case_count",
        "hidden_test_case_count",
        "review_count",
        "duplicate_matches",
        "duplicate_groups",
    ]
    with BEFORE_CSV.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=csv_fields)
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    field: (
                        _json_cell(record[field])
                        if field in {
                            "source_metadata",
                            "options",
                            "examples",
                            "duplicate_matches",
                            "duplicate_groups",
                        }
                        else record[field]
                    )
                    for field in csv_fields
                }
            )


def _mcq_issue_codes(row: dict) -> list[str]:
    errors = []
    options = row["options"]
    option_keys = [option["option_key"] for option in options]
    normalized_texts = [
        normalize_text(option.get("option_text"))
        for option in options
        if normalize_text(option.get("option_text"))
    ]
    if not row.get("question_text") or not str(row["question_text"]).strip():
        errors.append("MISSING_QUESTION_TEXT")
    errors.append("MCQ_ANSWER_NOT_INDEPENDENTLY_VERIFIED")
    if not row.get("mcq_explanation") or not str(row["mcq_explanation"]).strip():
        errors.append("MCQ_EXPLANATION_MISSING")
    else:
        errors.append("MCQ_EXPLANATION_NOT_INDEPENDENTLY_VERIFIED")
    if not options:
        errors.append("MCQ_MISSING_OPTIONS")
    elif len(options) not in (4, 5):
        errors.append("MCQ_INCOMPLETE_OPTIONS")
    if any(not str(option.get("option_text") or "").strip() for option in options):
        errors.append("MCQ_EMPTY_OPTION_TEXT")
    if len(option_keys) != len(set(option_keys)):
        errors.append("MCQ_DUPLICATE_OPTION_KEYS")
    if len(normalized_texts) != len(set(normalized_texts)):
        errors.append("MCQ_DUPLICATE_OPTION")
    key = row.get("correct_option_key")
    if not key or not str(key).strip():
        errors.append("MCQ_NULL_ANSWER")
    elif key not in option_keys:
        errors.append("MCQ_INVALID_ANSWER")
    if row.get("is_multiple_correct"):
        errors.append("MCQ_MULTIPLE_CORRECT_UNSUPPORTED")
    if row["duplicate_group"]:
        errors.append("MCQ_DUPLICATE_CONTENT")
    if row.get("difficulty") not in {"EASY", "MEDIUM", "HARD"}:
        errors.append("MCQ_INVALID_DIFFICULTY")
    if not row.get("source_id") or not row.get("source_name"):
        errors.append("MCQ_SOURCE_UNTRACEABLE")
    if row.get("source_question_number") is None and not row.get("source_metadata"):
        errors.append("MCQ_SOURCE_UNTRACEABLE")
    if row.get("source_type") == "SCRAPED":
        errors.append("MCQ_SOURCE_UNAUTHORIZED_OR_UNVERIFIED")
    if not row.get("topic_id") or not row.get("subtopic_id"):
        errors.append("MCQ_TAXONOMY_MISSING")
    elif row.get("taxonomy_track_id") != row.get("track_id"):
        errors.append("MCQ_TAXONOMY_TRACK_MISMATCH")
    return sorted(set(errors))


def _coding_issue_codes(row: dict, docker_ready: bool) -> list[str]:
    _, errors, _ = _review_reason(row)
    issue_codes = []
    categories = (
        ("statement", "CODING_MISSING_STATEMENT"),
        ("constraints", "CODING_MISSING_CONSTRAINTS"),
        ("input contract", "CODING_MISSING_INPUT_FORMAT"),
        ("output contract", "CODING_MISSING_OUTPUT_FORMAT"),
        ("starter code", "CODING_INVALID_STARTER"),
        ("complete public examples", "CODING_MISSING_EXAMPLES"),
        ("public judge test cases", "CODING_MISSING_TEST_CASES"),
        ("hidden judge test cases", "CODING_MISSING_TEST_CASES"),
        ("reference-algorithm pseudocode", "CODING_REFERENCE_SOLUTION_INVALID"),
    )
    combined = " ".join(errors).casefold()
    for fragment, category in categories:
        if fragment in combined:
            issue_codes.append(category)
    if not row.get("problem_statement") or not str(row["problem_statement"]).strip():
        issue_codes.append("CODING_AMBIGUOUS_CONTRACT")
    if not docker_ready:
        issue_codes.append("CODING_TEST_VALIDATION_FAILED")
    if row.get("source_type") == "SCRAPED":
        issue_codes.append("CODING_SOURCE_UNVERIFIED")
    if not row.get("source_id") or not row.get("source_name"):
        issue_codes.append("CODING_SOURCE_UNVERIFIED")
    if not row.get("topic_id") or not row.get("subtopic_id"):
        issue_codes.append("CODING_TAXONOMY_MISSING")
    if row.get("duplicate_group"):
        issue_codes.append("CODING_DUPLICATE_CONTENT")
    if not row.get("time_complexity") or not str(row["time_complexity"]).strip():
        issue_codes.append("CODING_MISSING_TIME_COMPLEXITY")
    if not row.get("space_complexity") or not str(row["space_complexity"]).strip():
        issue_codes.append("CODING_MISSING_SPACE_COMPLEXITY")
    if not row.get("solution_explanation") or not str(row["solution_explanation"]).strip():
        issue_codes.append("CODING_MISSING_SOLUTION_EXPLANATION")
    return sorted(set(issue_codes))


def _category_codes(record: dict) -> list[str]:
    mapped = {
        "MCQ_INVALID_ANSWER": {"MCQ_INVALID_ANSWER", "MCQ_NULL_ANSWER"},
        "MCQ_ANSWER_UNVERIFIED": {"MCQ_ANSWER_NOT_INDEPENDENTLY_VERIFIED"},
        "MCQ_MISSING_OPTIONS": {"MCQ_MISSING_OPTIONS"},
        "MCQ_INCOMPLETE_OPTIONS": {"MCQ_INCOMPLETE_OPTIONS", "MCQ_EMPTY_OPTION_TEXT"},
        "MCQ_DUPLICATE_OPTION": {"MCQ_DUPLICATE_OPTION", "MCQ_DUPLICATE_OPTION_KEYS"},
        "MCQ_DUPLICATE_CONTENT": {"MCQ_DUPLICATE_CONTENT"},
        "MCQ_SOURCE_UNVERIFIED": {"MCQ_SOURCE_UNAUTHORIZED_OR_UNVERIFIED"},
        "CODING_MISSING_STATEMENT": {"CODING_MISSING_STATEMENT"},
        "CODING_AMBIGUOUS_CONTRACT": {"CODING_AMBIGUOUS_CONTRACT"},
        "CODING_MISSING_CONSTRAINTS": {"CODING_MISSING_CONSTRAINTS"},
        "CODING_MISSING_INPUT_FORMAT": {"CODING_MISSING_INPUT_FORMAT"},
        "CODING_MISSING_OUTPUT_FORMAT": {"CODING_MISSING_OUTPUT_FORMAT"},
        "CODING_INVALID_STARTER": {"CODING_INVALID_STARTER"},
        "CODING_MISSING_TEST_CASES": {"CODING_MISSING_TEST_CASES"},
        "CODING_REFERENCE_SOLUTION_INVALID": {"CODING_REFERENCE_SOLUTION_INVALID"},
        "CODING_TEST_VALIDATION_FAILED": {"CODING_TEST_VALIDATION_FAILED"},
        "CODING_SOURCE_UNVERIFIED": {"CODING_SOURCE_UNVERIFIED"},
        "CODING_REFERENCE_SOLUTION_INVALID": {
            "CODING_REFERENCE_SOLUTION_INVALID",
            "CODING_MISSING_TIME_COMPLEXITY",
            "CODING_MISSING_SPACE_COMPLEXITY",
            "CODING_MISSING_SOLUTION_EXPLANATION",
        },
    }
    return sorted(name for name, issue_set in mapped.items() if issue_set.intersection(record["errors"]))


def build_final_records(
    rows: list[dict], docker_ready: bool, governance_audit: dict
) -> list[dict]:
    audit_by_id = {int(row["question_id"]): row for row in governance_audit["questions"]}
    results = []
    for row in rows:
        qid = int(row["question_id"])
        errors = (
            _mcq_issue_codes(row)
            if row["question_type"] == "MCQ"
            else _coding_issue_codes(row, docker_ready)
        )
        audit_row = audit_by_id.get(qid, {})
        governance_errors = audit_row.get("governance_errors", [])
        errors.extend(
            f"GOVERNANCE: {error}"
            for error in governance_errors
            if error not in errors
        )
        errors = sorted(set(errors))
        source_traceable = bool(row.get("source_id") and row.get("source_name")) and (
            row.get("source_question_number") is not None or row.get("source_metadata")
        )
        source_authorized = row.get("source_type") != "SCRAPED"
        warnings = []
        if row["question_type"] == "MCQ":
            warnings.append(
                "The stored answer key has not been independently solved and verified; "
                "no answer or explanation repair is proposed."
            )
        else:
            warnings.append(
                "No contract, constraints, examples, starter code, or test data are "
                "proposed without question-specific semantic review."
            )
        if row["duplicate_group"]:
            warnings.append(
                "Potential duplicate requires individual comparison and governance resolution."
            )
        ready = False
        result = {
            "question_id": qid,
            "source_id": row["source_id"],
            "source_question_number": row["source_question_number"],
            "title": row["title"],
            "question_type": row["question_type"],
            "old_status": row["status"],
            "new_status": (
                "REVIEW"
                if errors and row["status"] == "DRAFT"
                else row["status"]
            ),
            "old_answer_key": row["correct_option_key"],
            "new_answer_key": row["correct_option_key"],
            "old_option_count": len(row["options"]) if row["question_type"] == "MCQ" else None,
            "new_option_count": len(row["options"]) if row["question_type"] == "MCQ" else None,
            "duplicate_group": row["duplicate_groups"] or row["duplicate_matches"],
            "duplicate_resolution": "PENDING" if row["duplicate_group"] else None,
            "old_input_format": row["input_format"],
            "new_input_format": row["input_format"],
            "old_output_format": row["output_format"],
            "new_output_format": row["output_format"],
            "old_constraints": row["constraints_text"],
            "new_constraints": row["constraints_text"],
            "starter_code_created": False,
            "examples_created": 0,
            "public_test_cases": int(row["public_test_case_count"] or 0),
            "hidden_test_cases": int(row["hidden_test_case_count"] or 0),
            "reference_solution_valid": False,
            "expected_outputs_verified": False,
            "starter_code_compiles": False,
            "judge_validated": False,
            "source_traceable": bool(source_traceable),
            "source_authorized": source_authorized,
            "governance_ready": bool(audit_row.get("governance_ready")),
            "publish_ready": bool(ready),
            "repair_status": "BLOCKED_REVIEW" if errors else "UNVERIFIED",
            "errors": errors,
            "warnings": warnings,
            "review_reason": (
                "Content was not modified because the available evidence does not "
                "support a safe repair. Resolve the listed issues with source evidence "
                "and required human/judge verification before considering publication."
            )
            if errors or not ready
            else None,
        }
        result["review_categories"] = _category_codes(result)
        results.append(result)
    return results


def _write_final_reports(records: list[dict], metrics: dict, dry_run: bool) -> None:
    REPORT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    payload = {
        "report_version": "v1",
        "read_only": dry_run,
        "generated_at": datetime.now().astimezone().isoformat(),
        "question_total": len(records),
        "metrics": metrics,
        "records": records,
    }
    FINAL_JSON.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default) + "\n",
        encoding="utf-8",
    )
    with FINAL_CSV.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=FINAL_FIELDS)
        writer.writeheader()
        for row in records:
            writer.writerow(
                {
                    field: (
                        _json_cell(row.get(field))
                        if field in {"errors", "warnings", "duplicate_group"}
                        else row.get(field)
                    )
                    for field in FINAL_FIELDS
                }
            )

    queue_fields = (
        "question_id",
        "question_type",
        "source_id",
        "source_question_number",
        "title",
        "old_status",
        "review_categories",
        "errors",
        "review_reason",
    )
    with REVIEW_QUEUE_CSV.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=queue_fields)
        writer.writeheader()
        for row in records:
            if row["errors"]:
                writer.writerow(
                    {
                        field: (
                            _json_cell(row.get(field))
                            if field in {"review_categories", "errors"}
                            else row.get(field)
                        )
                        for field in queue_fields
                    }
                )


def _question_filter(args) -> tuple[set[int] | None, set[str] | None]:
    ids = None
    if args.question_id:
        try:
            parsed = [int(value.strip()) for value in args.question_id.split(",")]
        except ValueError as error:
            raise ValueError("--question-id must contain comma-separated positive IDs.") from error
        if any(value < 1 for value in parsed) or len(parsed) != len(set(parsed)):
            raise ValueError("--question-id IDs must be positive and unique.")
        ids = set(parsed)
    question_types = {args.type} if args.type else None
    phase_types = {"MCQ"} if args.phase == "mcq" else {"CODING"} if args.phase == "coding" else None
    if question_types and phase_types and not question_types.issubset(phase_types):
        raise ValueError(f"--type conflicts with --phase {args.phase}.")
    return ids, question_types or phase_types


def _filter_records(rows: list[dict], ids, types, source_id, limit) -> list[dict]:
    filtered = [
        row
        for row in rows
        if (ids is None or int(row["question_id"]) in ids)
        and (types is None or row["question_type"] in types)
        and (source_id is None or row["source_id"] == source_id)
    ]
    if ids is not None:
        found_ids = {int(row["question_id"]) for row in filtered}
        missing = sorted(ids - found_ids)
        if missing:
            raise ValueError(f"Question IDs were not selected from the bank: {missing}.")
    return filtered[:limit] if limit is not None else filtered


def _safe_hold_for_review(
    records: list[dict], reviewer_id: int, batch_size: int
) -> dict[str, int]:
    counts: Counter[str] = Counter()
    reviewable_ids = {
        row["question_id"]
        for row in records
        if row["errors"] and row["old_status"] == "DRAFT"
    }
    for start in range(0, len(records), batch_size):
        batch_ids = [
            row["question_id"]
            for row in records[start : start + batch_size]
            if row["question_id"] in reviewable_ids
        ]
        if not batch_ids:
            continue
        records_by_id = {row["question_id"]: row for row in records}
        with engine.begin() as connection:
            reviewer = connection.execute(
                text("""
                    SELECT user_id
                    FROM users
                    WHERE user_id = :reviewer_id
                      AND is_active = TRUE
                      AND role IN ('ADMIN', 'REVIEWER')
                """),
                {"reviewer_id": reviewer_id},
            ).scalar_one_or_none()
            if reviewer is None:
                raise RuntimeError("--reviewer-id must be an active ADMIN or REVIEWER.")
            for question_id in batch_ids:
                current = connection.execute(
                    text("""
                        SELECT question_type, status
                        FROM questions
                        WHERE question_id = :question_id
                        FOR UPDATE
                    """),
                    {"question_id": question_id},
                ).mappings().one_or_none()
                record = records_by_id[question_id]
                if current is None or current["question_type"] != record["question_type"]:
                    raise RuntimeError(
                        f"Question {question_id} changed since the dry-run snapshot."
                    )
                if current["status"] != "DRAFT":
                    counts["status_changed_since_audit"] += 1
                    continue
                existing_marker = connection.execute(
                    text("""
                        SELECT review_id
                        FROM question_reviews
                        WHERE question_id = :question_id
                          AND notes LIKE :marker
                        LIMIT 1
                    """),
                    {
                        "question_id": question_id,
                        "marker": f"{REVIEW_MARKER}%",
                    },
                ).scalar_one_or_none()
                if existing_marker is not None:
                    counts["review_records_already_exist"] += 1
                else:
                    review_data = {
                        "reason_code": record["review_categories"],
                        "reason": record["review_reason"],
                        "missing_or_unverified": record["errors"],
                        "repair_attempted": "Read-only audit; no content field was modified.",
                    }
                    connection.execute(
                        text("""
                            INSERT INTO question_reviews (
                                question_id, reviewer_id, decision, notes
                            )
                            VALUES (
                                :question_id, :reviewer_id, 'PENDING', :notes
                            )
                        """),
                        {
                            "question_id": question_id,
                            "reviewer_id": reviewer_id,
                            "notes": REVIEW_MARKER
                            + json.dumps(review_data, ensure_ascii=False),
                        },
                    )
                    counts["review_records_created"] += 1
                question_governance_service.transition_question_status(
                    connection,
                    question_id,
                    "REVIEW",
                    reviewer_id,
                    note=(
                        "Question-bank remediation audit: unresolved content or "
                        "verification blockers are recorded in question_reviews."
                    ),
                )
                counts["questions_moved_to_review"] += 1
    return dict(counts)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--dry-run", action="store_true", help="Read-only mode (default).")
    modes.add_argument(
        "--apply",
        action="store_true",
        help="Apply only safe governance holds; never synthesize or publish content.",
    )
    parser.add_argument("--type", choices=("MCQ", "CODING"))
    parser.add_argument("--question-id", help="One ID or comma-separated question IDs.")
    parser.add_argument("--source-id", type=int)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--reviewer-id", type=int)
    parser.add_argument(
        "--phase", choices=("mcq", "coding", "verify", "publish"), default=None
    )
    parser.add_argument(
        "--refresh-snapshot",
        action="store_true",
        help="Replace the immutable before-snapshot after explicit review.",
    )
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive.")
    if not 1 <= args.batch_size <= MAX_BATCH_SIZE:
        parser.error(f"--batch-size must be between 1 and {MAX_BATCH_SIZE}.")
    if args.source_id is not None and args.source_id < 1:
        parser.error("--source-id must be positive.")
    if args.reviewer_id is not None and args.reviewer_id < 1:
        parser.error("--reviewer-id must be positive.")
    if args.apply and args.reviewer_id is None:
        if args.phase not in {"publish", "verify"}:
            parser.error("--reviewer-id is required for --apply.")
    return args


def main() -> None:
    args = _parse_args()
    try:
        ids, types = _question_filter(args)
    except ValueError as error:
        raise SystemExit(str(error)) from error

    with engine.connect() as connection:
        database_name, all_rows, historical_counts, duplicate_matches = capture_live_bank(
            connection
        )
    counts_by_type = Counter(row["question_type"] for row in all_rows)
    if len(all_rows) != EXPECTED_TOTAL or dict(counts_by_type) != EXPECTED_BY_TYPE:
        raise RuntimeError(
            "Live bank count safety check failed: "
            f"total={len(all_rows)}, by_type={dict(counts_by_type)}."
        )
    if len({int(row["question_id"]) for row in all_rows}) != len(all_rows):
        raise RuntimeError("Live bank contains duplicate question IDs.")
    write_before_snapshot(
        database_name,
        all_rows,
        historical_counts,
        duplicate_matches,
        refresh=args.refresh_snapshot,
    )

    try:
        selected = _filter_records(all_rows, ids, types, args.source_id, args.limit)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    docker_ready = docker_is_ready()
    bank_audit = audit_question_bank()
    all_final_records = build_final_records(all_rows, docker_ready, bank_audit)
    selected_ids = {int(row["question_id"]) for row in selected}
    selected_final_records = [
        row for row in all_final_records if row["question_id"] in selected_ids
    ]
    if args.apply and args.phase == "publish":
        print(
            "Publication phase is verification-only: this run has no independently "
            "verified content, expected outputs, or source authorization, so it will "
            "not promote any question."
        )

    apply_counts = {}
    status_counts_after = Counter(row["status"] for row in all_rows)
    perform_apply = args.apply and args.phase not in {"publish", "verify"}
    if perform_apply:
        apply_counts = _safe_hold_for_review(
            selected_final_records, args.reviewer_id, args.batch_size
        )
        with engine.connect() as connection:
            _, updated_rows, current_historical_counts, _ = capture_live_bank(connection)
        status_counts_after = Counter(row["status"] for row in updated_rows)
        updated_by_id = {int(row["question_id"]): row for row in updated_rows}
        for result in all_final_records:
            current = updated_by_id[result["question_id"]]
            result["new_status"] = current["status"]
            result["repair_status"] = (
                "MOVED_TO_REVIEW"
                if current["status"] == "REVIEW" and result["old_status"] == "DRAFT"
                else result["repair_status"]
            )
        historical_counts["question_reviews"] = current_historical_counts["question_reviews"]
        historical_counts["question_status_history"] = current_historical_counts[
            "question_status_history"
        ]
    metrics = {
        "database": database_name,
        "total_questions": len(all_rows),
        "question_type_counts": dict(counts_by_type),
        "status_counts_before": dict(Counter(row["status"] for row in all_rows)),
        "status_counts_after": dict(status_counts_after),
        "selected_question_count": len(selected),
        "duplicate_match_records": len(duplicate_matches),
        "docker_judge_available": docker_ready,
        "governance_audit_counts": bank_audit.get("counts", {}),
        "historical_table_counts": historical_counts,
        "review_queue_count": sum(bool(row["errors"]) for row in all_final_records),
        "mcq_answer_keys_unverified": sum(
            "MCQ_ANSWER_NOT_INDEPENDENTLY_VERIFIED" in row["errors"]
            for row in all_final_records
            if row["question_type"] == "MCQ"
        ),
        "mcq_explanations_unverified_or_missing": sum(
            any(
                issue in row["errors"]
                for issue in (
                    "MCQ_EXPLANATION_MISSING",
                    "MCQ_EXPLANATION_NOT_INDEPENDENTLY_VERIFIED",
                )
            )
            for row in all_final_records
            if row["question_type"] == "MCQ"
        ),
        "publish_ready_count": sum(row["publish_ready"] for row in all_final_records),
        "source_traceable_count": sum(
            row["source_traceable"] for row in all_final_records
        ),
        "source_authorized_count": sum(
            row["source_authorized"] for row in all_final_records
        ),
        "review_hold_results": apply_counts,
        "database_content_fields_modified": False,
        "publication_attempted": False,
        "production_eligibility_gate": (
            "Strictly requires individually verified MCQ answers/explanations, "
            "authorized source provenance, coding contract/reference/test verification "
            "in the isolated judge, and governance approval."
        ),
        "dry_run": not perform_apply,
        "requested_apply": args.apply,
        "mcq_answer_keys_repaired": 0,
        "mcq_options_restored": 0,
        "coding_questions_content_repaired": 0,
        "coding_questions_judge_validated": 0,
        "questions_published": 0,
    }
    _write_final_reports(all_final_records, metrics, dry_run=not perform_apply)

    queue_counts = Counter(
        category
        for record in all_final_records
        for category in record["review_categories"]
    )
    summary = {
        "database": database_name,
        "selected": len(selected),
        "total_questions": len(all_rows),
        "question_type_counts": dict(counts_by_type),
        "status_counts_before": dict(Counter(row["status"] for row in all_rows)),
        "issue_counts": bank_audit.get("counts", {}).get("issue_counts", {}),
        "review_queue_categories": dict(sorted(queue_counts.items())),
        "questions_blocked": metrics["review_queue_count"],
        "publish_ready": metrics["publish_ready_count"],
        "docker_judge_available": docker_ready,
        "dry_run": not perform_apply,
        "requested_apply": args.apply,
        "review_hold_results": apply_counts,
        "reports": {
            "before_json": str(BEFORE_JSON),
            "before_csv": str(BEFORE_CSV),
            "final_json": str(FINAL_JSON),
            "final_csv": str(FINAL_CSV),
            "review_queue_csv": str(REVIEW_QUEUE_CSV),
        },
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=_json_default))


if __name__ == "__main__":
    main()
