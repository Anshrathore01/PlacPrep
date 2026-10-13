#!/usr/bin/env python3
"""Import the 10 TCS NQT full-length source papers from PAP/ into MySQL."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

DATABASE_URL = (
    os.getenv("DATABASE_URL")
    or f"mysql+pymysql://{os.getenv('DB_USER', 'root')}:{os.getenv('DB_PASSWORD', '12345678')}@{os.getenv('DB_HOST', 'localhost')}:{os.getenv('DB_PORT', '3306')}/{os.getenv('DB_NAME', 'placement_platform')}"
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PAP_DIR = PROJECT_ROOT / "PAP"
if not PAP_DIR.exists():
    PAP_DIR = Path("/Users/anshrathore/placement-platform/PAP")

SOURCE_NAME = "TCS NQT Full Length Papers"
DEFAULT_DURATION_SECONDS = 1800
QUESTION_TRACK_ID = 1

SECTION_TRIGGERS = [
    (re.compile(r"##\s*Numerical Ability", re.I), "Numerical Ability"),
    (re.compile(r"##\s*Verbal Ability", re.I), "Verbal Ability"),
    (re.compile(r"##\s*Coding", re.I), "Advanced Coding"),
    (re.compile(r"^(?:##\s*)?Reasoning Ability[:\s]*$", re.I), "Reasoning Ability"),
    (re.compile(r"^(?:##\s*)?Advanced Coding[:\s]*$", re.I), "Advanced Coding"),
    (re.compile(r"^(?:##\s*)?Advanced Quantitative[:\s]*$", re.I), "Advanced Quantitative"),
    (re.compile(r"^(?:##\s*)?Advanced Reasoning[:\s]*$", re.I), "Advanced Reasoning"),
    (re.compile(r"^(?:##\s*)?Advanced Logical[:\s]*$", re.I), "Advanced Logical"),
    # Inline triggers right before ### Question 1
    (re.compile(r"Logical Section\s*$", re.I), "Reasoning Ability"),
    (re.compile(r"Reasoning Ability\s*$", re.I), "Reasoning Ability"),
    (re.compile(r"Advanced Coding\s*$", re.I), "Advanced Coding"),
    (re.compile(r"Advanced Quantitative\s*$", re.I), "Advanced Quantitative"),
    (re.compile(r"Advanced Reasoning\s*$", re.I), "Advanced Reasoning"),
    (re.compile(r"Advanced Logical\s*$", re.I), "Advanced Logical"),
    (re.compile(r"## Verbal Ability\s*$", re.I), "Verbal Ability"),
]

OPTION_MARKER = re.compile(
    r"^\s*(?:[-*•+]\s*)?(?:(?P<label>[A-Ea-e])|(?P<num>[1-5]))\s*[.)]\s*(?P<text>\S.*)$"
)

ANSWER_LINE = re.compile(
    r"^\s*(?:\*\*)?Answer(?:\*\*)?\s*:\s*(?:\*\*)?\s*(.*?)(?:\*\*)?\s*$",
    re.IGNORECASE,
)

PASSAGE_INTRO = re.compile(
    r"^(?:[-*•–—\s]*)?Read the (?:given |following )?passage(?: and answer the questions? that follow)?[.:]?",
    re.IGNORECASE,
)


def paper_title_for_number(paper_number: int) -> str:
    return f"TCS NQT Full Length Paper {paper_number:02d}"


def source_question_number_for(paper_number: int, source_position: int) -> int:
    return (paper_number * 100_000) + source_position


def format_clean_text(val: str | None) -> str:
    """Preserve paragraphs and line breaks while normalizing intra-line spaces."""
    if not val:
        return ""
    text_content = val.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text_content.split("\n")]
    compact: list[str] = []
    for line in lines:
        if not line:
            if compact and compact[-1] != "":
                compact.append("")
        else:
            compact.append(line)
    while compact and not compact[0]:
        compact.pop(0)
    while compact and not compact[-1]:
        compact.pop()
    return "\n".join(compact).strip()


def split_file_into_blocks(filepath: Path) -> list[dict[str, Any]]:
    text_content = filepath.read_text(encoding="utf-8")
    lines = text_content.splitlines()
    current_section = "General"
    blocks: list[dict[str, Any]] = []
    current_block: dict[str, Any] | None = None

    for idx, line in enumerate(lines):
        stripped = line.strip()
        found_sec = None
        for pattern, sec_name in SECTION_TRIGGERS:
            if pattern.search(stripped):
                if (
                    "##" in pattern.pattern
                    or stripped.endswith(sec_name)
                    or stripped.endswith(sec_name + ":")
                    or "Logical Section" in stripped
                ):
                    if idx + 1 < len(lines) and re.match(r"^###\s+Question\s+1\b", lines[idx + 1].strip()):
                        found_sec = sec_name
                        break
                    elif (
                        idx + 2 < len(lines)
                        and re.match(r"^###\s+Question\s+1\b", lines[idx + 2].strip())
                        and not lines[idx + 1].strip()
                    ):
                        found_sec = sec_name
                        break
                    elif re.match(r"^(?:##\s*)?[A-Za-z\s]+[:\s]*$", stripped):
                        found_sec = sec_name
                        break

        if found_sec:
            current_section = found_sec

        q_match = re.match(r"^###\s+Question\s+(\d+)\s*$", stripped)
        if q_match:
            if current_block:
                blocks.append(current_block)
            current_block = {
                "section": current_section,
                "qnum": int(q_match.group(1)),
                "lines": [],
                "start_line": idx + 1,
            }
        else:
            if current_block:
                current_block["lines"].append(line)

    if current_block:
        blocks.append(current_block)

    # In paper-02.md, block 51 is a duplicate header containing only the reading passage
    # for Question 19, followed immediately by block 52 (Question 19 question statement)
    if filepath.name == "paper-02.md" and len(blocks) >= 53:
        if blocks[51]["qnum"] == 19 and blocks[52]["qnum"] == 19:
            passage_lines = blocks[51]["lines"]
            blocks[52]["lines"] = passage_lines + [""] + blocks[52]["lines"]
            blocks.pop(51)

    return blocks


def is_coding(section: str, lines: list[str]) -> bool:
    body = "\n".join(lines)
    if "Coding" in section:
        return True
    body_lower = body.lower()
    if "python" in body_lower and (
        "def " in body_lower or "input().split()" in body_lower or "constraints:" in body_lower
    ):
        return True
    return False


def parse_coding(block: dict[str, Any]) -> dict[str, Any]:
    body = "\n".join(block["lines"]).strip()

    constraints = None
    input_format = None
    output_format = None
    starter_code = None
    solution = None

    cm = re.search(
        r"Constraints:\s*(.*?)(?=(?:\n\s*(?:The input format|The Output format|Instructions:|Python\b)|\Z))",
        body,
        re.I | re.S,
    )
    if cm:
        constraints = format_clean_text(cm.group(1))

    im = re.search(
        r"The input format(?: for testing)?[:\-]?\s*(.*?)(?=(?:\n\s*(?:The [oO]utput format|Instructions:|Python\b)|\Z))",
        body,
        re.I | re.S,
    )
    if im:
        input_format = format_clean_text(im.group(1))

    om = re.search(
        r"The output format(?: for testing)?[:\-]?\s*(.*?)(?=(?:\n\s*(?:Instructions:|Python\b)|\Z))",
        body,
        re.I | re.S,
    )
    if om:
        output_format = format_clean_text(om.group(1))

    pym = re.search(r"(?:^|\n)Python\s*\n(.*)$", body, re.I | re.S)
    if pym:
        starter_code = pym.group(1).strip()
        solution = starter_code

    first_marker = len(body)
    for m in [cm, im, om]:
        if m and m.start() < first_marker:
            first_marker = m.start()
    ex_m = re.search(r"Example\s+\d+:", body, re.I)
    if ex_m and ex_m.start() < first_marker:
        first_marker = ex_m.start()

    problem_statement = format_clean_text(body[:first_marker])

    examples: list[dict[str, Any]] = []
    for match in re.finditer(
        r"Example\s+(\d+):\s*(.*?)(?=(?:\n\s*Example\s+\d+:)|\n\s*(?:Constraints:|The input format|The Output format|Instructions:|Python\b|\Z))",
        body,
        re.I | re.S,
    ):
        ex_num = int(match.group(1))
        ex_content = match.group(2).strip()
        in_m = re.search(r"Input:\s*(.*?)(?=\n\s*(?:Output:|Explanation:)|\Z)", ex_content, re.I | re.S)
        out_m = re.search(r"Output:\s*(.*?)(?=\n\s*(?:Explanation:)|\Z)", ex_content, re.I | re.S)
        exp_m = re.search(r"Explanation:\s*(.*)", ex_content, re.I | re.S)
        examples.append({
            "example_number": ex_num,
            "input_data": format_clean_text(in_m.group(1)) if in_m else None,
            "output_data": format_clean_text(out_m.group(1)) if out_m else None,
            "explanation": format_clean_text(exp_m.group(1)) if exp_m else None,
        })

    return {
        "question_type": "CODING",
        "problem_statement": problem_statement,
        "question_text": problem_statement,
        "constraints_text": constraints,
        "input_format": input_format,
        "output_format": output_format,
        "starter_code": starter_code,
        "solution_pseudocode": solution,
        "solution_explanation": solution,
        "examples": examples,
    }


def find_option_runs(lines: list[str]) -> tuple[list[tuple[int, str, str]], int | None]:
    ans_line_idx = None
    for i, l in enumerate(lines):
        if ANSWER_LINE.match(l):
            ans_line_idx = i
            break

    content_lines = lines[:ans_line_idx] if ans_line_idx is not None else lines

    candidates = []
    for i, l in enumerate(content_lines):
        m = OPTION_MARKER.match(l)
        if m:
            label = (m.group("label") or m.group("num")).upper()
            text_val = m.group("text").strip()
            candidates.append((i, label, text_val))

    if not candidates:
        return [], ans_line_idx

    runs: list[list[tuple[int, str, str]]] = []
    for c in candidates:
        if not runs:
            runs.append([c])
            continue
        prev = runs[-1][-1]
        exp = chr(ord(prev[1]) + 1) if prev[1].isalpha() else str(int(prev[1]) + 1)
        if c[1] == exp:
            runs[-1].append(c)
        else:
            runs.append([c])

    valid_4 = [r for r in runs if len(r) in (4, 5) and r[0][1] in {"A", "1"}]
    if valid_4:
        return valid_4[-1], ans_line_idx

    valid_other = [r for r in runs if len(r) in (2, 3) and r[0][1] in {"A", "1"}]
    if valid_other:
        return valid_other[-1], ans_line_idx

    return [], ans_line_idx


def parse_answer_key(raw_answer: str, options: list[dict[str, Any]]) -> str | None:
    if not raw_answer:
        return None
    raw = raw_answer.strip()

    m = re.search(r"(?i)\b(?:option\s+)?([A-E])\b", raw)
    if m:
        letter = m.group(1).upper()
        if any(o["option_key"] == letter for o in options):
            return letter

    m = re.search(r"(?i)\b([A-E])\s*[-–—]", raw)
    if m:
        letter = m.group(1).upper()
        if any(o["option_key"] == letter for o in options):
            return letter

    if re.fullmatch(r"[1-5]", raw):
        idx = int(raw) - 1
        if 0 <= idx < len(options):
            return options[idx]["option_key"]

    clean_ans = re.sub(r"\s+", " ", raw).strip().lower()
    for o in options:
        clean_opt = re.sub(r"\s+", " ", o["option_text"]).strip().lower()
        if clean_opt == clean_ans or clean_opt.rstrip(".") == clean_ans.rstrip("."):
            return o["option_key"]

    return None


def parse_mcq(block: dict[str, Any], active_passage: str | None = None) -> tuple[dict[str, Any], str | None]:
    lines = block["lines"]
    run, ans_line_idx = find_option_runs(lines)

    answer_text = None
    if ans_line_idx is not None:
        m = ANSWER_LINE.match(lines[ans_line_idx])
        if m:
            answer_text = m.group(1).strip().strip("*").strip()
        exp_lines = [lines[j].strip() for j in range(ans_line_idx + 1, len(lines)) if lines[j].strip()]
        if exp_lines:
            extra = "\n".join(exp_lines)
            answer_text = f"{answer_text}\n{extra}" if answer_text else extra

    options: list[dict[str, Any]] = []
    option_start_line = None
    if run:
        option_start_line = run[0][0]
        content_lines = lines[:ans_line_idx] if ans_line_idx is not None else lines
        keys = ["A", "B", "C", "D", "E"]
        for pos, (l_idx, marker, first_line) in enumerate(run):
            next_l_idx = run[pos + 1][0] if pos + 1 < len(run) else len(content_lines)
            opt_body = [first_line]
            for cont_idx in range(l_idx + 1, next_l_idx):
                opt_body.append(content_lines[cont_idx])
            opt_text = format_clean_text("\n".join(opt_body))
            opt_text = re.sub(r"^(?:[A-Ea-e1-5][.)]|\([A-Ea-e1-5]\))\s*", "", opt_text)
            options.append({
                "option_key": keys[pos],
                "option_text": opt_text,
                "display_order": pos + 1,
            })

    q_lines = (
        lines[:option_start_line]
        if option_start_line is not None
        else (lines[:ans_line_idx] if ans_line_idx is not None else lines)
    )
    raw_question_text = "\n".join(q_lines).strip()

    passage = None
    question_statement = raw_question_text

    pass_m = PASSAGE_INTRO.search(raw_question_text)
    if pass_m:
        pass_start = pass_m.start()
        pass_body = raw_question_text[pass_start:]
        q_markers = [
            r"\n\s*(?:Which of the following\b.*)",
            r"\n\s*(?:Based on the information\b.*)",
            r"\n\s*(?:According to the passage\b.*)",
            r"\n\s*(?:What do you infer\b.*)",
            r"\n\s*(?:Would you infer\b.*)",
            r"\n\s*(?:Why do\b.*)",
            r"\n\s*(?:Is George\b.*)",
            r"\n\s*(?:“[^”]+”\s*What caused\b.*)",
        ]
        q_found_idx = None
        for qm in q_markers:
            m = re.search(qm, pass_body, re.I)
            if m and (q_found_idx is None or m.start() < q_found_idx):
                q_found_idx = m.start()

        if q_found_idx is not None:
            passage = format_clean_text(pass_body[:q_found_idx])
            question_statement = format_clean_text(pass_body[q_found_idx:])
        else:
            passage = format_clean_text(pass_body)
            question_statement = passage

        active_passage = passage
    elif active_passage is not None:
        if re.search(r"\bpassage\b", raw_question_text, re.I) or "infer" in raw_question_text.lower():
            passage = active_passage
            question_statement = format_clean_text(raw_question_text)
        else:
            active_passage = None
            question_statement = format_clean_text(raw_question_text)
    else:
        question_statement = format_clean_text(raw_question_text)

    correct_key = parse_answer_key(answer_text or "", options)

    return {
        "question_type": "MCQ",
        "question_text": question_statement,
        "passage": passage,
        "options": options,
        "answer_text": answer_text,
        "correct_option_key": correct_key,
    }, active_passage


def parse_options(lines: list[str]) -> tuple[list[str], str | None]:
    data, _ = parse_mcq({"lines": lines})
    if len(data["options"]) < 4:
        return [], data.get("answer_text")
    return [opt["option_text"] for opt in data["options"]], data.get("answer_text")


def clean_question_text(lines: list[str]) -> str:
    data, _ = parse_mcq({"lines": lines})
    return data["question_text"]


def questions_for_paper(paper_file: Path) -> list[dict[str, Any]]:
    blocks = split_file_into_blocks(paper_file)
    items: list[dict[str, Any]] = []
    active_passage = None

    for pos, block in enumerate(blocks, start=1):
        if is_coding(block["section"], block["lines"]):
            data = parse_coding(block)
            data["section"] = block["section"]
            data["question_number"] = block["qnum"]
            data["source_position"] = pos
            items.append(data)
            active_passage = None
        else:
            data, active_passage = parse_mcq(block, active_passage)
            data["section"] = block["section"]
            data["question_number"] = block["qnum"]
            data["source_position"] = pos
            items.append(data)

    return items


def get_or_create_source(conn) -> int:
    row = conn.execute(
        text("SELECT source_id FROM sources WHERE source_name = :source_name LIMIT 1"),
        {"source_name": SOURCE_NAME},
    ).mappings().first()
    if row is not None:
        return int(row["source_id"])

    result = conn.execute(
        text("INSERT INTO sources (source_name, source_type, description) VALUES (:name, 'PAST_PAPER', :desc)"),
        {"name": SOURCE_NAME, "desc": "Imported previous year TCS NQT examination papers"},
    )
    return int(result.lastrowid)


def get_or_create_mock(conn, paper_title: str, paper_number: int) -> int:
    aliases = [paper_title, f"TCS NQT Paper {paper_number:02d}"]
    row = conn.execute(
        text(
            """
            SELECT mock_test_id, title
            FROM mock_tests
            WHERE title IN (:title_1, :title_2)
            ORDER BY mock_test_id
            LIMIT 1
            """
        ),
        {"title_1": aliases[0], "title_2": aliases[1]},
    ).mappings().first()
    if row is not None:
        mock_id = int(row["mock_test_id"])
        # Ensure title is canonical
        if row["title"] != paper_title:
            conn.execute(
                text("UPDATE mock_tests SET title = :title WHERE mock_test_id = :mock_test_id"),
                {"title": paper_title, "mock_test_id": mock_id},
            )
        return mock_id

    result = conn.execute(
        text(
            """
            INSERT INTO mock_tests (
                title, mode, selection_mode, duration_seconds, total_questions, status
            )
            VALUES (:title, 'MOCK', 'FIXED_QUESTIONS', :duration_seconds, 0, 'PUBLISHED')
            """
        ),
        {"title": paper_title, "duration_seconds": DEFAULT_DURATION_SECONDS},
    )
    return int(result.lastrowid)


def upsert_question(
    conn,
    source_id: int,
    paper_title: str,
    paper_number: int,
    section_name: str,
    question_number: int,
    item: dict[str, Any],
) -> int:
    unique_question_number = source_question_number_for(paper_number, item["source_position"])
    title = f"{paper_title} – {section_name} – Q{question_number}"

    # Build source_metadata
    source_metadata_dict: dict[str, Any] = {
        "paper_title": paper_title,
        "paper_number": paper_number,
        "source_position": item["source_position"],
        "section": section_name,
        "source_question_number": question_number,
    }
    if item.get("passage"):
        source_metadata_dict["passage"] = item["passage"]
    if item.get("answer_text"):
        source_metadata_dict["source_answer"] = item["answer_text"]

    source_metadata_json = json.dumps(source_metadata_dict, ensure_ascii=False)

    hash_dict = {
        "source_id": source_id,
        "paper_number": paper_number,
        "source_position": item["source_position"],
        "section": section_name,
        "question_number": question_number,
        "question_type": item["question_type"],
        "question_text": item.get("question_text") or item.get("problem_statement"),
        "passage": item.get("passage"),
        "correct_option_key": item.get("correct_option_key"),
    }
    content_hash = hashlib.sha256(json.dumps(hash_dict, sort_keys=True).encode("utf-8")).hexdigest()

    existing_row = conn.execute(
        text(
            "SELECT question_id FROM questions WHERE source_id = :source_id AND source_question_number = :source_question_number LIMIT 1"
        ),
        {"source_id": source_id, "source_question_number": unique_question_number},
    ).mappings().first()

    if existing_row is not None:
        question_id = int(existing_row["question_id"])
        conn.execute(
            text(
                """
                UPDATE questions
                SET question_type = :question_type,
                    title = :title,
                    content_hash = :content_hash,
                    source_metadata = :source_metadata,
                    status = 'PUBLISHED'
                WHERE question_id = :question_id
                """
            ),
            {
                "question_id": question_id,
                "question_type": item["question_type"],
                "title": title,
                "content_hash": content_hash,
                "source_metadata": source_metadata_json,
            },
        )
    else:
        track_id = 3 if item["question_type"] == "CODING" else QUESTION_TRACK_ID
        res = conn.execute(
            text(
                """
                INSERT INTO questions (
                    source_id, source_question_number, question_type, track_id, title,
                    difficulty, status, content_hash, source_metadata
                )
                VALUES (
                    :source_id, :source_question_number, :question_type, :track_id, :title,
                    'MEDIUM', 'PUBLISHED', :content_hash, :source_metadata
                )
                """
            ),
            {
                "source_id": source_id,
                "source_question_number": unique_question_number,
                "question_type": item["question_type"],
                "track_id": track_id,
                "title": title,
                "content_hash": content_hash,
                "source_metadata": source_metadata_json,
            },
        )
        question_id = int(res.lastrowid)

    # Upsert specific details
    if item["question_type"] == "MCQ":
        mcq_exists = conn.execute(
            text("SELECT 1 FROM mcq_questions WHERE question_id = :question_id LIMIT 1"),
            {"question_id": question_id},
        ).scalar()
        if mcq_exists:
            conn.execute(
                text(
                    """
                    UPDATE mcq_questions
                    SET question_text = :question_text,
                        explanation = :explanation,
                        correct_option_key = :correct_option_key
                    WHERE question_id = :question_id
                    """
                ),
                {
                    "question_id": question_id,
                    "question_text": item["question_text"],
                    "explanation": item.get("answer_text") or None,
                    "correct_option_key": item.get("correct_option_key"),
                },
            )
        else:
            conn.execute(
                text(
                    """
                    INSERT INTO mcq_questions (
                        question_id, question_text, explanation, correct_option_key, is_multiple_correct
                    )
                    VALUES (:question_id, :question_text, :explanation, :correct_option_key, 0)
                    """
                ),
                {
                    "question_id": question_id,
                    "question_text": item["question_text"],
                    "explanation": item.get("answer_text") or None,
                    "correct_option_key": item.get("correct_option_key"),
                },
            )

        # Refresh options
        conn.execute(
            text("DELETE FROM mcq_options WHERE question_id = :question_id"),
            {"question_id": question_id},
        )
        for opt in item.get("options", []):
            conn.execute(
                text(
                    """
                    INSERT INTO mcq_options (question_id, option_key, option_text, display_order)
                    VALUES (:question_id, :option_key, :option_text, :display_order)
                    """
                ),
                {
                    "question_id": question_id,
                    "option_key": opt["option_key"],
                    "option_text": opt["option_text"],
                    "display_order": opt["display_order"],
                },
            )

    elif item["question_type"] == "CODING":
        coding_exists = conn.execute(
            text("SELECT 1 FROM coding_questions WHERE question_id = :question_id LIMIT 1"),
            {"question_id": question_id},
        ).scalar()
        if coding_exists:
            conn.execute(
                text(
                    """
                    UPDATE coding_questions
                    SET problem_statement = :problem_statement,
                        constraints_text = :constraints_text,
                        input_format = :input_format,
                        output_format = :output_format,
                        starter_code = :starter_code,
                        solution_pseudocode = :solution_pseudocode,
                        solution_explanation = :solution_explanation
                    WHERE question_id = :question_id
                    """
                ),
                {
                    "question_id": question_id,
                    "problem_statement": item.get("problem_statement"),
                    "constraints_text": item.get("constraints_text"),
                    "input_format": item.get("input_format"),
                    "output_format": item.get("output_format"),
                    "starter_code": item.get("starter_code"),
                    "solution_pseudocode": item.get("solution_pseudocode"),
                    "solution_explanation": item.get("solution_explanation"),
                },
            )
        else:
            conn.execute(
                text(
                    """
                    INSERT INTO coding_questions (
                        question_id, problem_statement, constraints_text, input_format,
                        output_format, starter_code, solution_pseudocode, solution_explanation
                    )
                    VALUES (
                        :question_id, :problem_statement, :constraints_text, :input_format,
                        :output_format, :starter_code, :solution_pseudocode, :solution_explanation
                    )
                    """
                ),
                {
                    "question_id": question_id,
                    "problem_statement": item.get("problem_statement"),
                    "constraints_text": item.get("constraints_text"),
                    "input_format": item.get("input_format"),
                    "output_format": item.get("output_format"),
                    "starter_code": item.get("starter_code"),
                    "solution_pseudocode": item.get("solution_pseudocode"),
                    "solution_explanation": item.get("solution_explanation"),
                },
            )

        # Refresh examples
        conn.execute(
            text("DELETE FROM question_examples WHERE question_id = :question_id"),
            {"question_id": question_id},
        )
        for ex in item.get("examples", []):
            conn.execute(
                text(
                    """
                    INSERT INTO question_examples (
                        question_id, example_number, input_data, output_data, explanation
                    )
                    VALUES (:question_id, :example_number, :input_data, :output_data, :explanation)
                    """
                ),
                {
                    "question_id": question_id,
                    "example_number": ex["example_number"],
                    "input_data": ex.get("input_data"),
                    "output_data": ex.get("output_data"),
                    "explanation": ex.get("explanation"),
                },
            )

    return question_id


def synchronize_mock_questions(conn, mock_test_id: int, assigned_question_ids: list[int]) -> None:
    assigned_set = set(assigned_question_ids)
    existing_ids = set(
        conn.execute(
            text("SELECT question_id FROM mock_test_questions WHERE mock_test_id = :mock_test_id"),
            {"mock_test_id": mock_test_id},
        ).scalars()
    )

    # Remove questions no longer belonging to this mock
    for qid in existing_ids - assigned_set:
        conn.execute(
            text("DELETE FROM mock_test_questions WHERE mock_test_id = :mock_test_id AND question_id = :question_id"),
            {"mock_test_id": mock_test_id, "question_id": qid},
        )

    # Offset sequence numbers to avoid unique constraint collision during resequencing
    conn.execute(
        text("UPDATE mock_test_questions SET sequence_no = sequence_no + 100000 WHERE mock_test_id = :mock_test_id"),
        {"mock_test_id": mock_test_id},
    )

    for seq, qid in enumerate(assigned_question_ids, start=1):
        if qid in existing_ids:
            conn.execute(
                text(
                    "UPDATE mock_test_questions SET sequence_no = :seq, points = 1 WHERE mock_test_id = :mock_test_id AND question_id = :qid"
                ),
                {"mock_test_id": mock_test_id, "qid": qid, "seq": seq},
            )
        else:
            conn.execute(
                text(
                    "INSERT INTO mock_test_questions (mock_test_id, question_id, sequence_no, points) VALUES (:mock_test_id, :qid, :seq, 1)"
                ),
                {"mock_test_id": mock_test_id, "qid": qid, "seq": seq},
            )


def verify_all_papers_present() -> list[Path]:
    papers = sorted(PAP_DIR.glob("paper-*.md"))
    expected_numbers = set(range(1, 11))
    found_numbers = {
        int(m.group(1))
        for p in papers
        if (m := re.search(r"paper-(\d+)", p.name)) is not None
    }
    missing = expected_numbers - found_numbers
    if missing:
        raise FileNotFoundError(
            f"Missing required paper files in {PAP_DIR}: {sorted(missing)}"
        )
    return papers


def main() -> None:
    parser = argparse.ArgumentParser(description="Import TCS NQT full-length papers.")
    parser.add_argument("--paper", type=int, action="append", dest="paper_numbers", help="Specific paper number(s)")
    args = parser.parse_args()

    all_papers = verify_all_papers_present()
    if args.paper_numbers:
        requested = set(args.paper_numbers)
        papers_to_import = [
            p for p in all_papers if int(re.search(r"paper-(\d+)", p.name).group(1)) in requested
        ]
    else:
        papers_to_import = all_papers

    print(f"Source directory: {PAP_DIR}")
    print(f"Found {len(all_papers)} papers in PAP/ directory. Importing {len(papers_to_import)} paper(s)...\n")

    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    summary_report: list[dict[str, Any]] = []

    with engine.begin() as conn:
        source_id = get_or_create_source(conn)

        for paper_file in papers_to_import:
            paper_num = int(re.search(r"paper-(\d+)", paper_file.name).group(1))
            paper_title = paper_title_for_number(paper_num)

            items = questions_for_paper(paper_file)
            mock_id = get_or_create_mock(conn, paper_title, paper_num)

            assigned_qids: list[int] = []
            sections_count: dict[str, int] = {}
            mcq_count = 0
            coding_count = 0

            for it in items:
                sec = it["section"]
                sections_count[sec] = sections_count.get(sec, 0) + 1
                if it["question_type"] == "CODING":
                    coding_count += 1
                else:
                    mcq_count += 1

                qid = upsert_question(
                    conn,
                    source_id=source_id,
                    paper_title=paper_title,
                    paper_number=paper_num,
                    section_name=sec,
                    question_number=it["question_number"],
                    item=it,
                )
                assigned_qids.append(qid)

            synchronize_mock_questions(conn, mock_id, assigned_qids)

            total_q = len(assigned_qids)
            conn.execute(
                text("UPDATE mock_tests SET total_questions = :total_questions, status = 'PUBLISHED' WHERE mock_test_id = :mock_test_id"),
                {"total_questions": total_q, "mock_test_id": mock_id},
            )

            summary_report.append({
                "paper": f"Paper {paper_num:02d}",
                "mock_id": mock_id,
                "total": total_q,
                "mcq": mcq_count,
                "coding": coding_count,
                "sections": sections_count,
            })

            print(f"✓ {paper_title} (mock_id={mock_id}): {total_q} questions (MCQ: {mcq_count}, Coding: {coding_count})")
            for sec, cnt in sections_count.items():
                print(f"    - {sec}: {cnt}")

    print("\n" + "=" * 60)
    print("ALL PAPERS SUCCESSFULLY IMPORTED AND SYNCHRONIZED!")
    print("=" * 60)


if __name__ == "__main__":
    main()
