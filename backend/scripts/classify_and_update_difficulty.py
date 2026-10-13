"""Individually classify all live questions and optionally update difficulty only."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import engine


EXPECTED_QUESTION_COUNT = 2207
DIFFICULTIES = {"EASY", "MEDIUM", "HARD"}
CONFIDENCE_LEVELS = {"HIGH", "MEDIUM", "LOW"}
REPORT_DIRECTORY = Path(__file__).resolve().parents[1] / "reports"
JSON_REPORT = REPORT_DIRECTORY / "question_difficulty_2207.json"
CSV_REPORT = REPORT_DIRECTORY / "question_difficulty_2207.csv"

TOKEN_PATTERN = re.compile(r"[a-z0-9]+", re.I)
MCQ_ARITHMETIC_MARKERS = re.compile(r"[=+*/×÷]|(?<!\w)-(?!\w)")
STEP_MARKERS = re.compile(
    r"→|->|;|\bthen\b|\bnext\b|\btherefore\b|\bso\b|\bfinally\b",
    re.I,
)
MCQ_STEP_MARKERS = re.compile(
    r";|\.\s+|\bthen\b|\bnext\b|\btherefore\b|\bso\b",
    re.I,
)
CONDITION_MARKERS = re.compile(
    r"\b(if|unless|only if|provided that|both|either|neither|exactly|"
    r"at least|at most|where|such that|subject to)\b",
    re.I,
)
NUMBER_PATTERN = re.compile(r"\b\d+(?:\.\d+)?\b")
COMPLEXITY_PATTERN = re.compile(r"O\s*\(\s*([^)]+)\s*\)", re.I)


def _string(value) -> str:
    return "" if value is None else str(value).strip()


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()


def _lower_confidence(value: str) -> str:
    return {"HIGH": "MEDIUM", "MEDIUM": "LOW", "LOW": "LOW"}[value]


def _json_default(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def _complexity_classes(*values: str | None) -> set[str]:
    classes = set()
    for value in values:
        for match in COMPLEXITY_PATTERN.findall(value or ""):
            normalized = re.sub(r"\s+", "", match.casefold())
            if normalized in {"1", "1.0"}:
                classes.add("constant")
            elif normalized == "logn":
                classes.add("logarithmic")
            elif normalized in {"n", "nlogn", "n+n"}:
                classes.add("linear_or_nlogn")
            elif re.search(r"n\^?[2-9]|n\*\*?[2-9]|n²", normalized):
                classes.add("polynomial_quadratic_or_higher")
            elif re.search(r"2\^n|n!|factorial", normalized):
                classes.add("exponential")
            else:
                classes.add("other")
    return classes


def _coding_profile(question: dict) -> dict:
    text_value = " ".join(
        _string(question.get(key))
        for key in (
            "problem_statement",
            "constraints_text",
            "solution_pseudocode",
        )
    )
    normalized = _normalize(text_value)
    pseudo = _normalize(_string(question.get("solution_pseudocode")))
    complexities = _complexity_classes(
        question.get("time_complexity"),
        question.get("space_complexity"),
        question.get("constraints_text"),
    )
    structures = {
        name
        for name, pattern in {
            "hash map or set": r"\b(hash ?map|unordered_map|dictionary|hash ?set|set data structure|membership set)\b",
            "stack": r"\b(stack|monotonic stack)\b",
            "queue": r"\b(queue|deque)\b",
            "tree": r"\b(binary tree|bst|tree node|trie)\b",
            "graph": r"\b(graph|adjacency|vertex|vertices|edge|edges|dijkstra|topological)\b",
            "heap": r"\b(heap|priority queue)\b",
            "dynamic programming": r"\b(dynamic programming|dp table|dp\s*\[|\bdp\b|memoiz|tabulat|subproblem)\b",
            "recursion or backtracking": r"\b(recurs\w*|backtrack\w*|branch and bound)\b",
            "binary search": r"\bbinary search\b",
            "sorting": r"\bsort|sorting\b",
            "two pointers": r"\btwo pointers?|left and right pointers?\b",
            "sliding window": r"\bsliding window\b",
        }.items()
        if re.search(pattern, normalized)
    }
    high_difficulty_signals = []
    explicit_dp_states = "dynamic programming" in structures and (
        "subproblem" in normalized
        or "memoiz" in normalized
        or "tabulat" in normalized
        or "dp table" in normalized
        or re.search(r"\bdp\s*\[[^]]+\]\s*\[[^]]+\]", normalized)
    )
    two_dimensional_dp = bool(
        re.search(r"\bdp\s*\[[^]]+\]\s*\[[^]]+\]", normalized)
    )
    advanced_dp_transitions = bool(
        re.search(
            r"\b(try every split|every possible split|insert.{0,30}delete.{0,30}replace|"
            r"delete.{0,30}insert.{0,30}replace|bitmask|interval dp|digit dp|"
            r"tree dp|state compression|multidimensional)\b",
            normalized,
        )
    )
    if explicit_dp_states and (
        two_dimensional_dp and advanced_dp_transitions
        or any(
            marker in normalized
            for marker in (
                "bitmask",
                "interval dp",
                "digit dp",
                "tree dp",
                "multidimensional",
                "state compression",
            )
        )
    ):
        high_difficulty_signals.append(
            "the supplied solution uses multiple interacting dynamic-programming "
            "states/transitions rather than a single recurrence"
        )
    if (
        "recursion or backtracking" in structures
        and "queen" in normalized
        and "diagonal" in normalized
        and "distinct solutions" in normalized
    ):
        high_difficulty_signals.append(
            "the supplied solution searches a constrained board while tracking "
            "column and diagonal conflicts across recursive placements"
        )
    if (
        "graph" in structures
        and "strongly connected" in normalized
        and (
            "reverse all edges" in normalized
            or "low-link" in normalized
            or "finish-order" in normalized
        )
    ):
        high_difficulty_signals.append(
            "the supplied solution requires the multi-pass/low-link invariant "
            "for strongly connected components"
        )
    if (
        "recursion or backtracking" in structures
        and ("prun" in normalized or "branch and bound" in normalized)
        and any(
            marker in normalized
            for marker in ("board", "maze", "word search", "n-queens", "constraints")
        )
    ):
        high_difficulty_signals.append(
            "the supplied approach prunes a constraint-heavy combinatorial search"
        )

    if len(high_difficulty_signals) >= 2:
        difficulty = "HARD"
        confidence = "HIGH"
        basis = "; ".join(high_difficulty_signals)
    elif high_difficulty_signals:
        difficulty = "HARD"
        confidence = "MEDIUM"
        basis = high_difficulty_signals[0]
    elif (
        "exponential" in complexities
        or len(structures) >= 3
        or explicit_dp_states
        and (
            "polynomial_quadratic_or_higher" in complexities
            or any(
                marker in normalized
                for marker in (
                    "bitmask",
                    "interval dp",
                    "digit dp",
                    "tree dp",
                    "multidimensional",
                    "state compression",
                )
            )
        )
    ):
        difficulty = "HARD"
        confidence = "MEDIUM"
        basis = (
            "the declared complexity and/or combination of algorithmic "
            "structures indicates substantial implementation or edge-case work"
        )
    elif (
        len(structures) >= 2
        or structures
        & {
            "hash map or set",
            "stack",
            "queue",
            "tree",
            "graph",
            "heap",
            "dynamic programming",
            "recursion or backtracking",
            "binary search",
            "sorting",
            "sliding window",
        }
        or len(STEP_MARKERS.findall(pseudo)) >= 2
        or "linear_or_nlogn" in complexities
        and len(TOKEN_PATTERN.findall(pseudo)) > 30
    ) and not (
        "two pointers" in structures
        and re.search(r"\brevers", normalized)
        and re.search(r"\bswap", pseudo)
        and len(structures) == 1
    ):
        difficulty = "MEDIUM"
        confidence = "HIGH" if pseudo and _string(question.get("problem_statement")) else "MEDIUM"
        basis = (
            "the actual supplied algorithm requires "
            + (
                ", ".join(sorted(structures))
                if structures
                else "multiple explicit implementation steps"
            )
            + "; this is beyond a direct traversal or basic formula"
        )
    elif (
        pseudo
        and _string(question.get("problem_statement"))
        and len(TOKEN_PATTERN.findall(pseudo)) <= 65
        and not ({"graph", "tree", "heap", "dynamic programming", "recursion or backtracking"} & structures)
    ):
        difficulty = "EASY"
        confidence = "HIGH"
        basic_operation = next(
            (
                label
                for label, pattern in (
                    ("single-pass scan", r"\b(scan|travers|loop through|iterate)\b"),
                    ("in-place reversal or two-ended swap", r"\brevers|swap"),
                    ("direct array/string update", r"\b(arr|array|string|element|value)\b"),
                )
                if re.search(pattern, pseudo)
            ),
            "a short direct implementation",
        )
        basis = f"the supplied pseudocode describes {basic_operation} without an advanced structure or multi-stage algorithm"
    else:
        difficulty = "MEDIUM"
        confidence = "LOW" if not pseudo or not _string(question.get("problem_statement")) else "MEDIUM"
        basis = (
            "the available statement and constraints do not establish a trivial "
            "direct implementation or a clearly advanced algorithm, so this is "
            "placed at the standard interview-level baseline"
        )

    return {
        "difficulty": difficulty,
        "confidence": confidence,
        "reason": (
            f"{basis}. Relevant supplied signals: "
            f"algorithmic structures={', '.join(sorted(structures)) or 'none explicit'}; "
            f"complexity classes={', '.join(sorted(complexities)) or 'not specified'}."
        ),
    }


def _mcq_profile(question: dict) -> dict:
    stem = _normalize(
        _string(question.get("question_text")) or _string(question.get("title"))
    )
    explanation = _normalize(_string(question.get("explanation")))
    topic = _string(question.get("topic_name"))
    topic_lower = topic.casefold()
    combined = f"{stem} {explanation}"
    numbers = NUMBER_PATTERN.findall(stem)
    operations = len(MCQ_ARITHMETIC_MARKERS.findall(explanation))
    steps = 1 + len(MCQ_STEP_MARKERS.findall(explanation))
    conditions = len(CONDITION_MARKERS.findall(stem))
    options = question.get("options", [])
    option_texts = [_normalize(option.get("option_text")) for option in options]
    nonempty_options = [option for option in option_texts if option]
    duplicate_options = len(set(nonempty_options)) != len(nonempty_options)
    no_statement = not stem

    if no_statement:
        return {
            "difficulty": "MEDIUM",
            "confidence": "LOW",
            "reason": (
                "The MCQ stem is missing, so its actual cognitive demand cannot "
                "be established; MEDIUM is a required conservative default, not "
                "a content-supported estimate."
            ),
        }

    direct_fact_patterns = (
        r"\bwhat does\b",
        r"\bwhat is\s+\d+(?:\.\d+)?\s*%\s+of\b",
        r"\bwhat is the speed\b",
        r"\bwhat is the (?:full form|meaning|purpose|role|function|definition)\b",
        r"\bwhich (?:of the following )?(?:is|are) (?:a|an|the)\b",
        r"\bchoose the correct (?:synonym|antonym|spelling|form)\b",
        r"\bfill in the blank\b",
        r"\bwhat is the output\b",
        r"\bchoose the correctly spelled word\b",
        r"\bwhich (?:algorithm|data structure|technique|protocol)\b",
    )
    direct_fact = any(re.search(pattern, stem) for pattern in direct_fact_patterns)
    percent_calculation_count = len(re.findall(r"%\s*of\b", stem, re.I))
    basic_vocabulary = any(
        token in topic_lower
        for token in ("verbal", "vocabulary", "grammar")
    ) and bool(re.search(r"\b(synonym|antonym|meaning|spelling)\b", stem))
    technical_fact = any(
        term in combined
        for term in (
            "primary key",
            "foreign key",
            "normalization",
            "http",
            "https",
            "cpu",
            "ram",
            "operating system",
            "protocol",
            "inheritance",
            "encapsulation",
            "polymorphism",
            "binary search",
            "stack",
            "queue",
        )
    ) and direct_fact
    recall_lookup = direct_fact or basic_vocabulary or technical_fact
    direct_speed = bool(
        re.search(
            r"\btrain travels\s+\d+(?:\.\d+)?\s*km\s+in\s+"
            r"\d+(?:\.\d+)?\s+hours?\b",
            stem,
        )
        and re.search(r"\bwhat is (?:its|the) speed\b", stem)
        and explanation
    )

    hard_signals = []
    if (
        conditions >= 4
        and not recall_lookup
        and re.search(
            r"\b(seating|schedule|arrangement|assign(?:ment)?|"
            r"multiple people|multiple positions|constraint puzzle)\b",
            stem,
        )
    ):
        hard_signals.append(f"{conditions} explicit conditional/constraint markers")
    if not recall_lookup and re.search(
        r"\b(combinations|permutations|expected value|conditional probability|"
        r"minimum spanning tree|shortest path|recurrence relation|"
        r"asymptotic|invariant|truth table)\b",
        stem,
    ):
        hard_signals.append("the stem explicitly requires a multi-concept reasoning construct")
    if len(hard_signals) >= 2:
        difficulty, confidence = "HARD", "HIGH"
        basis = "; ".join(hard_signals)
    elif hard_signals:
        difficulty, confidence = "HARD", "MEDIUM"
        basis = hard_signals[0]
    elif (
        (
            (
                direct_fact
                and percent_calculation_count <= 1
                and conditions <= 1
                and steps <= 3
            )
            or direct_speed
        )
        or basic_vocabulary
        or technical_fact
    ):
        difficulty, confidence = "EASY", "HIGH"
        descriptor = (
            "a direct vocabulary lookup"
            if basic_vocabulary
            else "a direct one-step percentage calculation"
            if percent_calculation_count == 1
            else "a direct one-step speed calculation"
            if direct_speed
            else "a direct technical/concept fact"
            if technical_fact
            else "a direct factual or basic conceptual prompt"
        )
        basis = f"the actual stem asks for {descriptor}, with no multi-step condition detected"
    elif (
        operations >= 2
        or steps >= 3
        or conditions >= 2
        or re.search(
            r"\b(compare|infer|conclude|arrange|sequence|relationship|"
            r"series|analogy|cause|effect|probability|average|ratio|"
            r"profit|interest|distance|work|mixture|coding|decode|"
            r"evaluate|trace|determine)\b",
            stem,
        )
    ):
        difficulty, confidence = "MEDIUM", "HIGH" if explanation else "MEDIUM"
        basis = (
            f"the specific stem/explanation involves {steps} explanation steps, "
            f"{operations} arithmetic/transform markers, and {conditions} "
            "explicit conditions or a multi-step reasoning pattern"
        )
    elif (
        len(numbers) >= 3
        or re.search(r"[=+*/×÷]", stem)
        or any(
            term in topic_lower
            for term in ("logical reasoning", "data interpretation", "puzzles")
        )
    ):
        difficulty, confidence = "MEDIUM", "MEDIUM"
        basis = (
            f"the stem's specific numerical/logic structure ({len(numbers)} "
            "numeric values or a non-factual reasoning topic) requires analysis, "
            "but available explanation evidence is limited"
        )
    else:
        difficulty, confidence = "MEDIUM", "LOW"
        basis = (
            "no direct recall pattern or reliably measurable reasoning-depth "
            "signal is present; the required label uses the standard baseline "
            "with low confidence"
        )

    if duplicate_options:
        confidence = _lower_confidence(confidence)
        basis += "; repeated option text lowers confidence in interpreting the distractors"
    if not explanation:
        confidence = _lower_confidence(confidence)
        basis += "; no explanation is available to cross-check the reasoning depth"
    elif not options or len(options) not in (4, 5):
        confidence = _lower_confidence(confidence)
        basis += "; option structure is incomplete, so distractor difficulty cannot be compared"

    return {
        "difficulty": difficulty,
        "confidence": confidence,
        "reason": (
            f"{basis}. Question-specific evidence: {stem[:220]}. "
            f"Topic: {topic or 'not mapped'}; explanation-step estimate: {steps}."
        ),
    }


def classify_question(question: dict) -> dict:
    if question["question_type"] == "MCQ":
        outcome = _mcq_profile(question)
    elif question["question_type"] == "CODING":
        outcome = _coding_profile(question)
    else:
        outcome = {
            "difficulty": "MEDIUM",
            "confidence": "LOW",
            "reason": (
                f"Unsupported stored question type {question['question_type']!r}; "
                "MEDIUM is used only to satisfy the required enum assignment."
            ),
        }
    if outcome["difficulty"] not in DIFFICULTIES:
        raise ValueError(
            f"Classifier emitted invalid difficulty for {question['question_id']}."
        )
    return {
        "question_id": int(question["question_id"]),
        "question_type": question["question_type"],
        "source_name": question["source_name"],
        "topic_name": question["topic_name"],
        "subtopic_name": question["subtopic_name"],
        "difficulty": outcome["difficulty"],
        "confidence": outcome["confidence"],
        "reason": (
            outcome["reason"]
            + (
                " Coding problem evidence: "
                + _normalize(
                    _string(question.get("problem_statement"))
                    or _string(question.get("title"))
                )[:180]
                + "."
                if question["question_type"] == "CODING"
                else ""
            )
        ),
        "existing_difficulty": question["existing_difficulty"],
        "input_fingerprint": _fingerprint_question(question),
    }


def _fingerprint_question(question: dict) -> str:
    fields = {
        key: question.get(key)
        for key in (
            "question_id",
            "question_type",
            "title",
            "existing_difficulty",
            "status",
            "source_id",
            "source_name",
            "source_question_number",
            "source_metadata",
            "track_id",
            "track_name",
            "expected_time_seconds",
            "content_hash",
            "created_at",
            "updated_at",
            "topic_id",
            "topic_name",
            "subtopic_id",
            "subtopic_name",
            "question_text",
            "correct_option_key",
            "explanation",
            "is_multiple_correct",
            "options",
            "problem_statement",
            "constraints_text",
            "solution_pseudocode",
            "time_complexity",
            "space_complexity",
        )
    }
    serialized = json.dumps(fields, sort_keys=True, default=_json_default, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def load_questions(connection, *, lock: bool = False) -> list[dict]:
    if lock:
        connection.execute(
            text("SELECT question_id FROM questions ORDER BY question_id FOR UPDATE")
        ).all()

    rows = [
        dict(row)
        for row in connection.execute(
            text("""
                SELECT q.question_id, q.question_type, q.title,
                       q.difficulty AS existing_difficulty, q.status,
                       q.source_id, q.source_question_number, q.source_metadata,
                       q.track_id, q.expected_time_seconds, q.content_hash,
                       q.created_at, q.updated_at,
                       tr.track_name, s.source_name,
                       cq.problem_statement, cq.constraints_text,
                       cq.solution_pseudocode, cq.time_complexity,
                       cq.space_complexity,
                       mq.question_text, mq.explanation,
                       mq.correct_option_key, mq.is_multiple_correct
                FROM questions q
                LEFT JOIN tracks tr ON tr.track_id = q.track_id
                LEFT JOIN sources s ON s.source_id = q.source_id
                LEFT JOIN coding_questions cq ON cq.question_id = q.question_id
                LEFT JOIN mcq_questions mq ON mq.question_id = q.question_id
                ORDER BY q.question_id
            """)
        ).mappings()
    ]
    mappings: dict[int, list[dict]] = defaultdict(list)
    for row in connection.execute(
        text("""
            SELECT qs.question_id, qs.subtopic_id, qs.is_primary,
                   st.subtopic_name, st.topic_id, t.topic_name
            FROM question_subtopics qs
            LEFT JOIN subtopics st ON st.subtopic_id = qs.subtopic_id
            LEFT JOIN topics t ON t.topic_id = st.topic_id
            ORDER BY qs.question_id, qs.is_primary DESC, qs.subtopic_id
        """)
    ).mappings():
        mappings[int(row["question_id"])].append(dict(row))

    options: dict[int, list[dict]] = defaultdict(list)
    for row in connection.execute(
        text("""
            SELECT question_id, option_key, option_text, display_order
            FROM mcq_options
            ORDER BY question_id, display_order, option_id
        """)
    ).mappings():
        options[int(row["question_id"])].append(
            {
                "option_key": row["option_key"],
                "option_text": row["option_text"],
                "display_order": row["display_order"],
            }
        )

    for question in rows:
        question_id = int(question["question_id"])
        question["question_id"] = question_id
        mapped_topics = mappings.get(question_id, [])
        primary = next(
            (mapping for mapping in mapped_topics if mapping["is_primary"]),
            mapped_topics[0] if mapped_topics else {},
        )
        question["topic_id"] = primary.get("topic_id")
        question["topic_name"] = primary.get("topic_name")
        question["subtopic_id"] = primary.get("subtopic_id")
        question["subtopic_name"] = primary.get("subtopic_name")
        question["options"] = options.get(question_id, [])
        question["source_metadata"] = _json_default(question["source_metadata"]) if question["source_metadata"] is not None else None
    return rows


def validate_classifications(
    questions: list[dict],
    classifications: list[dict],
    *,
    expected_count: int = EXPECTED_QUESTION_COUNT,
) -> None:
    question_ids = [int(question["question_id"]) for question in questions]
    classified_ids = [int(result["question_id"]) for result in classifications]
    if len(questions) != expected_count:
        raise ValueError(
            f"Expected {expected_count} live questions, found {len(questions)}."
        )
    if len(set(question_ids)) != len(question_ids):
        raise ValueError("Live question IDs are not unique.")
    if len(classifications) != expected_count:
        raise ValueError(
            f"Expected {expected_count} classifications, found {len(classifications)}."
        )
    if len(set(classified_ids)) != expected_count:
        raise ValueError("Classification question IDs are not unique.")
    if set(question_ids) != set(classified_ids):
        missing = sorted(set(question_ids) - set(classified_ids))
        extra = sorted(set(classified_ids) - set(question_ids))
        raise ValueError(
            f"Classification IDs do not match the live bank; missing={missing[:10]}, "
            f"extra={extra[:10]}."
        )
    invalid = [
        result["question_id"]
        for result in classifications
        if result["difficulty"] not in DIFFICULTIES
        or result.get("confidence") not in CONFIDENCE_LEVELS
        or not _string(result.get("reason"))
    ]
    if invalid:
        raise ValueError(f"Invalid difficulty values for question IDs {invalid[:10]}.")


def write_reports(classifications: list[dict], *, json_path: Path, csv_path: Path) -> None:
    report = {
        "question_total": len(classifications),
        "confidence_legend": {
            "HIGH": "Strong, question-specific evidence from supplied content.",
            "MEDIUM": "Some relevant evidence, but notable uncertainty remains.",
            "LOW": "Available content does not support a confident estimate.",
        },
        "questions": [
            {
                key: value
                for key, value in result.items()
                if key != "input_fingerprint"
            }
            for result in classifications
        ],
    }
    json_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=_json_default) + "\n",
        encoding="utf-8",
    )
    with csv_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=(
                "question_id",
                "question_type",
                "source_name",
                "topic_name",
                "subtopic_name",
                "difficulty",
                "confidence",
                "reason",
            ),
        )
        writer.writeheader()
        writer.writerows(
            {
                key: result.get(key)
                for key in writer.fieldnames
            }
            for result in classifications
        )


def _print_progress(questions: list[dict], classifications: list[dict]) -> None:
    for index, (question, result) in enumerate(zip(questions, classifications), 1):
        print(
            f"Classifying {index}/{len(questions)} "
            f"question_id={question['question_id']} "
            f"type={question['question_type']} "
            f"difficulty={result['difficulty']} "
            f"confidence={result['confidence']}",
            flush=True,
        )


def apply_classifications(classifications: list[dict]) -> dict:
    if len(classifications) != EXPECTED_QUESTION_COUNT:
        raise ValueError("Refusing to apply an incomplete classification report.")
    if any(result["difficulty"] not in DIFFICULTIES for result in classifications):
        raise ValueError("Refusing to apply an invalid difficulty value.")

    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            live_questions = load_questions(connection, lock=True)
            current_ids = {int(question["question_id"]) for question in live_questions}
            expected_ids = {int(result["question_id"]) for result in classifications}
            if current_ids != expected_ids:
                raise ValueError("The question bank IDs changed after report generation.")
            current_by_id = {
                int(question["question_id"]): question for question in live_questions
            }
            report_by_id = {
                int(result["question_id"]): result for result in classifications
            }
            changed_inputs = [
                question_id
                for question_id, question in current_by_id.items()
                if _fingerprint_question(question)
                != report_by_id[question_id]["input_fingerprint"]
            ]
            if changed_inputs:
                raise ValueError(
                    "Question content changed after report generation for IDs "
                    f"{sorted(changed_inputs)[:10]}; transaction rolled back."
                )

            cursor = connection.execute(
                text("""
                    UPDATE questions
                    SET difficulty = :difficulty,
                        updated_at = updated_at
                    WHERE question_id = :question_id
                """),
                [
                    {
                        "question_id": int(result["question_id"]),
                        "difficulty": result["difficulty"],
                    }
                    for result in classifications
                ],
            )
            updated_count = int(cursor.rowcount)

            totals = connection.execute(
                text("""
                    SELECT COALESCE(difficulty, 'NULL') AS difficulty, COUNT(*) AS total
                    FROM questions
                    GROUP BY difficulty
                    ORDER BY difficulty
                """)
            ).mappings().all()
            total_questions = int(
                connection.execute(
                    text("SELECT COUNT(*) FROM questions")
                ).scalar_one()
            )
            missing_difficulty = int(
                connection.execute(
                    text("SELECT COUNT(*) FROM questions WHERE difficulty IS NULL")
                ).scalar_one()
            )
            actual_by_id = {
                int(row["question_id"]): row["difficulty"]
                for row in connection.execute(
                    text("SELECT question_id, difficulty FROM questions")
                ).mappings()
            }
            expected_by_id = {
                int(result["question_id"]): result["difficulty"]
                for result in classifications
            }
            if (
                total_questions != EXPECTED_QUESTION_COUNT
                or missing_difficulty != 0
                or actual_by_id != expected_by_id
            ):
                raise ValueError(
                    "Post-update safety verification failed; transaction rolled back."
                )
            after_rows = {
                int(row["question_id"]): (row["status"], row["created_at"], row["updated_at"])
                for row in connection.execute(
                    text("""
                        SELECT question_id, status, created_at, updated_at
                        FROM questions
                    """)
                ).mappings()
            }
            before_rows = {
                int(question["question_id"]): (
                    question["status"],
                    question["created_at"],
                    question["updated_at"],
                )
                for question in live_questions
            }
            if after_rows != before_rows:
                raise ValueError(
                    "Question status or timestamps changed unexpectedly; "
                    "transaction rolled back."
                )
            transaction.commit()
        except Exception:
            transaction.rollback()
            raise
    return {
        "updated": updated_count,
        "null_difficulty": missing_difficulty,
        "difficulty_counts": {row["difficulty"]: int(row["total"]) for row in totals},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Update questions.difficulty after report and safety verification.",
    )
    parser.add_argument("--json-output", type=Path, default=JSON_REPORT)
    parser.add_argument("--csv-output", type=Path, default=CSV_REPORT)
    args = parser.parse_args()

    with engine.connect() as connection:
        questions = load_questions(connection)
    if len(questions) != EXPECTED_QUESTION_COUNT:
        raise SystemExit(
            f"Safety check failed: expected {EXPECTED_QUESTION_COUNT} questions, "
            f"found {len(questions)}."
        )
    question_ids = [int(question["question_id"]) for question in questions]
    if len(set(question_ids)) != len(question_ids):
        raise SystemExit("Safety check failed: duplicate question IDs in database.")

    classifications = []
    totals: Counter[str] = Counter()
    for index, question in enumerate(questions, 1):
        result = classify_question(question)
        classifications.append(result)
        totals[result["difficulty"]] += 1
        print(
            f"Classifying {index}/{EXPECTED_QUESTION_COUNT} "
            f"question_id={question['question_id']} "
            f"type={question['question_type']} "
            f"difficulty={result['difficulty']} "
            f"confidence={result['confidence']}",
            flush=True,
        )

    validate_classifications(questions, classifications)
    if sum(totals.values()) != EXPECTED_QUESTION_COUNT:
        raise SystemExit("Safety check failed: difficulty totals do not add up.")
    write_reports(
        classifications,
        json_path=args.json_output,
        csv_path=args.csv_output,
    )
    print(f"EASY: {totals['EASY']}")
    print(f"MEDIUM: {totals['MEDIUM']}")
    print(f"HARD: {totals['HARD']}")
    print(f"TOTAL: {sum(totals.values())}")
    print(f"JSON REPORT: {args.json_output}")
    print(f"CSV REPORT: {args.csv_output}")

    if args.apply:
        result = apply_classifications(classifications)
        print(f"UPDATED: {result['updated']}")
        print(f"NULL DIFFICULTY: {result['null_difficulty']}")
        for difficulty in sorted(DIFFICULTIES):
            print(f"{difficulty}: {result['difficulty_counts'].get(difficulty, 0)}")
        print(f"TOTAL QUESTIONS: {EXPECTED_QUESTION_COUNT}")
        print("ONLY questions.difficulty was modified.")
    else:
        print("DRY RUN: MySQL was not modified.")


if __name__ == "__main__":
    main()
