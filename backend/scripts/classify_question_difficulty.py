"""Conservative, proposal-only question difficulty classification."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import engine
from app.services import question_governance_service
from app.services.question_governance_service import transition_question_status
from scripts.audit_question_bank import (
    _duplicate_keys,
    classify_mcq_issues,
    has_source_traceability,
    normalize_text,
)


CLASSIFIER_VERSION = "v1"
DIRECT_EASY_PATTERNS = (
    (
        re.compile(r"\bwhat\s+is\s+\d+(?:\.\d+)?\s*%\s+of\s+\d+(?:\.\d+)?\b", re.I),
        "one direct percentage calculation",
    ),
    (
        re.compile(
            r"\bwhat\s+is\s+\d+(?:\.\d+)?\s*[+\-×*/]\s*\d+(?:\.\d+)?\b",
            re.I,
        ),
        "one direct arithmetic operation",
    ),
    (
        re.compile(
            r"\b(?:a\s+)?train\s+travels\s+\d+(?:\.\d+)?\s*km?\s+"
            r"in\s+\d+(?:\.\d+)?\s+hours?.{0,50}\b(?:speed|fast)\b",
            re.I,
        ),
        "direct distance divided by time",
    ),
)
ARITHMETIC_MARKERS = re.compile(r"[=+*/×÷]|(?<!\w)-(?!\w)|→|->")
CONDITION_MARKERS = re.compile(
    r"\b(if|unless|only if|provided that|both|either|neither|all of|"
    r"exactly|at least|at most|not)\b",
    re.I,
)
STEP_TRANSITIONS = re.compile(r"→|->|;|\bthen\b|\bnext\b|\btherefore\b|\bso\b", re.I)
CONCEPT_MARKERS = (
    "average",
    "percentage",
    "profit",
    "ratio",
    "speed",
    "distance",
    "time",
    "probability",
    "equation",
    "sequence",
    "condition",
    "algorithm",
    "complexity",
    "recursion",
    "database",
    "network",
    "security",
    "system",
)


def _source_metadata(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def classify_difficulty(
    *,
    question_text: str | None,
    explanation: str | None,
    topic_name: str | None,
    source_metadata: dict | None = None,
    current_difficulty: str | None = None,
    options: list[str] | None = None,
) -> dict:
    metadata = source_metadata or {}
    source_difficulty = metadata.get("difficulty")
    if source_difficulty in {"EASY", "MEDIUM", "HARD"}:
        evidence = metadata.get("difficulty_source") or metadata.get(
            "difficulty_reference"
        )
        return {
            "proposed_difficulty": source_difficulty,
            "confidence": 0.99 if evidence else 0.91,
            "classification_reason": (
                f"Source metadata explicitly labels this {source_difficulty}; "
                + (
                    f"evidence reference: {evidence}."
                    if evidence
                    else "the imported source tag should be checked by a reviewer."
                )
            ),
            "signals": ["source difficulty metadata"],
        }

    if current_difficulty in {"EASY", "MEDIUM", "HARD"}:
        return {
            "proposed_difficulty": current_difficulty,
            "confidence": 1.0,
            "classification_reason": (
                "The question already has a valid difficulty value; this "
                "classifier preserves it and does not infer a replacement."
            ),
            "signals": ["existing difficulty value"],
        }

    prompt = normalize_text(question_text)
    rationale = normalize_text(explanation)
    direct_rule = next(
        (description for pattern, description in DIRECT_EASY_PATTERNS if pattern.search(prompt)),
        None,
    )
    has_explanation = bool(rationale)
    is_numeric_topic = bool(
        topic_name
        and any(
            word in topic_name.casefold()
            for word in ("quantitative", "data interpretation", "mathematics")
        )
    )
    operation_count = len(ARITHMETIC_MARKERS.findall(rationale))
    condition_count = len(CONDITION_MARKERS.findall(prompt))
    solution_steps = 1 + len(STEP_TRANSITIONS.findall(rationale))
    concept_count = sum(
        concept in f"{prompt} {rationale}" for concept in CONCEPT_MARKERS
    )
    option_tokens = [
        set(re.findall(r"\w+", normalize_text(option)))
        for option in options or []
        if normalize_text(option)
    ]
    distractor_similarity = max(
        (
            len(left & right) / len(left | right)
            for index, left in enumerate(option_tokens)
            for right in option_tokens[index + 1 :]
            if left | right
        ),
        default=0.0,
    )
    feature_signals = [
        f"estimated explanation steps: {solution_steps}",
        f"arithmetic markers: {operation_count}",
        f"prompt condition markers: {condition_count}",
        f"recognized concepts: {concept_count}",
        f"maximum option-token similarity: {distractor_similarity:.2f}",
    ]

    if (
        direct_rule
        and has_explanation
        and is_numeric_topic
        and operation_count <= 6
        and condition_count <= 1
        and solution_steps <= 2
        and (
            direct_rule != "one direct percentage calculation"
            or len(re.findall(r"%\s*of\b", prompt, re.I)) == 1
        )
    ):
        return {
            "proposed_difficulty": "EASY",
            "confidence": 0.92,
            "classification_reason": (
                f"The prompt matches {direct_rule}; the existing explanation "
                "supports a single direct calculation, with no multi-condition "
                "reasoning detected. This is a deterministic heuristic, not "
                "independent answer verification."
            ),
            "signals": [direct_rule, *feature_signals],
        }

    if (
        has_explanation
        and condition_count >= 3
        and solution_steps >= 4
        and operation_count >= 4
    ):
        return {
            "proposed_difficulty": "HARD",
            "confidence": 0.68,
            "classification_reason": (
                "The prompt and existing explanation contain several explicit "
                "conditions, solution transitions, and operations. These "
                "complexity indicators are only a triage signal; expert review "
                "must determine whether the interacting constraints justify HARD."
            ),
            "signals": feature_signals,
        }

    if is_numeric_topic and has_explanation and operation_count >= 2:
        return {
            "proposed_difficulty": "MEDIUM",
            "confidence": 0.78,
            "classification_reason": (
                "The existing explanation contains multiple arithmetic or "
                "transformation markers. This is insufficient to establish "
                "difficulty without expert review."
            ),
            "signals": feature_signals,
        }

    if has_explanation and condition_count >= 2 and solution_steps >= 2:
        return {
            "proposed_difficulty": "MEDIUM",
            "confidence": 0.7,
            "classification_reason": (
                "The prompt has multiple explicit conditions and the explanation "
                "has more than one transition. This heuristic is too uncertain "
                "to establish difficulty without expert review."
            ),
            "signals": feature_signals,
        }

    return {
        "proposed_difficulty": None,
        "confidence": 0.25,
        "classification_reason": (
            "No deterministic, source-backed difficulty rule matched. "
            "Do not infer a label from topic or prompt length alone."
        ),
        "signals": [
            "no source difficulty metadata",
            f"explanation available: {has_explanation}",
            *feature_signals,
        ],
    }


def requires_review(
    confidence: float,
    proposed_difficulty: str | None,
    confidence_threshold: float,
) -> bool:
    return confidence < confidence_threshold or proposed_difficulty is not None


def is_publication_ready(
    *,
    governance_errors: list[str],
    audit_issues: set[str],
    duplicate_content: bool,
    source_traceable: bool,
) -> bool:
    return (
        not governance_errors
        and not audit_issues
        and not duplicate_content
        and source_traceable
    )


def _load_questions(
    connection,
) -> tuple[list[dict], dict[int, list[dict]], dict[int, list[dict]]]:
    rows = [
        dict(row)
        for row in connection.execute(
            text("""
                SELECT q.question_id, q.source_id, s.source_name, s.source_type,
                       s.source_url, q.source_question_number, q.source_metadata,
                       q.question_type, q.track_id AS question_track_id,
                       tr.track_name,
                       q.title, q.difficulty, q.status, q.content_hash,
                       mq.question_text, mq.correct_option_key,
                       mq.is_multiple_correct, mq.explanation
                FROM questions q
                LEFT JOIN sources s ON s.source_id = q.source_id
                LEFT JOIN tracks tr ON tr.track_id = q.track_id
                LEFT JOIN mcq_questions mq ON mq.question_id = q.question_id
                ORDER BY q.question_id
            """)
        ).mappings()
    ]
    mappings_by_question: dict[int, list[dict]] = defaultdict(list)
    for row in connection.execute(
        text("""
            SELECT qs.question_id, qs.subtopic_id, qs.is_primary,
                   st.subtopic_name, st.topic_id, t.topic_name, t.track_id
            FROM question_subtopics qs
            LEFT JOIN subtopics st ON st.subtopic_id = qs.subtopic_id
            LEFT JOIN topics t ON t.topic_id = st.topic_id
            ORDER BY qs.question_id, qs.is_primary DESC, qs.subtopic_id
        """)
    ).mappings():
        mappings_by_question[int(row["question_id"])].append(dict(row))
    for row in rows:
        mappings = mappings_by_question.get(int(row["question_id"]), [])
        primary_mapping = next(
            (mapping for mapping in mappings if mapping["is_primary"]),
            mappings[0] if mappings else {},
        )
        row["topic_id"] = primary_mapping.get("topic_id")
        row["topic_name"] = primary_mapping.get("topic_name")
        row["subtopic_id"] = primary_mapping.get("subtopic_id")
        row["subtopic_name"] = primary_mapping.get("subtopic_name")
    options_by_question: dict[int, list[dict]] = defaultdict(list)
    for row in connection.execute(
        text("""
            SELECT question_id, option_key, option_text, display_order
            FROM mcq_options
            ORDER BY question_id, display_order
        """)
    ).mappings():
        options_by_question[int(row["question_id"])].append(dict(row))
    return rows, options_by_question, mappings_by_question


def _make_report(
    connection,
    *,
    source_filter: str | None,
    track_filter: str | None,
    topic_filter: str | None,
    limit: int | None,
    only_missing: bool,
    confidence_threshold: float,
) -> dict:
    questions, options_by_question, mappings_by_question = _load_questions(connection)
    mcq_rows = [row for row in questions if row["question_type"] == "MCQ"]
    duplicate_hash_ids = _duplicate_keys(
        mcq_rows, lambda row: normalize_text(row.get("content_hash"))
    )
    duplicate_text_ids = _duplicate_keys(
        mcq_rows, lambda row: normalize_text(row.get("question_text"))
    )
    duplicate_ids = duplicate_hash_ids | duplicate_text_ids

    candidates = []
    for row in questions:
        if row["status"] not in {"DRAFT", "REVIEW"}:
            continue
        if source_filter:
            if source_filter.isdigit():
                if int(row["source_id"] or 0) != int(source_filter):
                    continue
            elif source_filter.casefold() not in str(row["source_name"] or "").casefold():
                continue
        if track_filter and track_filter.casefold() != str(row["track_name"] or "").casefold():
            continue
        if topic_filter and topic_filter.casefold() != str(row["topic_name"] or "").casefold():
            continue
        if only_missing and row["difficulty"] is not None:
            continue
        candidates.append(row)
    if limit is not None:
        candidates = candidates[:limit]

    results = []
    for row in candidates:
        question_id = int(row["question_id"])
        metadata = _source_metadata(row["source_metadata"])
        options = options_by_question.get(question_id, [])
        governance_errors = question_governance_service.validate_question_for_publication(
            connection, question_id
        )
        if row["question_type"] == "MCQ":
            audit_issues = set(
                classify_mcq_issues(
                    question_text=row["question_text"],
                    correct_option_key=row["correct_option_key"],
                    is_multiple_correct=bool(row["is_multiple_correct"]),
                    difficulty=row["difficulty"],
                    options=options,
                    mappings=[
                        {
                            "subtopic_id": mapping["subtopic_id"],
                            "topic_id": mapping["topic_id"],
                            "track_id": mapping["track_id"],
                            "question_track_id": row["question_track_id"],
                        }
                        for mapping in mappings_by_question.get(question_id, [])
                    ],
                    duplicate_content=question_id in duplicate_ids,
                )
            )
        else:
            audit_issues = set()
        classification = classify_difficulty(
            question_text=row["question_text"] or row["title"],
            explanation=row["explanation"],
            topic_name=row["topic_name"],
            source_metadata=metadata,
            current_difficulty=row["difficulty"],
            options=[option["option_text"] for option in options],
        )
        trace_number = row["source_question_number"] or metadata.get(
            "source_question_number"
        )
        source_traceable = has_source_traceability(
            source_id=row["source_id"],
            source_name=row["source_name"],
            source_question_number=trace_number,
            source_metadata=metadata,
        )
        publish_ready = is_publication_ready(
            governance_errors=governance_errors,
            audit_issues=audit_issues,
            duplicate_content=question_id in duplicate_ids,
            source_traceable=source_traceable,
        )
        needs_review = requires_review(
            classification["confidence"],
            classification["proposed_difficulty"],
            confidence_threshold,
        )
        results.append(
            {
                "question_id": question_id,
                "current_difficulty": row["difficulty"],
                "proposed_difficulty": classification["proposed_difficulty"],
                "confidence": classification["confidence"],
                "classification_reason": classification["classification_reason"],
                "signals": classification["signals"],
                "source": row["source_name"],
                "source_id": row["source_id"],
                "source_type": row["source_type"],
                "source_url": row["source_url"],
                "source_question_number": trace_number,
                "source_metadata": metadata,
                "track": row["track_name"],
                "topic": row["topic_name"],
                "subtopic": row["subtopic_name"],
                "status": row["status"],
                "recommended_status": (
                    "REVIEW" if needs_review and row["status"] == "DRAFT" else row["status"]
                ),
                "governance_errors": governance_errors,
                "audit_issues": sorted(audit_issues),
                "publication_ready": publish_ready,
            }
        )
    return {
        "read_only": True,
        "classifier_version": CLASSIFIER_VERSION,
        "confidence_semantics": (
            "Deterministic heuristic score, not a calibrated probability; "
            "all proposals require governance review."
        ),
        "confidence_threshold": confidence_threshold,
        "candidate_count": len(results),
        "high_confidence_count": sum(
            result["confidence"] >= confidence_threshold
            and result["proposed_difficulty"] is not None
            for result in results
        ),
        "review_required_count": sum(
            requires_review(
                result["confidence"],
                result["proposed_difficulty"],
                confidence_threshold,
            )
            for result in results
        ),
        "publication_ready_count": sum(
            result["publication_ready"] for result in results
        ),
        "results": results,
    }


def _create_reviews(connection, report: dict, reviewer_id: int) -> dict:
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
        raise RuntimeError("reviewer_id must identify an active ADMIN or REVIEWER.")

    created = 0
    skipped_existing = 0
    skipped_nonreviewable = 0
    for result in report["results"]:
        if result["status"] not in {"DRAFT", "REVIEW"}:
            skipped_nonreviewable += 1
            continue
        question_id = result["question_id"]
        existing = connection.execute(
            text("""
                SELECT review_id
                FROM question_reviews
                WHERE question_id = :question_id
                  AND notes LIKE :prefix
                ORDER BY review_id DESC
                LIMIT 1
            """),
            {
                "question_id": question_id,
                "prefix": f"QUESTION_CLASSIFICATION:{CLASSIFIER_VERSION}:%",
            },
        ).scalar_one_or_none()
        if existing is not None:
            skipped_existing += 1
            continue

        review_payload = {
            "proposed_difficulty": result["proposed_difficulty"],
            "confidence": result["confidence"],
            "classification_reason": result["classification_reason"],
            "signals": result["signals"],
            "source": result["source"],
            "source_question_number": result["source_question_number"],
            "source_id": result["source_id"],
            "source_type": result["source_type"],
            "source_url": result["source_url"],
            "source_metadata": result["source_metadata"],
            "governance_errors": result["governance_errors"],
            "publication_ready": result["publication_ready"],
        }
        notes = (
            f"QUESTION_CLASSIFICATION:{CLASSIFIER_VERSION}:"
            + json.dumps(review_payload, sort_keys=True, ensure_ascii=False)
        )
        connection.execute(
            text("""
                INSERT INTO question_reviews (
                    question_id, reviewer_id, decision, quality_score, notes
                )
                VALUES (
                    :question_id, :reviewer_id, 'PENDING', :quality_score, :notes
                )
            """),
            {
                "question_id": question_id,
                "reviewer_id": reviewer_id,
                "quality_score": round(result["confidence"] * 100, 2),
                "notes": notes,
            },
        )
        status = result["status"]
        if status == "DRAFT":
            transition_question_status(
                connection,
                question_id,
                "REVIEW",
                reviewer_id,
                note=(
                    "Queued for conservative difficulty and content review; "
                    "classification is a proposal and does not publish or set "
                    "difficulty."
                ),
            )
        created += 1
    return {
        "reviews_created": created,
        "reviews_skipped_as_existing": skipped_existing,
        "reviews_skipped_nonreviewable_status": skipped_nonreviewable,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Do not create review records.")
    parser.add_argument("--source", help="Filter by source ID or source name.")
    parser.add_argument("--track", help="Filter by exact track name.")
    parser.add_argument("--topic", help="Filter by exact topic name.")
    parser.add_argument("--limit", type=int, help="Maximum number of question records.")
    parser.add_argument("--only-missing", action="store_true", help="Only include NULL difficulty.")
    parser.add_argument("--output", type=Path, help="Write the JSON report to this path.")
    parser.add_argument(
        "--confidence-threshold",
        type=float,
        default=0.9,
        help="Confidence required to count a proposal as high-confidence (default: 0.9).",
    )
    parser.add_argument(
        "--create-reviews",
        action="store_true",
        help="Persist idempotent PENDING reviews and move DRAFT questions to REVIEW.",
    )
    parser.add_argument(
        "--reviewer-id",
        type=int,
        help="Active ADMIN/REVIEWER user ID required with --create-reviews.",
    )
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be a positive integer.")
    if not 0 <= args.confidence_threshold <= 1:
        parser.error("--confidence-threshold must be between 0 and 1.")
    if args.create_reviews and args.reviewer_id is None:
        parser.error("--reviewer-id is required with --create-reviews.")

    context = (
        engine.begin()
        if args.create_reviews and not args.dry_run
        else engine.connect()
    )
    with context as connection:
        report = _make_report(
            connection,
            source_filter=args.source,
            track_filter=args.track,
            topic_filter=args.topic,
            limit=args.limit,
            only_missing=args.only_missing,
            confidence_threshold=args.confidence_threshold,
        )
        if args.create_reviews and not args.dry_run:
            report["read_only"] = False
            report["review_writes"] = _create_reviews(
                connection, report, args.reviewer_id
            )

    rendered = json.dumps(report, indent=2, default=str, ensure_ascii=False)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
        print(json.dumps({key: value for key, value in report.items() if key != "results"}, default=str))
    else:
        print(rendered)


if __name__ == "__main__":
    main()
