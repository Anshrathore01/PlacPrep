import json
import random

from fastapi import HTTPException
from sqlalchemy import text

from app.judge.config import MAX_CASE_BYTES, MAX_TEST_CASES, MAX_TOTAL_CASE_BYTES
from app.services.mock_eligibility_service import (
    MOCK_ELIGIBLE_QUESTION_SQL,
)

MAX_BLUEPRINT_QUESTIONS = 100

JUDGE_COMPATIBLE_CODING_SQL = f"""
    (
        q.question_type <> 'CODING'
        OR (
            (
                SELECT COUNT(*)
                FROM coding_test_cases tc
                WHERE tc.question_id = q.question_id
            ) BETWEEN 1 AND {MAX_TEST_CASES}
            AND NOT EXISTS (
                SELECT 1
                FROM coding_test_cases tc
                WHERE tc.question_id = q.question_id
                  AND (tc.points IS NULL OR tc.points <= 0)
            )
            AND NOT EXISTS (
                SELECT 1
                FROM coding_test_cases tc
                WHERE tc.question_id = q.question_id
                  AND LENGTH(tc.input_data) + LENGTH(tc.expected_output) > {MAX_CASE_BYTES}
            )
            AND (
                SELECT COALESCE(
                    SUM(LENGTH(tc.input_data) + LENGTH(tc.expected_output)), 0
                )
                FROM coding_test_cases tc
                WHERE tc.question_id = q.question_id
            ) <= {MAX_TOTAL_CASE_BYTES}
        )
    )
"""

# Kept as an import-compatible alias while all consumers share one predicate.
ELIGIBLE_QUESTION_SQL = MOCK_ELIGIBLE_QUESTION_SQL


def _lock_questions(connection, question_ids: list[int]) -> None:
    for question_id in question_ids:
        exists = connection.execute(
            text("""
                SELECT 1
                FROM questions
                WHERE question_id = :question_id
                FOR UPDATE
            """),
            {"question_id": question_id},
        ).scalar_one_or_none()
        if exists is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "The eligible question pool changed during test creation; "
                    "please retry."
                ),
            )


def _get_blueprint(connection, blueprint_id: int, lock: bool = False) -> dict:
    query = """
        SELECT b.blueprint_id, b.company_id, c.company_name, b.blueprint_name,
               b.program_name, b.pattern_version, b.effective_from, b.effective_to,
               b.source_name, b.source_url, b.source_type,
               b.source_published_at, b.source_accessed_at, b.source_notes,
               b.pattern_details, b.activated_at,
               b.verification_status, b.verification_notes, b.track_id,
               b.duration_seconds, b.description, b.status
        FROM test_blueprints b
        LEFT JOIN companies c ON c.company_id = b.company_id
        WHERE b.blueprint_id = :blueprint_id
    """
    if lock:
        query += " FOR UPDATE"
    blueprint = connection.execute(
        text(query), {"blueprint_id": blueprint_id}
    ).mappings().first()
    if blueprint is None:
        raise HTTPException(status_code=404, detail="Blueprint not found")
    result = dict(blueprint)
    details = result.get("pattern_details")
    if isinstance(details, str):
        result["pattern_details"] = json.loads(details)
    return result


def _get_rules(connection, blueprint_id: int) -> list[dict]:
    rows = connection.execute(
        text("""
            SELECT blueprint_rule_id, blueprint_id, track_id, topic_id, subtopic_id,
                   question_type, difficulty, question_count, selection_weight,
                   points, section_name, section_order, is_required,
                   time_allocation_seconds, selection_strategy, minimum_difficulty,
                   maximum_difficulty
            FROM test_blueprint_rules
            WHERE blueprint_id = :blueprint_id
            ORDER BY section_order, blueprint_rule_id
        """),
        {"blueprint_id": blueprint_id},
    ).mappings().all()
    return [dict(row) for row in rows]


def get_blueprint(connection, blueprint_id: int, lock: bool = False) -> dict:
    blueprint = _get_blueprint(connection, blueprint_id, lock=lock)
    blueprint["rules"] = _get_rules(connection, blueprint_id)
    return blueprint


def _effective_now(connection, blueprint: dict) -> bool:
    return connection.execute(
        text("""
            SELECT (:effective_from IS NULL OR :effective_from <= CURRENT_DATE)
               AND (:effective_to IS NULL OR :effective_to >= CURRENT_DATE)
        """),
        {
            "effective_from": blueprint.get("effective_from"),
            "effective_to": blueprint.get("effective_to"),
        },
    ).scalar_one()


def validate_rule_references(connection, blueprint: dict, rule: dict) -> list[str]:
    errors = []
    rule_track_id = rule.get("track_id") or blueprint.get("track_id")
    if rule.get("track_id") is not None:
        exists = connection.execute(
            text("SELECT 1 FROM tracks WHERE track_id = :track_id"),
            {"track_id": rule["track_id"]},
        ).scalar_one_or_none()
        if exists is None:
            errors.append(f"Track {rule['track_id']} does not exist.")
    if rule.get("topic_id") is not None:
        topic = connection.execute(
            text("SELECT track_id FROM topics WHERE topic_id = :topic_id"),
            {"topic_id": rule["topic_id"]},
        ).scalar_one_or_none()
        if topic is None:
            errors.append(f"Topic {rule['topic_id']} does not exist.")
        elif rule_track_id is not None and topic != rule_track_id:
            errors.append(
                f"Topic {rule['topic_id']} does not belong to the rule track."
            )

    if rule.get("subtopic_id") is not None:
        subtopic = connection.execute(
            text("""
                SELECT t.track_id, st.topic_id
                FROM subtopics st
                JOIN topics t ON t.topic_id = st.topic_id
                WHERE st.subtopic_id = :subtopic_id
            """),
            {"subtopic_id": rule["subtopic_id"]},
        ).mappings().first()
        if subtopic is None:
            errors.append(f"Subtopic {rule['subtopic_id']} does not exist.")
        elif subtopic["topic_id"] != rule.get("topic_id"):
            errors.append("Subtopic must belong to the rule's topic.")
        elif rule_track_id is not None and subtopic["track_id"] != rule_track_id:
            errors.append("Subtopic does not belong to the rule track.")
    if rule.get("question_type") not in (None, "MCQ", "CODING"):
        errors.append("Unsupported question type.")
    if rule.get("difficulty") not in (None, "EASY", "MEDIUM", "HARD"):
        errors.append("Unsupported difficulty.")
    difficulty_order = {"EASY": 1, "MEDIUM": 2, "HARD": 3}
    minimum = rule.get("minimum_difficulty")
    maximum = rule.get("maximum_difficulty")
    if minimum is not None and minimum not in difficulty_order:
        errors.append("Unsupported minimum difficulty.")
    if maximum is not None and maximum not in difficulty_order:
        errors.append("Unsupported maximum difficulty.")
    if (
        minimum in difficulty_order
        and maximum in difficulty_order
        and difficulty_order[minimum] > difficulty_order[maximum]
    ):
        errors.append("Minimum difficulty cannot exceed maximum difficulty.")
    if rule.get("difficulty") is not None and (minimum is not None or maximum is not None):
        errors.append("Use exact difficulty or a difficulty range, not both.")
    if int(rule.get("section_order", 1)) < 1:
        errors.append("Section order must be positive.")
    if rule.get("time_allocation_seconds") is not None and int(
        rule["time_allocation_seconds"]
    ) < 1:
        errors.append("Section time allocation must be positive.")
    if int(rule.get("question_count", 0)) < 1:
        errors.append("Question count must be positive.")
    if rule.get("selection_strategy", "QUESTION_ID_ASC") not in {
        "QUESTION_ID_ASC",
        "EASY_TO_HARD",
        "HARD_TO_EASY",
    }:
        errors.append("Unsupported selection strategy.")
    if float(rule.get("points", 0)) <= 0:
        errors.append("Points must be positive.")
    if float(rule.get("selection_weight", 0)) <= 0:
        errors.append("Selection weight must be positive.")
    return errors


def _candidate_question_ids(connection, blueprint: dict, rule: dict) -> list[int]:
    conditions = [ELIGIBLE_QUESTION_SQL, JUDGE_COMPATIBLE_CODING_SQL]
    params = {}
    track_id = rule.get("track_id") or blueprint["track_id"]
    if track_id is not None:
        conditions.append("q.track_id = :track_id")
        params["track_id"] = track_id
    if rule.get("topic_id") is not None:
        conditions.append("""
            EXISTS (
                SELECT 1
                FROM question_subtopics qs
                JOIN subtopics st ON st.subtopic_id = qs.subtopic_id
                WHERE qs.question_id = q.question_id
                  AND st.topic_id = :topic_id
            )
        """)
        params["topic_id"] = rule["topic_id"]
    if rule.get("subtopic_id") is not None:
        conditions.append("""
            EXISTS (
                SELECT 1 FROM question_subtopics qs
                WHERE qs.question_id = q.question_id
                  AND qs.subtopic_id = :subtopic_id
            )
        """)
        params["subtopic_id"] = rule["subtopic_id"]
    if rule.get("question_type") is not None:
        conditions.append("q.question_type = :question_type")
        params["question_type"] = rule["question_type"]
    if rule.get("difficulty") is not None:
        conditions.append("q.difficulty = :difficulty")
        params["difficulty"] = rule["difficulty"]
    difficulty_order = {"EASY": 1, "MEDIUM": 2, "HARD": 3}
    if rule.get("minimum_difficulty") in difficulty_order:
        conditions.append(
            "FIELD(q.difficulty, 'EASY', 'MEDIUM', 'HARD') >= :minimum_difficulty"
        )
        params["minimum_difficulty"] = difficulty_order[rule["minimum_difficulty"]]
    if rule.get("maximum_difficulty") in difficulty_order:
        conditions.append(
            "FIELD(q.difficulty, 'EASY', 'MEDIUM', 'HARD') <= :maximum_difficulty"
        )
        params["maximum_difficulty"] = difficulty_order[rule["maximum_difficulty"]]

    rows = connection.execute(
        text(f"""
            SELECT q.question_id, q.difficulty
            FROM questions q
            WHERE {" AND ".join(f"({condition})" for condition in conditions)}
        """),
        params,
    ).mappings().all()
    strategy = rule.get("selection_strategy", "QUESTION_ID_ASC")
    difficulty_order = {"EASY": 1, "MEDIUM": 2, "HARD": 3}
    if strategy == "EASY_TO_HARD":
        rows = sorted(
            rows,
            key=lambda row: (
                difficulty_order.get(row["difficulty"], 4),
                int(row["question_id"]),
            ),
        )
    elif strategy == "HARD_TO_EASY":
        rows = sorted(
            rows,
            key=lambda row: (
                -difficulty_order.get(row["difficulty"], 0),
                int(row["question_id"]),
            ),
        )
    else:
        rows = sorted(rows, key=lambda row: int(row["question_id"]))
    return [int(row["question_id"]) for row in rows]


def _allocate_unique_questions(
    rules: list[dict],
    candidates_by_rule: list[list[int]],
    *,
    preserve_candidate_order: bool = False,
) -> list[dict]:
    total_requested = sum(int(rule["question_count"]) for rule in rules)
    if total_requested > MAX_BLUEPRINT_QUESTIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Blueprints may request at most {MAX_BLUEPRINT_QUESTIONS} questions.",
        )

    candidate_sets = [
        list(dict.fromkeys(candidates))
        if preserve_candidate_order
        else sorted(set(candidates))
        for candidates in candidates_by_rule
    ]

    slots = [
        rule_index
        for rule_index, rule in enumerate(rules)
        if (
            rule.get("is_required", True)
            or len(candidate_sets[rule_index]) >= int(rule["question_count"])
        )
        for _ in range(int(rule["question_count"]))
    ]
    slots.sort(
        key=lambda index: (
            len(candidate_sets[index]),
            -float(rules[index].get("selection_weight", 1)),
        )
    )

    assigned_slot_by_question = {}
    assignment_by_slot = [None] * len(slots)

    def assign(slot_index: int, visited: set[int]) -> bool:
        rule_index = slots[slot_index]
        for question_id in candidate_sets[rule_index]:
            if question_id in visited:
                continue
            visited.add(question_id)
            previous_slot = assigned_slot_by_question.get(question_id)
            if previous_slot is None or assign(previous_slot, visited):
                assigned_slot_by_question[question_id] = slot_index
                assignment_by_slot[slot_index] = question_id
                return True
        return False

    for slot_index in range(len(slots)):
        if not assign(slot_index, set()):
            shortage_rules = []
            for index, rule in enumerate(rules):
                shortage_rules.append({
                    "blueprint_rule_id": rule.get("blueprint_rule_id"),
                    "section": rule.get("section_name"),
                    "requested": int(rule["question_count"]),
                    "eligible_count": len(candidates_by_rule[index]),
                })
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "INSUFFICIENT_BLUEPRINT_CONTENT",
                    "message": "Insufficient distinct eligible published questions for this blueprint.",
                    "rules": shortage_rules,
                },
            )

    selected_by_rule = [[] for _ in rules]
    for slot_index, question_id in enumerate(assignment_by_slot):
        selected_by_rule[slots[slot_index]].append(question_id)
    selections = [
        {
            "blueprint_rule_id": rule.get("blueprint_rule_id"),
            "question_ids": selected_by_rule[index],
            "points": float(rule["points"]),
        }
        for index, rule in enumerate(rules)
        if (
            rule.get("is_required", True)
            or len(candidate_sets[index]) >= int(rule["question_count"])
        )
    ]
    return selections


def validate_blueprint(connection, blueprint_id: int) -> list[dict]:
    blueprint = _get_blueprint(connection, blueprint_id)
    rules = _get_rules(connection, blueprint_id)
    errors = []
    if not rules:
        errors.append({"message": "Blueprint must have at least one rule."})
    if blueprint.get("company_id") is not None:
        if blueprint.get("company_name") is None:
            errors.append({
                "code": "INVALID_COMPANY",
                "message": "Blueprint company does not exist.",
            })
        for field, label in (
            ("program_name", "Program name"),
            ("pattern_version", "Pattern version"),
            ("source_name", "Pattern source name"),
            ("source_url", "Pattern source URL"),
            ("source_type", "Pattern source type"),
            ("source_accessed_at", "Source access date"),
            ("duration_seconds", "Assessment duration"),
        ):
            value = blueprint.get(field)
            if value is None or (
                isinstance(value, str) and not value.strip()
            ):
                errors.append({
                    "code": "MISSING_REQUIRED_FIELD",
                    "field": field,
                    "message": f"{label} is required for company blueprints.",
                })
        source_type = blueprint.get("source_type")
        verification_status = blueprint.get("verification_status")
        if (
            verification_status == "OFFICIAL"
            and source_type not in {"COMPANY_OFFICIAL", "ASSESSMENT_PROVIDER"}
        ):
            errors.append({
                "code": "INVALID_VERIFICATION_SOURCE",
                "message": (
                    "OFFICIAL verification requires a company or assessment "
                    "provider source."
                ),
            })
        if (
            verification_status == "REPORTED"
            and source_type not in {"RECRUITMENT_REPORT", "CANDIDATE_REPORT"}
        ):
            errors.append({
                "code": "INVALID_VERIFICATION_SOURCE",
                "message": "REPORTED patterns require a report or candidate source.",
            })
        duplicate_version = connection.execute(
            text("""
                SELECT blueprint_id
                FROM test_blueprints
                WHERE company_id = :company_id
                  AND program_name = :program_name
                  AND pattern_version = :pattern_version
                  AND blueprint_id <> :blueprint_id
                LIMIT 1
            """),
            {
                "company_id": blueprint["company_id"],
                "program_name": blueprint.get("program_name"),
                "pattern_version": blueprint.get("pattern_version"),
                "blueprint_id": blueprint_id,
            },
        ).scalar_one_or_none()
        if duplicate_version is not None:
            errors.append({
                "code": "DUPLICATE_PATTERN_VERSION",
                "message": (
                    "A pattern version already exists for this company and program."
                ),
                "conflicting_blueprint_id": int(duplicate_version),
            })

    effective_from = blueprint.get("effective_from")
    effective_to = blueprint.get("effective_to")
    if effective_from is not None and effective_to is not None and effective_to < effective_from:
        errors.append({
            "code": "INVALID_DATE_RANGE",
            "message": "effective_to must not precede effective_from.",
        })

    pattern_details = blueprint.get("pattern_details")
    detail_sections = []
    if pattern_details is not None:
        if (
            not isinstance(pattern_details, dict)
            or not isinstance(pattern_details.get("sections"), list)
            or any(
                not isinstance(section, dict)
                for section in pattern_details.get("sections", [])
            )
        ):
            errors.append({
                "code": "INVALID_PATTERN_DETAILS",
                "message": (
                    "Pattern details must include a sections array of section "
                    "objects."
                ),
            })
        else:
            detail_sections = pattern_details["sections"]
    detail_names = []
    detail_orders = []
    for section in detail_sections:
        section_name = section.get("section_name")
        section_order = section.get("section_order")
        if not isinstance(section_name, str) or not section_name.strip():
            errors.append({
                "code": "MISSING_PATTERN_SECTION_NAME",
                "message": "Every source pattern section requires a name.",
            })
        else:
            detail_names.append(section_name.strip().casefold())
        if (
            not isinstance(section_order, int)
            or isinstance(section_order, bool)
            or section_order < 1
        ):
            errors.append({
                "code": "INVALID_PATTERN_SECTION_ORDER",
                "section": section_name,
                "message": "Source pattern section order must be a positive integer.",
            })
        else:
            detail_orders.append(section_order)

        count = section.get("question_count")
        if count is not None and (
            not isinstance(count, int)
            or isinstance(count, bool)
            or count < 1
        ):
            errors.append({
                "code": "INVALID_PATTERN_QUESTION_COUNT",
                "section": section_name,
                "message": "Reported section question counts must be positive integers.",
            })
        count_range = section.get("question_count_range")
        if count_range is not None and (
            not isinstance(count_range, list)
            or len(count_range) != 2
            or any(
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 1
                for value in count_range
            )
            or (
                isinstance(count_range, list)
                and len(count_range) == 2
                and all(isinstance(value, int) for value in count_range)
                and count_range[0] > count_range[1]
            )
        ):
            errors.append({
                "code": "INVALID_PATTERN_QUESTION_RANGE",
                "section": section_name,
                "message": (
                    "Reported question count ranges must contain ordered positive "
                    "integer bounds."
                ),
            })
        duration = section.get("duration_seconds")
        if duration is not None and (
            not isinstance(duration, int)
            or isinstance(duration, bool)
            or duration < 1
        ):
            errors.append({
                "code": "INVALID_PATTERN_SECTION_DURATION",
                "section": section_name,
                "message": "Reported section duration must be a positive integer.",
            })
        duration_range = section.get("duration_range_seconds")
        if duration_range is not None and (
            not isinstance(duration_range, list)
            or len(duration_range) != 2
            or any(
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 1
                for value in duration_range
            )
            or (
                isinstance(duration_range, list)
                and len(duration_range) == 2
                and all(isinstance(value, int) for value in duration_range)
                and duration_range[0] > duration_range[1]
            )
        ):
            errors.append({
                "code": "INVALID_PATTERN_DURATION_RANGE",
                "section": section_name,
                "message": (
                    "Reported duration ranges must contain ordered positive "
                    "integer bounds."
                ),
            })
        question_types = section.get("question_types", [])
        if not isinstance(question_types, list) or any(
            not isinstance(question_type, str) or not question_type.strip()
            for question_type in question_types
        ):
            errors.append({
                "code": "INVALID_PATTERN_QUESTION_TYPES",
                "section": section_name,
                "message": "Reported question types must be a list of nonempty strings.",
            })
        if (
            section.get("selection_supported") is not True
            and section.get("selection_supported") is not False
        ):
            errors.append({
                "code": "INVALID_PATTERN_SUPPORT_FLAG",
                "section": section_name,
                "message": "Pattern section selection_supported must be boolean.",
            })
    if len(detail_names) != len(set(detail_names)):
        errors.append({
            "code": "DUPLICATE_PATTERN_SECTION",
            "message": "Source pattern section names must be unique.",
        })
    if len(detail_orders) != len(set(detail_orders)):
        errors.append({
            "code": "DUPLICATE_PATTERN_SECTION_ORDER",
            "message": "Source pattern section orders must be unique.",
        })
    unsupported_sections = [
        section
        for section in detail_sections
        if section.get("selection_supported") is False
    ]
    for section in unsupported_sections:
        errors.append({
            "code": "UNSUPPORTED_PATTERN_SECTION",
            "section": section.get("section_name"),
            "message": (
                "The reported pattern contains a section that cannot yet be "
                "represented by the eligible question bank."
            ),
        })

    if blueprint.get("company_id") is not None:
        conflicts = connection.execute(
            text("""
                SELECT blueprint_id
                FROM test_blueprints
                WHERE company_id = :company_id
                  AND program_name = :program_name
                  AND status = 'ACTIVE'
                  AND blueprint_id <> :blueprint_id
                  AND COALESCE(effective_from, '1000-01-01')
                      <= COALESCE(:effective_to, '9999-12-31')
                  AND COALESCE(effective_to, '9999-12-31')
                      >= COALESCE(:effective_from, '1000-01-01')
            """),
            {
                "company_id": blueprint["company_id"],
                "program_name": blueprint.get("program_name"),
                "blueprint_id": blueprint_id,
                "effective_from": effective_from,
                "effective_to": effective_to,
            },
        ).scalars().all()
        if conflicts:
            errors.append({
                "code": "CONFLICTING_ACTIVE_VERSIONS",
                "message": (
                    "Another active version for this company and program has "
                    "an overlapping effective date range."
                ),
                "conflicting_blueprint_ids": [int(value) for value in conflicts],
            })

    section_names = [
        (rule.get("section_name") or "").strip().casefold()
        for rule in rules
    ]
    section_orders = [int(rule.get("section_order") or 0) for rule in rules]
    if len(section_names) != len(set(section_names)):
        errors.append({
            "code": "DUPLICATE_SECTION",
            "message": "Blueprint section names must be unique.",
        })
    if len(section_orders) != len(set(section_orders)):
        errors.append({
            "code": "DUPLICATE_SECTION_ORDER",
            "message": "Blueprint section orders must be unique.",
        })

    rules_by_section = {
        (rule.get("section_name") or "").strip().casefold(): rule
        for rule in rules
    }
    for section in detail_sections:
        if section.get("selection_supported") is not True:
            continue
        section_name = (section.get("section_name") or "").strip().casefold()
        rule = rules_by_section.get(section_name)
        if rule is None or section.get("question_count") != int(rule["question_count"]):
            errors.append({
                "code": "PATTERN_RULE_MISMATCH",
                "section": section.get("section_name"),
                "message": (
                    "Every executable source section must have a matching "
                    "blueprint rule with the reported question count."
                ),
            })

    if sum(
        int(rule["question_count"])
        for rule in rules
        if rule.get("is_required", True)
        or len(_candidate_question_ids(connection, blueprint, rule))
        >= int(rule["question_count"])
    ) > MAX_BLUEPRINT_QUESTIONS:
        errors.append({
            "message": f"Blueprint may request at most {MAX_BLUEPRINT_QUESTIONS} questions."
        })

    candidates_by_rule = []
    for rule in rules:
        if blueprint.get("company_id") is not None and not (
            rule.get("section_name") or ""
        ).strip():
            errors.append({
                "code": "MISSING_SECTION_NAME",
                "blueprint_rule_id": rule["blueprint_rule_id"],
                "message": "Company blueprint rules require a section name.",
            })
        if blueprint.get("company_id") is not None and rule.get("question_type") not in {
            "MCQ",
            "CODING",
        }:
            errors.append({
                "code": "MISSING_QUESTION_TYPE",
                "blueprint_rule_id": rule["blueprint_rule_id"],
                "message": "Company blueprint rules require a question type.",
            })
        if (
            blueprint.get("company_id") is not None
            and rule.get("topic_id") is None
            and rule.get("subtopic_id") is None
            and rule.get("track_id") is None
            and blueprint.get("track_id") is None
        ):
            errors.append({
                "code": "MISSING_TOPIC_FILTER",
                "blueprint_rule_id": rule["blueprint_rule_id"],
                "message": (
                    "Company blueprint rules must constrain questions to a topic "
                    "or subtopic."
                ),
            })
        for message in validate_rule_references(connection, blueprint, rule):
            errors.append({
                "blueprint_rule_id": rule["blueprint_rule_id"],
                "message": message,
            })
        candidates_by_rule.append(_candidate_question_ids(connection, blueprint, rule))
        eligible_count = len(candidates_by_rule[-1])
        if eligible_count < int(rule["question_count"]) and rule.get(
            "is_required", True
        ):
            errors.append({
                "code": "INSUFFICIENT_BLUEPRINT_CONTENT",
                "blueprint_rule_id": rule["blueprint_rule_id"],
                "section": rule.get("section_name"),
                "requested": int(rule["question_count"]),
                "required_count": int(rule["question_count"]),
                "available": eligible_count,
                "eligible_count": eligible_count,
                "reason": "NOT_ENOUGH_CONTENT_ELIGIBLE_QUESTIONS",
                "message": "Insufficient eligible published questions for this rule.",
            })
    if not errors:
        try:
            _allocate_unique_questions(rules, candidates_by_rule)
        except HTTPException as error:
            detail = error.detail
            errors.append(
                detail if isinstance(detail, dict) else {"message": str(detail)}
            )
    return errors


def preview_blueprint(connection, blueprint_id: int) -> dict:
    blueprint = _get_blueprint(connection, blueprint_id)
    rules = _get_rules(connection, blueprint_id)
    counts = []
    candidates_by_rule = []
    for rule in rules:
        candidates = _candidate_question_ids(connection, blueprint, rule)
        candidates_by_rule.append(candidates)
        counts.append({
            "blueprint_rule_id": rule["blueprint_rule_id"],
            "section_name": rule.get("section_name"),
            "section_order": rule.get("section_order"),
            "is_required": bool(rule.get("is_required", True)),
            "track_id": rule.get("track_id") or blueprint.get("track_id"),
            "topic_id": rule["topic_id"],
            "subtopic_id": rule["subtopic_id"],
            "question_type": rule["question_type"],
            "difficulty": rule["difficulty"],
            "minimum_difficulty": rule.get("minimum_difficulty"),
            "maximum_difficulty": rule.get("maximum_difficulty"),
            "time_allocation_seconds": rule.get("time_allocation_seconds"),
            "selection_strategy": rule.get("selection_strategy"),
            "question_count": int(rule["question_count"]),
            "eligible_count": len(candidates),
            "sufficient": len(candidates) >= int(rule["question_count"]),
        })
    errors = validate_blueprint(connection, blueprint_id)
    return {
        "blueprint_id": blueprint_id,
        "company_id": blueprint.get("company_id"),
        "company": blueprint.get("company_name"),
        "blueprint_name": blueprint.get("blueprint_name"),
        "program_name": blueprint.get("program_name"),
        "pattern_version": blueprint.get("pattern_version"),
        "effective_from": blueprint.get("effective_from"),
        "effective_to": blueprint.get("effective_to"),
        "source_name": blueprint.get("source_name"),
        "source_url": blueprint.get("source_url"),
        "source_type": blueprint.get("source_type"),
        "source_published_at": blueprint.get("source_published_at"),
        "source_accessed_at": blueprint.get("source_accessed_at"),
        "source_notes": blueprint.get("source_notes"),
        "pattern_details": blueprint.get("pattern_details"),
        "verification_status": blueprint.get("verification_status"),
        "status": blueprint["status"],
        "activated_at": blueprint.get("activated_at"),
        "currently_effective": _effective_now(connection, blueprint),
        "rules": counts,
        "pattern_sections": (
            blueprint.get("pattern_details", {}).get("sections", [])
            if isinstance(blueprint.get("pattern_details"), dict)
            else []
        ),
        "valid": not errors,
        "ready_for_mock": (
            blueprint["status"] == "ACTIVE"
            and _effective_now(connection, blueprint)
            and not errors
        ),
        "errors": errors,
    }


def select_blueprint_questions(connection, blueprint_id: int) -> tuple[dict, list[dict]]:
    blueprint = _get_blueprint(connection, blueprint_id, lock=True)
    if blueprint["status"] != "ACTIVE" or not _effective_now(connection, blueprint):
        raise HTTPException(
            status_code=409,
            detail="Only currently effective active blueprints can be used to create a student test.",
        )
    rules = _get_rules(connection, blueprint_id)
    errors = validate_blueprint(connection, blueprint_id)
    if errors:
        insufficient = any(
            "available" in error or error.get("code") == "INSUFFICIENT_BLUEPRINT_CONTENT"
            for error in errors
        )
        raise HTTPException(
            status_code=409,
            detail={
                "code": (
                    "INSUFFICIENT_BLUEPRINT_CONTENT"
                    if insufficient else "INVALID_BLUEPRINT"
                ),
                "company": blueprint.get("company_name"),
                "blueprint_id": blueprint_id,
                "message": "Blueprint is not valid for test creation.",
                "errors": errors,
            },
        )
    candidates = [
        _candidate_question_ids(connection, blueprint, rule)
        for rule in rules
    ]
    selections = _allocate_unique_questions(
        rules,
        candidates,
        preserve_candidate_order=True,
    )
    _lock_questions(
        connection,
        [
            question_id
            for selection in selections
            for question_id in selection["question_ids"]
        ],
    )
    return blueprint, selections


def create_mock_test_from_blueprint(
    connection,
    blueprint_id: int,
    title: str,
    mode: str,
    created_by: int,
    *,
    selections: list[dict] | None = None,
    selection_mode: str = "FILTERED_BANK",
    duration_seconds: int | None = None,
) -> dict:
    blueprint = _get_blueprint(connection, blueprint_id, lock=True)
    if blueprint["status"] != "ACTIVE" or not _effective_now(connection, blueprint):
        raise HTTPException(
            status_code=409,
            detail="Only currently effective active blueprints can be used to create a student test.",
        )
    adaptive_selection = selections is not None
    if selections is None:
        blueprint, selections = select_blueprint_questions(connection, blueprint_id)
    else:
        errors = validate_blueprint(connection, blueprint_id)
        if errors:
            insufficient = any(
                "available" in error
                or error.get("code") == "INSUFFICIENT_BLUEPRINT_CONTENT"
                for error in errors
            )
            raise HTTPException(
                status_code=409,
                detail={
                    "code": (
                        "INSUFFICIENT_BLUEPRINT_CONTENT"
                        if insufficient else "INVALID_BLUEPRINT"
                    ),
                    "company": blueprint.get("company_name"),
                    "blueprint_id": blueprint_id,
                    "message": "Blueprint is not valid for test creation.",
                    "errors": errors,
                },
            )
        rules = _get_rules(connection, blueprint_id)
        by_rule = {rule["blueprint_rule_id"]: rule for rule in rules}
        if {item["blueprint_rule_id"] for item in selections} != {
            rule["blueprint_rule_id"]
            for rule in rules
            if rule.get("is_required", True)
            or len(_candidate_question_ids(connection, blueprint, rule))
            >= int(rule["question_count"])
        }:
            raise HTTPException(status_code=409, detail="Blueprint selection is incomplete.")
        for selection in selections:
            rule = by_rule[selection["blueprint_rule_id"]]
            question_ids = selection["question_ids"]
            if len(question_ids) != int(rule["question_count"]):
                raise HTTPException(status_code=409, detail="Blueprint section count mismatch.")
            allowed = set(_candidate_question_ids(connection, blueprint, rule))
            if not set(question_ids).issubset(allowed):
                raise HTTPException(
                    status_code=409,
                    detail="Blueprint selection contains an ineligible question.",
                )
    if blueprint.get("company_id") is not None:
        label = (
            "Company-Style Adaptive Practice"
            if adaptive_selection and mode == "PRACTICE"
            else "Company-Style Mock"
            if mode == "MOCK"
            else "Company-Style Practice"
        )
        title = " ".join(
            value
            for value in (
                blueprint.get("company_name"),
                blueprint.get("program_name"),
                blueprint.get("pattern_version"),
                label,
            )
            if value
        )
    total_questions = sum(len(selection["question_ids"]) for selection in selections)
    result = connection.execute(
        text("""
            INSERT INTO mock_tests (
                blueprint_id, created_by, title, mode, selection_mode,
                duration_seconds, total_questions, status
            )
            VALUES (
                :blueprint_id, :created_by, :title, :mode, :selection_mode,
                :duration_seconds, :total_questions, 'PUBLISHED'
            )
        """),
        {
            "blueprint_id": blueprint_id,
            "created_by": created_by,
            "title": title,
            "mode": mode,
            "selection_mode": selection_mode,
            "duration_seconds": (
                duration_seconds
                if duration_seconds is not None
                else blueprint["duration_seconds"]
            ),
            "total_questions": total_questions,
        },
    )
    mock_test_id = result.lastrowid
    sequence_no = 1
    for selection in selections:
        for question_id in selection["question_ids"]:
            connection.execute(
                text("""
                    INSERT INTO mock_test_questions (
                        mock_test_id, question_id, sequence_no, points
                    )
                    VALUES (
                        :mock_test_id, :question_id, :sequence_no, :points
                    )
                """),
                {
                    "mock_test_id": mock_test_id,
                    "question_id": question_id,
                    "sequence_no": sequence_no,
                    "points": selection["points"],
                },
            )
            sequence_no += 1
    row = connection.execute(
        text("""
            SELECT mt.mock_test_id, mt.blueprint_id, mt.title, mt.mode,
                   mt.selection_mode, mt.duration_seconds, mt.total_questions,
                   mt.status, b.company_id, c.company_name, b.program_name,
                   b.pattern_version, b.verification_status
            FROM mock_tests mt
            LEFT JOIN test_blueprints b ON b.blueprint_id = mt.blueprint_id
            LEFT JOIN companies c ON c.company_id = b.company_id
            WHERE mt.mock_test_id = :mock_test_id
        """),
        {"mock_test_id": mock_test_id},
    ).mappings().one()
    return dict(row)


def select_filtered_questions(
    connection,
    question_type: str | None,
    track_id: int | None,
    difficulty: str | None,
    topic_id: int | None,
    subtopic_id: int | None,
    total_questions: int,
) -> list[int]:
    if topic_id is not None:
        exists = connection.execute(
            text("SELECT 1 FROM topics WHERE topic_id = :topic_id"),
            {"topic_id": topic_id},
        ).scalar_one_or_none()
        if exists is None:
            raise HTTPException(status_code=422, detail="Topic does not exist.")
    if subtopic_id is not None:
        subtopic_topic_id = connection.execute(
            text("SELECT topic_id FROM subtopics WHERE subtopic_id = :subtopic_id"),
            {"subtopic_id": subtopic_id},
        ).scalar_one_or_none()
        if subtopic_topic_id != topic_id:
            raise HTTPException(
                status_code=422,
                detail="Subtopic does not belong to the supplied topic.",
            )

    filters = [ELIGIBLE_QUESTION_SQL]
    params = {}
    for column, value, key in (
        ("q.question_type", question_type, "question_type"),
        ("q.track_id", track_id, "track_id"),
        ("q.difficulty", difficulty, "difficulty"),
    ):
        if value is not None:
            filters.append(f"{column} = :{key}")
            params[key] = value
    if topic_id is not None:
        filters.append("""
            EXISTS (
                SELECT 1
                FROM question_subtopics qs
                JOIN subtopics st ON st.subtopic_id = qs.subtopic_id
                WHERE qs.question_id = q.question_id
                  AND st.topic_id = :topic_id
            )
        """)
        params["topic_id"] = topic_id
    if subtopic_id is not None:
        filters.append("""
            EXISTS (
                SELECT 1
                FROM question_subtopics qs
                WHERE qs.question_id = q.question_id
                  AND qs.subtopic_id = :subtopic_id
            )
        """)
        params["subtopic_id"] = subtopic_id

    question_ids = connection.execute(
        text(f"""
            SELECT q.question_id
            FROM questions q
            WHERE {" AND ".join(f"({filter_sql})" for filter_sql in filters)}
        """),
        params,
    ).scalars().all()
    if len(question_ids) < total_questions:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Insufficient content-eligible questions for the requested filters.",
                "available": len(question_ids),
                "requested": total_questions,
            },
        )
    random.SystemRandom().shuffle(question_ids)
    selected = [int(question_id) for question_id in question_ids[:total_questions]]
    _lock_questions(connection, selected)
    return selected


def insert_mock_test(
    connection,
    title: str,
    mode: str,
    duration_seconds: int | None,
    question_ids: list[int],
    created_by: int | None = None,
    *,
    selection_mode: str = "FILTERED_BANK",
) -> dict:
    result = connection.execute(
        text("""
            INSERT INTO mock_tests (
                blueprint_id, created_by, title, mode, selection_mode,
                duration_seconds, total_questions, status
            )
            VALUES (
                NULL, :created_by, :title, :mode, :selection_mode,
                :duration_seconds, :total_questions, 'PUBLISHED'
            )
        """),
        {
            "created_by": created_by,
            "title": title,
            "mode": mode,
            "selection_mode": selection_mode,
            "duration_seconds": duration_seconds,
            "total_questions": len(question_ids),
        },
    )
    mock_test_id = result.lastrowid
    for sequence_no, question_id in enumerate(question_ids, start=1):
        connection.execute(
            text("""
                INSERT INTO mock_test_questions (
                    mock_test_id, question_id, sequence_no, points
                )
                VALUES (
                    :mock_test_id, :question_id, :sequence_no, 1.00
                )
            """),
            {
                "mock_test_id": mock_test_id,
                "question_id": question_id,
                "sequence_no": sequence_no,
            },
        )
    row = connection.execute(
        text("""
            SELECT mock_test_id, title, mode, selection_mode, duration_seconds,
                   total_questions, status
            FROM mock_tests
            WHERE mock_test_id = :mock_test_id
        """),
        {"mock_test_id": mock_test_id},
    ).mappings().one()
    return dict(row)
