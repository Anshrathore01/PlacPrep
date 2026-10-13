"""Seed source-backed, inactive company pattern versions without touching questions."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from decimal import Decimal
import sys
from pathlib import Path

from sqlalchemy import bindparam, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import engine
from app.services import blueprint_service


ACCESS_AT = datetime.now().replace(microsecond=0)
ACCESS_DATE = ACCESS_AT.date()

COMPANIES = (
    ("TCS", "tcs"),
    ("Wipro", "wipro"),
    ("Capgemini", "capgemini"),
    ("Infosys", "infosys"),
    ("LTIMindtree", "ltimindtree"),
    ("Cognizant", "cognizant"),
)

PROTOTYPE_NAME = "General Placement Preparation - v1.0"
PROTOTYPE_PROGRAM = "Company-Style Placement Preparation"
PROTOTYPE_VERSION = "1.0"
PROTOTYPE_RULES = (
    ("Quantitative Aptitude", 1, 2, 120),
    ("Logical Reasoning", 2, 2, 120),
    ("Verbal Ability", 3, 1, 60),
)
LEGACY_TCS_FOUNDATION_NOTES = (
    "Reported 2026 Foundation format. The source mixes MCQ and non-MCQ "
    "question formats but does not break their counts down by section. "
    "Official TCS campus/careers pages reviewed do not publish this "
    "detailed blueprint."
)


def _section(
    name: str,
    order: int,
    *,
    question_count: int | None = None,
    question_count_range: tuple[int, int] | None = None,
    duration_seconds: int | None = None,
    duration_range_seconds: tuple[int, int] | None = None,
    question_types: tuple[str, ...] = (),
    supported: bool = False,
    **metadata,
) -> dict:
    return {
        "section_name": name,
        "section_order": order,
        "question_count": question_count,
        "question_count_range": question_count_range,
        "duration_seconds": duration_seconds,
        "duration_range_seconds": duration_range_seconds,
        "question_types": list(question_types),
        "difficulty": None,
        "selection_supported": supported,
        **metadata,
    }


def _rule(
    section_name: str,
    section_order: int,
    track_name: str,
    question_type: str,
    question_count: int,
    *,
    topic_name: str | None = None,
    duration_seconds: int | None = None,
    selection_strategy: str = "QUESTION_ID_ASC",
) -> dict:
    return {
        "section_name": section_name,
        "section_order": section_order,
        "track_name": track_name,
        "topic_name": topic_name,
        "question_type": question_type,
        "question_count": question_count,
        "time_allocation_seconds": duration_seconds,
        "selection_strategy": selection_strategy,
        "is_required": True,
    }


PATTERNS = (
    {
        "company_slug": "tcs",
        "program_name": "TCS NQT Foundation",
        "pattern_version": "reported-2026-08",
        "blueprint_name": "TCS NQT Foundation — reported 2026",
        "source_name": "PrepInsta — TCS NQT Placement Papers and Questions 2026",
        "source_url": "https://prepinsta.com/tcs-nqt/placement-papers/",
        "source_type": "RECRUITMENT_REPORT",
        "source_published_at": date(2026, 8, 8),
        "verification_status": "REPORTED",
        "duration_seconds": 76 * 60,
        "notes": (
            "Reported 2026 Foundation format. The source mixes MCQ and non-MCQ "
            "question formats but does not break their counts down by section. "
            "Official TCS campus/careers pages reviewed do not publish this "
            "detailed blueprint. The platform operationalizes the reported "
            "section counts as MCQs because this is the supported format; it is "
            "not an exact reconstruction of the company assessment."
        ),
        "details": {
            "program_context": (
                "Foundation is reported as mandatory for Ninja aspirants; the "
                "source has surrounding references to 2025 despite a 2026 title."
            ),
            "reported_overall_duration_seconds": 76 * 60,
            "official_reference": "https://nextstep.tcsapps.com/indiacampus/",
            "platform_operationalization": (
                "The source does not split the reported MCQ/non-MCQ mix. The "
                "platform implements these counts using MCQs from its existing "
                "Numerical, Verbal and Reasoning taxonomy. This preparation mock "
                "is not an exact paper reconstruction and is not an official TCS "
                "assessment."
            ),
            "exact_exam_reconstruction": False,
            "sections": [
                _section(
                    "Numerical Ability", 1, question_count=20,
                    duration_seconds=25 * 60,
                    question_types=("MCQ", "NON_MCQ"),
                    supported=True,
                    platform_operationalized_question_type="MCQ",
                ),
                _section(
                    "Verbal Ability", 2, question_count=25,
                    duration_seconds=26 * 60,
                    question_types=("MCQ", "NON_MCQ"),
                    supported=True,
                    platform_operationalized_question_type="MCQ",
                ),
                _section(
                    "Reasoning Ability", 3, question_count=20,
                    duration_seconds=25 * 60,
                    question_types=("MCQ", "NON_MCQ"),
                    supported=True,
                    platform_operationalized_question_type="MCQ",
                ),
            ],
        },
        "rules": (
            _rule(
                "Numerical Ability", 1, "Aptitude", "MCQ", 20,
                topic_name="Quantitative Aptitude", duration_seconds=25 * 60,
            ),
            _rule(
                "Verbal Ability", 2, "Aptitude", "MCQ", 25,
                topic_name="Verbal Ability", duration_seconds=26 * 60,
            ),
            _rule(
                "Reasoning Ability", 3, "Aptitude", "MCQ", 20,
                topic_name="Logical Reasoning", duration_seconds=25 * 60,
            ),
        ),
    },
    {
        "company_slug": "tcs",
        "program_name": "TCS NQT Advanced",
        "pattern_version": "reported-2026-08",
        "blueprint_name": "TCS NQT Advanced — reported 2026",
        "source_name": "PrepInsta — TCS NQT Placement Papers and Questions 2026",
        "source_url": "https://prepinsta.com/tcs-nqt/placement-papers/",
        "source_type": "RECRUITMENT_REPORT",
        "source_published_at": date(2026, 8, 8),
        "verification_status": "REPORTED",
        "duration_seconds": 115 * 60,
        "notes": (
            "Reported 2026 Advanced format for Digital/Prime aspirants. The "
            "quantitative and reasoning count is reported as 14–16 combined; "
            "the source does not give per-section counts. Foundation and "
            "Advanced are separate program versions."
        ),
        "details": {
            "program_context": (
                "Advanced section is reported as mandatory for Digital/Prime "
                "aspirants. The source title says 2026 but surrounding content "
                "also references 2025."
            ),
            "reported_overall_duration_seconds": 115 * 60,
            "official_reference": "https://nextstep.tcsapps.com/indiacampus/",
            "sections": [
                _section(
                    "Advanced Quantitative and Reasoning Ability", 1,
                    question_count_range=(14, 16),
                    duration_seconds=25 * 60,
                    question_types=("MCQ", "NON_MCQ"),
                    notes="Question count is reported combined for both areas.",
                ),
                _section(
                    "Advanced Coding", 2, question_count=2,
                    duration_seconds=90 * 60,
                    question_types=("CODING",),
                    supported=True,
                    coding_structure="Two coding questions.",
                ),
            ],
        },
        "rules": (
            _rule(
                "Advanced Coding", 2, "Coding", "CODING", 2,
                duration_seconds=90 * 60,
            ),
        ),
    },
    {
        "company_slug": "wipro",
        "program_name": "Wipro Elite National Talent Hunt",
        "pattern_version": "reported-2025-08",
        "blueprint_name": "Wipro Elite NTH — reported 2025",
        "source_name": "PrepInsta — Wipro NTH 2024 / Wipro Elite",
        "source_url": "https://prepinsta.com/wipro-nlth/",
        "source_type": "RECRUITMENT_REPORT",
        "source_published_at": date(2025, 8, 8),
        "verification_status": "REPORTED",
        "duration_seconds": 128 * 60,
        "notes": (
            "The source supports 128 minutes overall and two coding programs, "
            "but does not provide a reliable question count or time breakdown "
            "for aptitude subsections. Its page title says 2024 while its "
            "modified date is 2025-08-08."
        ),
        "details": {
            "reported_overall_duration_seconds": 128 * 60,
            "official_reference": "https://careers.wipro.com/",
            "coding_language_options": ["Java", "C", "C++", "Python"],
            "sections": [
                _section(
                    "Aptitude Test", 1,
                    question_types=("APTITUDE",),
                    notes=(
                        "Quantitative, verbal and logical material is listed; "
                        "the source does not support a complete count split."
                    ),
                ),
                _section(
                    "Coding", 2, question_count=2,
                    question_types=("CODING",),
                    supported=True,
                    coding_structure="Two programming problems.",
                ),
            ],
        },
        "rules": (
            _rule(
                "Coding", 2, "Coding", "CODING", 2,
            ),
        ),
    },
    {
        "company_slug": "capgemini",
        "program_name": "Capgemini Exceller Campus Assessment",
        "pattern_version": "reported-2026-02",
        "blueprint_name": "Capgemini Exceller — reported 2026",
        "source_name": "PrepInsta — Capgemini Exceller Placement Papers 2026",
        "source_url": "https://prepinsta.com/capgemini/",
        "source_type": "RECRUITMENT_REPORT",
        "source_published_at": date(2026, 2, 25),
        "verification_status": "REPORTED",
        "duration_seconds": None,
        "notes": (
            "Reported campus format. Technical and coding components are "
            "separate rounds. Behavioral timing is inconsistent within the "
            "source (omitted in one table and 20–25 minutes in another), and "
            "the complete overall duration is not established."
        ),
        "details": {
            "rounds": ["Online Assessment", "Coding"],
            "official_reference": "https://www.capgemini.com/in-en/careers/",
            "sections": [
                _section(
                    "Technical MCQs and Pseudocode", 1,
                    question_count=40,
                    duration_range_seconds=(40 * 60, 50 * 60),
                    question_types=("MCQ", "PSEUDOCODE"),
                    notes="Source gives a drive-dependent 40–50 minute range.",
                ),
                _section(
                    "English and Communication", 2, question_count=30,
                    duration_seconds=30 * 60,
                    question_types=("MCQ",),
                    supported=True,
                ),
                _section(
                    "Game-Based Cognitive Assessment", 3,
                    duration_range_seconds=(20 * 60, 30 * 60),
                    question_types=("INTERACTIVE_GAME",),
                    reported_game_count=4,
                    notes="Four games; game-based tasks are not bank questions.",
                ),
                _section(
                    "Behavioral / PowerSkills Assessment", 4,
                    duration_range_seconds=(20 * 60, 25 * 60),
                    question_types=("BEHAVIORAL",),
                    notes="The source omits timing in one table.",
                ),
                _section(
                    "Coding", 5, question_count=2,
                    duration_seconds=45 * 60,
                    question_types=("CODING",),
                    supported=True,
                    coding_structure="Two coding questions in the second round.",
                ),
            ],
        },
        "rules": (
            _rule(
                "English and Communication", 2, "Aptitude", "MCQ", 30,
                topic_name="Verbal Ability", duration_seconds=30 * 60,
            ),
            _rule(
                "Coding", 5, "Coding", "CODING", 2,
                duration_seconds=45 * 60,
            ),
        ),
    },
    {
        "company_slug": "infosys",
        "program_name": "Infosys Campus Written Assessment",
        "pattern_version": "reported-2026-01",
        "blueprint_name": "Infosys Campus Written Assessment — reported 2026",
        "source_name": "PrepInsta — Infosys Previous Papers with Solutions",
        "source_url": "https://prepinsta.com/infosys/",
        "source_type": "RECRUITMENT_REPORT",
        "source_published_at": date(2026, 1, 28),
        "verification_status": "REPORTED",
        "duration_seconds": 120 * 60,
        "notes": (
            "This is a general campus written-test report, not a confirmed "
            "pattern for HackWithInfy or Specialist Programmer. Only the "
            "Pseudocode section has a separately reported 10-minute duration."
        ),
        "details": {
            "reported_question_count": 60,
            "reported_overall_duration_seconds": 120 * 60,
            "official_reference": "https://www.infosys.com/careers.html",
            "sections": [
                _section("Reasoning Ability", 1, question_count=15),
                _section("Technical Ability", 2, question_count=10),
                _section("Verbal Ability", 3, question_count=20),
                _section(
                    "Pseudocode", 4, question_count=5,
                    duration_seconds=10 * 60,
                ),
                _section("Numerical Puzzle", 5, question_count=4),
                _section("English Grammar", 6, question_count=5),
                _section(
                    "English Writing", 7, question_count=1,
                    question_types=("WRITING",),
                    notes="One writing question; response format not specified.",
                ),
            ],
        },
        "rules": (
        ),
    },
    {
        "company_slug": "ltimindtree",
        "program_name": "LTM Fresher Online Test — Six-Section Report",
        "pattern_version": "reported-2026-05-a",
        "blueprint_name": "LTM Fresher Test — six-section report, 2026",
        "source_name": "FACE Prep — LTIMindtree Recruitment Process for Freshers",
        "source_url": "https://faceprep.in/article/mindtree-recruitment-process-for-freshers/",
        "source_type": "RECRUITMENT_REPORT",
        "source_published_at": date(2026, 5, 7),
        "verification_status": "REPORTED",
        "duration_seconds": 160 * 60,
        "notes": (
            "The 160-minute total is the sum of the six reported section "
            "durations. The source describes the current hiring cycle but is "
            "not an official LTM test specification. The source does not name "
            "coding languages or platform."
        ),
        "details": {
            "company_brand_context": (
                "LTM is the current corporate brand; this source refers to "
                "LTIMindtree."
            ),
            "reported_overall_duration_seconds": 160 * 60,
            "overall_duration_basis": "Sum of the six published section times.",
            "official_reference": "https://www.ltm.com/",
            "sections": [
                _section(
                    "Quantitative Aptitude", 1, question_count=10,
                    duration_seconds=20 * 60,
                ),
                _section(
                    "Logical Reasoning", 2, question_count=15,
                    duration_seconds=25 * 60,
                ),
                _section(
                    "Verbal Ability", 3, question_count=20,
                    duration_seconds=20 * 60,
                ),
                _section(
                    "Coding Challenges", 4, question_count=2,
                    duration_seconds=60 * 60,
                    question_types=("CODING",),
                    supported=True,
                    coding_structure="Two coding challenges; language unspecified.",
                ),
                _section(
                    "Technical MCQs", 5, question_count=10,
                    duration_seconds=15 * 60,
                    question_types=("MCQ",),
                    supported=True,
                ),
                _section(
                    "Psychometric Test", 6, question_count=50,
                    duration_seconds=20 * 60,
                    question_types=("PSYCHOMETRIC",),
                ),
            ],
        },
        "rules": (
            _rule(
                "Coding Challenges", 4, "Coding", "CODING", 2,
                duration_seconds=60 * 60,
            ),
            _rule(
                "Technical MCQs", 5, "Technical", "MCQ", 10,
                topic_name="Technical Concepts", duration_seconds=15 * 60,
            ),
        ),
    },
    {
        "company_slug": "ltimindtree",
        "program_name": "LTM Fresher Online Test — Four-Coding-Problem Report",
        "pattern_version": "reported-2026-05-b",
        "blueprint_name": "LTM Fresher Test — four coding problems, 2026",
        "source_name": "FACE Prep — Mindtree Test Pattern and Syllabus 2025",
        "source_url": "https://faceprep.in/article/mindtree-test-pattern-and-mindtree-syllabus-2025-face-prep/",
        "source_type": "RECRUITMENT_REPORT",
        "source_published_at": date(2026, 5, 1),
        "verification_status": "REPORTED",
        "duration_seconds": None,
        "notes": (
            "The source describes an approximately 180-minute 2026 structure "
            "and conflicts materially with the separate six-section LTM report "
            "(four coding problems here versus two there). Keep this as a "
            "separate reported variant; do not merge the reports."
        ),
        "details": {
            "reported_overall_duration_seconds": 180 * 60,
            "overall_duration_is_approximate": True,
            "implementation_language_options": ["C", "Java", "Python"],
            "official_reference": "https://careers.ltm.com/",
            "sections": [
                _section(
                    "English Communication", 1, question_count=20,
                    duration_seconds=20 * 60,
                ),
                _section(
                    "Quantitative Ability", 2, question_count=15,
                    duration_seconds=20 * 60,
                ),
                _section(
                    "Logical Reasoning", 3, question_count=15,
                    duration_seconds=20 * 60,
                ),
                _section(
                    "Technical Implementation", 4, question_count=2,
                    duration_seconds=60 * 60,
                    question_types=("CODING",),
                    supported=True,
                    coding_structure="Two implementation coding problems.",
                ),
                _section(
                    "Data Structures and Algorithms", 5, question_count=1,
                    duration_seconds=30 * 60,
                    question_types=("CODING",),
                    supported=True,
                    coding_structure="One coding problem.",
                ),
                _section(
                    "Advanced Algorithms", 6, question_count=1,
                    duration_seconds=30 * 60,
                    question_types=("CODING",),
                    supported=True,
                    coding_structure="One coding problem.",
                ),
            ],
        },
        "rules": (
            _rule(
                "Technical Implementation", 4, "Coding", "CODING", 2,
                duration_seconds=60 * 60,
            ),
            _rule(
                "Data Structures and Algorithms", 5, "Coding", "CODING", 1,
                duration_seconds=30 * 60,
            ),
            _rule(
                "Advanced Algorithms", 6, "Coding", "CODING", 1,
                duration_seconds=30 * 60,
            ),
        ),
    },
    {
        "company_slug": "cognizant",
        "program_name": "Cognizant GenC AMCAT — Historical Candidate Report",
        "pattern_version": "reported-2020-11",
        "blueprint_name": "Cognizant GenC AMCAT — historical 2020 report",
        "source_name": "GeeksforGeeks — Cognizant GenC Interview Experience",
        "source_url": "https://www.geeksforgeeks.org/interview-experiences/cognizant-genc-interview-experience/",
        "source_type": "CANDIDATE_REPORT",
        "source_published_at": date(2023, 1, 10),
        "verification_status": "REPORTED",
        "duration_seconds": 120 * 60,
        "notes": (
            "Historical candidate experience published 2020-11-30 and modified "
            "2023-01-10. It is not current-cycle evidence and must not be "
            "presented as the current GenC, GenC Next, or GenC Pro format. No "
            "current detailed variant was source-verified."
        ),
        "details": {
            "historical_publication_date": "2020-11-30",
            "historical_modified_date": "2023-01-10",
            "current_validity": "UNCERTAIN_HISTORICAL_REPORT",
            "other_reported_rounds": [
                {"name": "Combined technical/HR interview", "duration_seconds": 30 * 60}
            ],
            "official_reference": "https://careers.cognizant.com/india-en/",
            "sections": [
                _section(
                    "Quantitative", 1, question_count=24,
                    duration_seconds=35 * 60,
                    question_types=("APTITUDE",),
                ),
                _section(
                    "Logical Reasoning", 2, question_count=25,
                    duration_seconds=35 * 60,
                    question_types=("APTITUDE",),
                ),
                _section(
                    "Essay Writing", 3,
                    duration_seconds=30 * 60,
                    question_types=("WRITING",),
                    word_limit=200,
                ),
                _section(
                    "Automata Fix", 4, question_count=7,
                    duration_seconds=20 * 60,
                    question_types=("CODE_COMPLETION", "DEBUGGING"),
                    coding_structure=(
                        "Two function-completion tasks; remaining tasks "
                        "reported as syntax/logical error corrections."
                    ),
                    coding_language_options=["C", "C++", "Java"],
                ),
            ],
        },
        "rules": (),
    },
)


def _company_id(connection, slug: str, company_name: str) -> int:
    row = connection.execute(
        text("""
            SELECT company_id, company_name, slug
            FROM companies
            WHERE slug = :slug OR company_name = :company_name
        """),
        {"slug": slug, "company_name": company_name},
    ).mappings().all()
    if len(row) > 1:
        raise RuntimeError(
            f"Company name/slug collision for {company_name!r}."
        )
    if row:
        if row[0]["slug"] != slug or row[0]["company_name"] != company_name:
            raise RuntimeError(
                f"Existing company identity conflicts for {company_name!r}."
            )
        return int(row[0]["company_id"])
    result = connection.execute(
        text("""
            INSERT INTO companies (
                company_name, slug, description, official_pattern_verified
            )
            VALUES (
                :company_name, :slug, :description, FALSE
            )
        """),
        {
            "company_name": company_name,
            "slug": slug,
            "description": (
                "Company-specific assessment pattern metadata; each version "
                "includes its own source and verification status."
            ),
        },
    )
    return int(result.lastrowid)


def _deactivate_generic_prototypes(
    connection,
    *,
    deactivate: bool = True,
) -> list[int]:
    rows = connection.execute(
        text("""
            SELECT blueprint_id, company_id
            FROM test_blueprints
            WHERE blueprint_name = :blueprint_name
              AND program_name = :program_name
              AND pattern_version = :pattern_version
              AND verification_status = 'UNVERIFIED'
              AND status = 'ACTIVE'
            ORDER BY blueprint_id
        """),
        {
            "blueprint_name": PROTOTYPE_NAME,
            "program_name": PROTOTYPE_PROGRAM,
            "pattern_version": PROTOTYPE_VERSION,
        },
    ).mappings().all()
    blueprint_ids = [int(row["blueprint_id"]) for row in rows]
    for blueprint_id in blueprint_ids:
        actual = connection.execute(
            text("""
                SELECT section_name, section_order, question_count,
                       time_allocation_seconds
                FROM test_blueprint_rules
                WHERE blueprint_id = :blueprint_id
                ORDER BY section_order, blueprint_rule_id
            """),
            {"blueprint_id": blueprint_id},
        ).all()
        signature = tuple(
            (
                row.section_name,
                int(row.section_order),
                int(row.question_count),
                row.time_allocation_seconds,
            )
            for row in actual
        )
        if signature != PROTOTYPE_RULES:
            raise RuntimeError(
                f"Refusing to deactivate changed prototype blueprint "
                f"{blueprint_id}; its rules do not match the known generic seed."
            )
    if blueprint_ids and deactivate:
        connection.execute(
            text("""
                UPDATE test_blueprints
                SET status = 'INACTIVE'
                WHERE blueprint_id IN :blueprint_ids
            """).bindparams(bindparam("blueprint_ids", expanding=True)),
            {"blueprint_ids": tuple(blueprint_ids)},
        )
    return blueprint_ids


def _topic_and_track_ids(
    connection,
    track_name: str,
    topic_name: str | None,
) -> tuple[int, int | None]:
    track_id = connection.execute(
        text("SELECT track_id FROM tracks WHERE track_name = :track_name"),
        {"track_name": track_name},
    ).scalar_one_or_none()
    if track_id is None:
        raise RuntimeError(f"Required track {track_name!r} does not exist.")
    if topic_name is None:
        return int(track_id), None
    topic_id = connection.execute(
        text("""
            SELECT topic_id
            FROM topics
            WHERE track_id = :track_id AND topic_name = :topic_name
        """),
        {"track_id": track_id, "topic_name": topic_name},
    ).scalar_one_or_none()
    if topic_id is None:
        raise RuntimeError(
            f"Required topic {topic_name!r} does not exist in {track_name!r}."
        )
    return int(track_id), int(topic_id)


def _stored_pattern_details(value) -> dict | None:
    if value is None:
        return None
    return json.loads(value) if isinstance(value, str) else json.loads(json.dumps(value))


def _legacy_tcs_foundation_details() -> dict:
    return {
        "program_context": (
            "Foundation is reported as mandatory for Ninja aspirants; the "
            "source has surrounding references to 2025 despite a 2026 title."
        ),
        "reported_overall_duration_seconds": 76 * 60,
        "official_reference": "https://nextstep.tcsapps.com/indiacampus/",
        "sections": [
            _section(
                "Numerical Ability", 1, question_count=20,
                duration_seconds=25 * 60,
                question_types=("MCQ", "NON_MCQ"),
            ),
            _section(
                "Verbal Ability", 2, question_count=25,
                duration_seconds=26 * 60,
                question_types=("MCQ", "NON_MCQ"),
            ),
            _section(
                "Reasoning Ability", 3, question_count=20,
                duration_seconds=25 * 60,
                question_types=("MCQ", "NON_MCQ"),
            ),
        ],
    }


def _seed_pattern(
    connection,
    pattern: dict,
    companies_by_slug: dict[str, tuple[str, int]],
) -> tuple[int, str]:
    company_name, company_id = companies_by_slug[pattern["company_slug"]]
    details = json.loads(json.dumps(pattern["details"]))
    existing = connection.execute(
        text("""
            SELECT blueprint_id, blueprint_name, source_name, source_url,
                   source_type, source_published_at, source_accessed_at,
                   source_notes, pattern_details, verification_status,
                   verification_notes, duration_seconds, status, activated_at
            FROM test_blueprints
            WHERE company_id = :company_id
              AND program_name = :program_name
              AND pattern_version = :pattern_version
        """),
        {
            "company_id": company_id,
            "program_name": pattern["program_name"],
            "pattern_version": pattern["pattern_version"],
        },
    ).mappings().first()
    if existing is None:
        result = connection.execute(
            text("""
                INSERT INTO test_blueprints (
                    company_id, blueprint_name, program_name, pattern_version,
                    source_name, source_url, source_type, source_published_at,
                    source_accessed_at, source_notes, pattern_details,
                    verification_status, verification_notes, track_id,
                    duration_seconds, description, status
                )
                VALUES (
                    :company_id, :blueprint_name, :program_name, :pattern_version,
                    :source_name, :source_url, :source_type, :source_published_at,
                    :source_accessed_at, :source_notes, :pattern_details,
                    :verification_status, :verification_notes, NULL,
                    :duration_seconds, :description, 'INACTIVE'
                )
            """),
            {
                "company_id": company_id,
                "blueprint_name": pattern["blueprint_name"],
                "program_name": pattern["program_name"],
                "pattern_version": pattern["pattern_version"],
                "source_name": pattern["source_name"],
                "source_url": pattern["source_url"],
                "source_type": pattern["source_type"],
                "source_published_at": pattern["source_published_at"],
                "source_accessed_at": ACCESS_AT,
                "source_notes": pattern["notes"],
                "pattern_details": json.dumps(details),
                "verification_status": pattern["verification_status"],
                "verification_notes": pattern["notes"],
                "duration_seconds": pattern["duration_seconds"],
                "description": (
                    "Source-backed reported composition. Check readiness and "
                    "section-level uncertainty before activation."
                ),
            },
        )
        blueprint_id = int(result.lastrowid)
    else:
        blueprint_id = int(existing["blueprint_id"])
        expected = {
            "blueprint_name": pattern["blueprint_name"],
            "source_name": pattern["source_name"],
            "source_url": pattern["source_url"],
            "source_type": pattern["source_type"],
            "source_published_at": pattern["source_published_at"],
            "source_notes": pattern["notes"],
            "pattern_details": details,
            "verification_status": pattern["verification_status"],
            "duration_seconds": pattern["duration_seconds"],
        }
        actual = dict(existing)
        actual["pattern_details"] = _stored_pattern_details(
            actual["pattern_details"]
        )
        if mismatches := {
            key: (actual[key], value)
            for key, value in expected.items()
            if actual[key] != value
        }:
            can_update_tcs_foundation = (
                pattern["company_slug"] == "tcs"
                and pattern["program_name"] == "TCS NQT Foundation"
                and actual["status"] == "INACTIVE"
                and actual["activated_at"] is None
                and actual["source_notes"] == LEGACY_TCS_FOUNDATION_NOTES
                and actual["pattern_details"] == _legacy_tcs_foundation_details()
                and set(mismatches).issubset(
                    {"source_notes", "pattern_details"}
                )
            )
            if not can_update_tcs_foundation:
                raise RuntimeError(
                    f"Existing {pattern['program_name']} "
                    f"{pattern['pattern_version']} conflicts with seed "
                    f"metadata: {mismatches}"
                )
            connection.execute(
                text("""
                    UPDATE test_blueprints
                    SET source_notes = :source_notes,
                        verification_notes = :verification_notes,
                        pattern_details = :pattern_details
                    WHERE blueprint_id = :blueprint_id
                      AND status = 'INACTIVE'
                      AND activated_at IS NULL
                """),
                {
                    "blueprint_id": blueprint_id,
                    "source_notes": pattern["notes"],
                    "verification_notes": pattern["notes"],
                    "pattern_details": json.dumps(details),
                },
            )
            actual["source_notes"] = pattern["notes"]
            actual["pattern_details"] = details
        accessed_at = actual["source_accessed_at"]
        if accessed_at is None or accessed_at.date() != ACCESS_DATE:
            raise RuntimeError(
                f"Existing {pattern['program_name']} has an unexpected source "
                "access date."
            )

    expected_rules = []
    for rule in pattern["rules"]:
        track_id, topic_id = _topic_and_track_ids(
            connection, rule["track_name"], rule["topic_name"]
        )
        expected_rules.append(
            {
                **rule,
                "track_id": track_id,
                "topic_id": topic_id,
                "subtopic_id": None,
                "difficulty": None,
                "minimum_difficulty": None,
                "maximum_difficulty": None,
                "points": 1.0,
                "selection_weight": 1.0,
            }
        )
    existing_rules = connection.execute(
        text("""
            SELECT section_name, section_order, is_required,
                   time_allocation_seconds, selection_strategy, track_id,
                   topic_id, subtopic_id, question_type, difficulty,
                   minimum_difficulty, maximum_difficulty, question_count,
                   points, selection_weight
            FROM test_blueprint_rules
            WHERE blueprint_id = :blueprint_id
            ORDER BY section_order, blueprint_rule_id
        """),
        {"blueprint_id": blueprint_id},
    ).mappings().all()
    if existing_rules and len(existing_rules) != len(expected_rules):
        raise RuntimeError(
            f"Existing {pattern['program_name']} rules do not match the seed."
        )
    if existing_rules:
        for current, expected in zip(existing_rules, expected_rules):
            for key in (
                "section_name", "section_order", "is_required",
                "time_allocation_seconds", "selection_strategy", "track_id",
                "topic_id", "subtopic_id", "question_type", "difficulty",
                "minimum_difficulty", "maximum_difficulty", "question_count",
                "points", "selection_weight",
            ):
                expected_value = expected[key]
                if key in {"points", "selection_weight"}:
                    expected_value = Decimal(str(expected_value))
                if current[key] != expected_value:
                    raise RuntimeError(
                        f"Existing {pattern['program_name']} rule field {key} "
                        f"does not match the source-backed seed."
                    )
    elif expected_rules:
        if existing and (
            existing["status"] == "ACTIVE"
            or existing.get("activated_at") is not None
        ):
            raise RuntimeError(
                f"Refusing to alter activated pattern {blueprint_id}."
            )
        for rule in expected_rules:
            connection.execute(
                text("""
                    INSERT INTO test_blueprint_rules (
                        blueprint_id, section_name, section_order, is_required,
                        time_allocation_seconds, selection_strategy, track_id,
                        topic_id, subtopic_id, question_type, difficulty,
                        minimum_difficulty, maximum_difficulty, question_count,
                        points, selection_weight
                    )
                    VALUES (
                        :blueprint_id, :section_name, :section_order, :is_required,
                        :time_allocation_seconds, :selection_strategy, :track_id,
                        :topic_id, :subtopic_id, :question_type, :difficulty,
                        :minimum_difficulty, :maximum_difficulty, :question_count,
                        :points, :selection_weight
                    )
                """),
                {"blueprint_id": blueprint_id, **rule},
            )
    current_status = connection.execute(
        text("SELECT status FROM test_blueprints WHERE blueprint_id = :id"),
        {"id": blueprint_id},
    ).scalar_one()
    return blueprint_id, current_status


def seed(dry_run: bool = False) -> None:
    with engine.connect() as connection:
        if dry_run:
            for company_name, slug in COMPANIES:
                rows = connection.execute(
                    text("""
                        SELECT company_name, slug
                        FROM companies
                        WHERE slug = :slug OR company_name = :company_name
                    """),
                    {"slug": slug, "company_name": company_name},
                ).mappings().all()
                if len(rows) > 1 or (
                    rows
                    and (
                        rows[0]["slug"] != slug
                        or rows[0]["company_name"] != company_name
                    )
                ):
                    raise RuntimeError(
                        f"Company name/slug collision for {company_name!r}."
                    )
            for pattern in PATTERNS:
                for rule in pattern["rules"]:
                    _topic_and_track_ids(
                        connection, rule["track_name"], rule["topic_name"]
                    )
            prototypes = _deactivate_generic_prototypes(
                connection, deactivate=False
            )
            print(
                f"DRY RUN: {len(PATTERNS)} versioned patterns, "
                f"{sum(len(item['rules']) for item in PATTERNS)} rules, "
                f"{len(prototypes)} generic prototypes would be deactivated; "
                "no database writes performed."
            )
            return

        transaction = connection.begin()
        try:
            companies_by_slug = {}
            for company_name, slug in COMPANIES:
                company_id = _company_id(connection, slug, company_name)
                companies_by_slug[slug] = (company_name, company_id)

            deactivated = _deactivate_generic_prototypes(connection)
            records = []
            for pattern in PATTERNS:
                blueprint_id, status = _seed_pattern(
                    connection, pattern, companies_by_slug
                )
                errors = blueprint_service.validate_blueprint(
                    connection, blueprint_id
                )
                records.append((blueprint_id, pattern, status, errors))

            transaction.commit()
            action = "SEEDED"
        except Exception:
            transaction.rollback()
            raise

    print(f"{action}: {len(records)} versioned pattern records.")
    print(f"{'Would deactivate' if dry_run else 'Deactivated'} prototypes: {deactivated}")
    for blueprint_id, pattern, status, errors in records:
        problems = [
            error.get("code", error.get("message", "INVALID"))
            for error in errors
        ]
        print(
            f"blueprint_id={blueprint_id} company={pattern['company_slug']} "
            f"program={pattern['program_name']!r} "
            f"version={pattern['pattern_version']} "
            f"verification={pattern['verification_status']} "
            f"status={status} rules={len(pattern['rules'])} "
            f"validation_errors={len(errors)} problems={problems}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Roll back all database writes after validating the seed.",
    )
    args = parser.parse_args()
    seed(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
