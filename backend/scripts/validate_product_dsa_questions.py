"""Validate the static product-company DSA catalog without contacting providers."""

import json
from collections import Counter
from pathlib import Path


CATALOG_PATH = Path(__file__).resolve().parents[1] / "app" / "product_dsa_questions.json"
EXPECTED_COUNT = 200
DIFFICULTIES = {"Easy", "Medium", "Hard"}
PLATFORMS = {"LeetCode", "GeeksforGeeks"}


def load_and_validate() -> list[dict]:
    questions = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    if len(questions) != EXPECTED_COUNT:
        raise ValueError(f"Expected {EXPECTED_COUNT} questions, got {len(questions)}")

    fields = {"id", "question_number", "title", "topic", "difficulty", "platform", "url"}
    for question in questions:
        missing = fields - question.keys()
        if missing:
            raise ValueError(f"Question is missing fields: {sorted(missing)}")
        if question["difficulty"] not in DIFFICULTIES:
            raise ValueError(f"Invalid difficulty: {question['difficulty']}")
        if question["platform"] not in PLATFORMS:
            raise ValueError(f"Invalid platform: {question['platform']}")
        if not question["topic"] or not question["title"]:
            raise ValueError("Question title and topic must be non-empty")
        if "is_completed" in question:
            raise ValueError("Completion state must not be stored in the shared question bank")
        expected_host = "leetcode.com" if question["platform"] == "LeetCode" else "www.geeksforgeeks.org"
        if not question["url"].startswith(f"https://{expected_host}/problems/"):
            raise ValueError(f"Unexpected problem URL for {question['id']}: {question['url']}")

    for field in ("id", "question_number", "title", "url"):
        values = [str(question[field]).casefold() for question in questions]
        duplicates = [value for value, count in Counter(values).items() if count > 1]
        if duplicates:
            raise ValueError(f"Duplicate {field} values: {duplicates}")
    numbers = sorted(question["question_number"] for question in questions)
    if numbers != list(range(1, EXPECTED_COUNT + 1)):
        raise ValueError("Question numbers must cover 1 through 200 exactly")
    return questions


if __name__ == "__main__":
    data = load_and_validate()
    print(f"Valid catalog: {len(data)} questions")
