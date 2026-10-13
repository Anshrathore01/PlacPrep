"""Audit coding questions and conservatively queue unvalidated content for review."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import engine
from app.judge.docker_sandbox import docker_is_ready
from app.services import question_governance_service


EXPECTED_CODING_QUESTION_COUNT = 290
REPORT_DIRECTORY = Path(__file__).resolve().parents[1] / "reports"
DEFAULT_JSON_REPORT = REPORT_DIRECTORY / "coding_question_repair_290.json"
DEFAULT_CSV_REPORT = REPORT_DIRECTORY / "coding_question_repair_290.csv"
REPAIR_MARKER = "CODING_QUESTION_REPAIR_AUDIT:v1:"

CODING_QUESTION_QUERY = """
    SELECT q.question_id, q.source_id, s.source_name, s.source_url,
           q.source_question_number, q.source_metadata, q.content_hash,
           q.question_type, q.track_id, tr.track_name, q.title, q.difficulty,
           q.status, q.created_at, q.updated_at,
           cq.problem_statement, cq.constraints_text, cq.input_format,
           cq.output_format, cq.starter_code, cq.solution_pseudocode,
           cq.solution_explanation, cq.time_complexity, cq.space_complexity,
           cq.solution_visibility,
           st.subtopic_id, st.subtopic_name, t.topic_id, t.topic_name,
           t.track_id AS topic_track_id,
           (SELECT COUNT(*)
            FROM question_examples e
            WHERE e.question_id = q.question_id) AS example_count,
           (SELECT COUNT(*)
            FROM question_examples e
            WHERE e.question_id = q.question_id
              AND TRIM(COALESCE(e.input_data, '')) <> ''
              AND TRIM(COALESCE(e.output_data, '')) <> '') AS complete_example_count,
           (SELECT COUNT(*)
            FROM coding_test_cases tc
            WHERE tc.question_id = q.question_id) AS test_case_count,
           (SELECT COUNT(*)
            FROM coding_test_cases tc
            WHERE tc.question_id = q.question_id
              AND tc.is_hidden = FALSE) AS public_test_case_count,
           (SELECT COUNT(*)
            FROM coding_test_cases tc
            WHERE tc.question_id = q.question_id
              AND tc.is_hidden = TRUE) AS hidden_test_case_count
    FROM questions q
    LEFT JOIN sources s ON s.source_id = q.source_id
    LEFT JOIN tracks tr ON tr.track_id = q.track_id
    LEFT JOIN coding_questions cq ON cq.question_id = q.question_id
    LEFT JOIN question_subtopics qs
      ON qs.question_id = q.question_id AND qs.is_primary = TRUE
    LEFT JOIN subtopics st ON st.subtopic_id = qs.subtopic_id
    LEFT JOIN topics t ON t.topic_id = st.topic_id
    WHERE q.question_type = 'CODING'
    ORDER BY q.question_id
"""


def _decode_json(value):
    if value is None or isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return value


def _has_text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _review_reason(row: dict) -> tuple[str, list[str], list[str]]:
    errors = []
    warnings = []
    content_exists = _has_text(row.get("problem_statement"))
    if not content_exists:
        classification = "C_AMBIGUOUS_OR_INCOMPLETE"
        errors.append(
            "Problem statement is empty; intended task and I/O semantics cannot be established."
        )
    elif not _has_text(row.get("solution_pseudocode")):
        classification = "C_REQUIRES_SEMANTIC_REVIEW"
        errors.append(
            "No solution pseudocode is available to cross-check the intended algorithm."
        )
    else:
        classification = "B_WELL_DEFINED_CANDIDATE_MISSING_METADATA"
        warnings.append(
            "The statement and pseudocode exist, but their semantic agreement has not "
            "been independently established."
        )

    required_fields = {
        "constraints_text": "Constraints are missing.",
        "input_format": "Input contract is missing.",
        "output_format": "Output contract is missing.",
        "starter_code": "C++17 starter code is missing.",
        "solution_pseudocode": "Reference-algorithm pseudocode is missing.",
    }
    for field, message in required_fields.items():
        if not _has_text(row.get(field)):
            errors.append(message)

    if not int(row.get("complete_example_count") or 0):
        errors.append("No complete public examples exist.")
    if not int(row.get("public_test_case_count") or 0):
        errors.append("No public judge test cases exist.")
    if not int(row.get("hidden_test_case_count") or 0):
        errors.append("No hidden judge test cases exist.")
    if int(row.get("example_count") or 0) != int(row.get("complete_example_count") or 0):
        errors.append("One or more stored examples have missing input or output.")
    if not _has_text(row.get("solution_explanation")):
        warnings.append("Solution explanation is missing.")
    if not _has_text(row.get("time_complexity")):
        warnings.append("Time complexity is missing.")
    if not _has_text(row.get("space_complexity")):
        warnings.append("Space complexity is missing.")

    if not row.get("source_id") or not row.get("source_name"):
        errors.append("Source provenance is incomplete.")
    if row.get("source_question_number") is None and not row.get("source_metadata"):
        errors.append("Source question number and source metadata are both missing.")
    if not row.get("topic_id") or not row.get("subtopic_id") or not row.get("track_id"):
        errors.append("Track/topic/subtopic taxonomy mapping is incomplete.")
    elif row.get("track_id") != row.get("topic_track_id"):
        errors.append("Topic taxonomy does not belong to the question track.")

    warnings.append(
        "No input/output contract or test data is proposed by this audit. These must "
        "be derived per problem, independently checked, and executed in the isolated judge."
    )
    return classification, errors, warnings


def _load_rows(connection, question_ids: list[int] | None = None) -> list[dict]:
    rows = [dict(row) for row in connection.execute(text(CODING_QUESTION_QUERY)).mappings()]
    for row in rows:
        row["source_metadata"] = _decode_json(row.get("source_metadata"))
    if question_ids is not None:
        by_id = {int(row["question_id"]): row for row in rows}
        missing = sorted(set(question_ids) - set(by_id))
        if missing:
            raise ValueError(f"Question IDs are not coding questions: {missing}.")
        rows = [by_id[question_id] for question_id in question_ids]
    return rows


def _validate_with_governance(connection, question_id: int) -> list[str]:
    return question_governance_service.validate_question_for_publication(
        connection, question_id
    )


def audit_questions(connection, rows: list[dict], docker_ready: bool) -> list[dict]:
    results = []
    for row in rows:
        question_id = int(row["question_id"])
        classification, errors, warnings = _review_reason(row)
        governance_errors = _validate_with_governance(connection, question_id)
        errors.extend(governance_errors)
        if not docker_ready:
            errors.append(
                "Isolated C++17 judge unavailable (Docker daemon or configured judge image missing)."
            )
        else:
            warnings.append(
                "Judge availability is confirmed; no reference/starter execution has yet "
                "been completed for this question."
            )
        source_metadata = row.get("source_metadata")
        report = {
            "question_id": question_id,
            "source_question_number": row.get("source_question_number"),
            "source_id": row.get("source_id"),
            "source_name": row.get("source_name"),
            "source_url": row.get("source_url"),
            "source_metadata": source_metadata,
            "title": row.get("title"),
            "question_type": row.get("question_type"),
            "topic_name": row.get("topic_name"),
            "subtopic_name": row.get("subtopic_name"),
            "track_name": row.get("track_name"),
            "difficulty": row.get("difficulty"),
            "old_status": row.get("status"),
            "new_status": (
                "REVIEW"
                if errors and row.get("status") in {"DRAFT", "REVIEW"}
                else row.get("status")
            ),
            "classification": classification,
            "problem_statement": row.get("problem_statement"),
            "constraints_text": row.get("constraints_text"),
            "old_input_format": row.get("input_format"),
            "new_input_format": None,
            "old_output_format": row.get("output_format"),
            "new_output_format": None,
            "starter_code_created": False,
            "examples_created": 0,
            "test_cases_created": 0,
            "public_test_cases": int(row.get("public_test_case_count") or 0),
            "hidden_test_cases": int(row.get("hidden_test_case_count") or 0),
            "reference_solution_valid": False,
            "starter_code_compiles": False,
            "test_cases_verified": False,
            "judge_validation_passed": False,
            "governance_ready": not governance_errors,
            "publish_ready": not errors and not governance_errors,
            "errors": sorted(set(errors)),
            "warnings": sorted(set(warnings)),
            "review_reason": (
                "Do not publish: contract reconstruction, representative examples, "
                "public/hidden tests, reference execution, starter compilation, and "
                "isolated judge verification remain incomplete."
            ),
            "existing_metadata": {
                "solution_pseudocode": row.get("solution_pseudocode"),
                "solution_explanation": row.get("solution_explanation"),
                "time_complexity": row.get("time_complexity"),
                "space_complexity": row.get("space_complexity"),
                "solution_visibility": row.get("solution_visibility"),
                "content_hash": row.get("content_hash"),
                "example_count": int(row.get("example_count") or 0),
                "complete_example_count": int(row.get("complete_example_count") or 0),
                "test_case_count": int(row.get("test_case_count") or 0),
            },
        }
        results.append(report)
    return results


def write_report(results: list[dict], json_path: Path, csv_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(
            {
                "question_total": len(results),
                "read_only": True,
                "report_version": "v1",
                "results": results,
            },
            indent=2,
            ensure_ascii=False,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )
    fields = (
        "question_id",
        "question_type",
        "source_id",
        "source_name",
        "source_url",
        "source_question_number",
        "title",
        "topic_name",
        "subtopic_name",
        "track_name",
        "difficulty",
        "old_status",
        "new_status",
        "problem_statement",
        "constraints_text",
        "old_input_format",
        "new_input_format",
        "old_output_format",
        "new_output_format",
        "constraints_text",
        "starter_code_created",
        "examples_created",
        "test_cases_created",
        "public_test_cases",
        "hidden_test_cases",
        "reference_solution_valid",
        "starter_code_compiles",
        "test_cases_verified",
        "judge_validation_passed",
        "governance_ready",
        "publish_ready",
        "classification",
        "errors",
        "warnings",
        "review_reason",
    )
    with csv_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for result in results:
            writer.writerow(
                {
                    key: (
                        json.dumps(result.get(key), ensure_ascii=False)
                        if key in {"errors", "warnings"}
                        else result.get(key)
                    )
                    for key in fields
                }
            )


def _parse_question_ids(value: str | None) -> list[int] | None:
    if value is None:
        return None
    ids = []
    for piece in value.split(","):
        piece = piece.strip()
        if not piece.isdigit() or int(piece) < 1:
            raise argparse.ArgumentTypeError(
                "--question-id must be a comma-separated list of positive IDs."
            )
        ids.append(int(piece))
    if len(ids) != len(set(ids)):
        raise argparse.ArgumentTypeError("--question-id contains duplicate IDs.")
    return ids


def _apply_review_queue(results: list[dict], reviewer_id: int, batch_size: int) -> dict:
    counts = Counter()
    active_reviewer_query = text("""
        SELECT user_id
        FROM users
        WHERE user_id = :reviewer_id
          AND is_active = TRUE
          AND role IN ('ADMIN', 'REVIEWER')
    """)
    for start in range(0, len(results), batch_size):
        batch = results[start : start + batch_size]
        with engine.begin() as connection:
            if connection.execute(
                active_reviewer_query, {"reviewer_id": reviewer_id}
            ).scalar_one_or_none() is None:
                raise RuntimeError("reviewer-id must be an active ADMIN or REVIEWER.")
            for result in batch:
                question_id = result["question_id"]
                current = connection.execute(
                    text("""
                        SELECT question_type, status
                        FROM questions
                        WHERE question_id = :question_id
                        FOR UPDATE
                    """),
                    {"question_id": question_id},
                ).mappings().one_or_none()
                if current is None or current["question_type"] != "CODING":
                    raise RuntimeError(
                        f"Question {question_id} changed or is no longer a coding question."
                    )

                existing = connection.execute(
                    text("""
                        SELECT review_id
                        FROM question_reviews
                        WHERE question_id = :question_id
                          AND notes LIKE :marker
                        ORDER BY review_id DESC
                        LIMIT 1
                    """),
                    {
                        "question_id": question_id,
                        "marker": f"{REPAIR_MARKER}%",
                    },
                ).scalar_one_or_none()
                if existing is not None:
                    counts["reviews_skipped_existing"] += 1
                    continue

                review_data = {
                    "repair_version": "v1",
                    "classification": result["classification"],
                    "errors": result["errors"],
                    "warnings": result["warnings"],
                    "review_reason": result["review_reason"],
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
                        "notes": REPAIR_MARKER
                        + json.dumps(review_data, ensure_ascii=False),
                    },
                )
                if current["status"] == "DRAFT":
                    question_governance_service.transition_question_status(
                        connection,
                        question_id,
                        "REVIEW",
                        reviewer_id,
                        note=(
                            "Coding repair audit: content fields were not changed; "
                            "question queued because contract/test/judge verification "
                            "is outstanding."
                        ),
                    )
                    counts["moved_to_review"] += 1
                else:
                    counts["review_records_created"] += 1
    return dict(counts)


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Audit only (default).")
    mode.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Queue selected coding questions into REVIEW with audit metadata only. "
            "This does not repair content, create tests, execute code, or publish."
        ),
    )
    parser.add_argument(
        "--question-id",
        help="One coding question ID or comma-separated IDs.",
    )
    parser.add_argument("--limit", type=int, help="Limit the selected questions.")
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--reviewer-id", type=int)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_REPORT)
    parser.add_argument("--csv-output", type=Path, default=DEFAULT_CSV_REPORT)
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive.")
    if args.batch_size < 1 or args.batch_size > 25:
        parser.error("--batch-size must be between 1 and 25.")
    if args.apply and args.reviewer_id is None:
        parser.error("--reviewer-id is required with --apply.")

    try:
        question_ids = _parse_question_ids(args.question_id)
    except argparse.ArgumentTypeError as error:
        parser.error(str(error))

    docker_ready = docker_is_ready()
    with engine.connect() as connection:
        all_rows = _load_rows(connection)
        if not args.question_id and len(all_rows) != EXPECTED_CODING_QUESTION_COUNT:
            raise RuntimeError(
                f"Expected {EXPECTED_CODING_QUESTION_COUNT} coding questions, "
                f"found {len(all_rows)}."
            )
        rows = _load_rows(connection, question_ids)
        if args.limit is not None:
            rows = rows[: args.limit]
        results = audit_questions(connection, rows, docker_ready)

    write_report(results, args.json_output, args.csv_output)
    categories = Counter(result["classification"] for result in results)
    totals = {
        "selected": len(results),
        "review_blocked": sum(bool(result["errors"]) for result in results),
        "publish_ready": sum(bool(result["publish_ready"]) for result in results),
        "examples": sum(result["existing_metadata"]["example_count"] for result in results),
        "test_cases": sum(result["existing_metadata"]["test_case_count"] for result in results),
        "public_test_cases": sum(result["public_test_cases"] for result in results),
        "hidden_test_cases": sum(result["hidden_test_cases"] for result in results),
        "docker_judge_available": docker_ready,
        "categories": dict(categories),
        "json_report": str(args.json_output),
        "csv_report": str(args.csv_output),
    }
    if args.apply:
        totals["review_queue_changes"] = _apply_review_queue(
            results, args.reviewer_id, args.batch_size
        )
        totals["read_only"] = False
    else:
        totals["read_only"] = True
    print(json.dumps(totals, indent=2, ensure_ascii=False))
    print("First batch:")
    for result in results[: min(args.batch_size, 20)]:
        print(
            json.dumps(
                {
                    "question_id": result["question_id"],
                    "title": result["title"],
                    "classification": result["classification"],
                    "old_status": result["old_status"],
                    "new_status": result["new_status"],
                    "errors": result["errors"],
                    "proposed_input_format": result["new_input_format"],
                    "proposed_output_format": result["new_output_format"],
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
