import json

MOCK_SELECTION_PROMPT_VERSION = "v1"


def build_selection_prompt(
    candidates: list[dict],
    requested_count: int,
    difficulty: str,
    filters: dict,
) -> str:
    return (
        "You are an AI question curator for a placement preparation platform. "
        "Choose only existing question IDs from the supplied candidate records. "
        "Never invent IDs, create questions, change question content, return "
        "explanations, or return answer keys. Return exactly the requested number "
        "of distinct IDs. Every candidate already matches the required difficulty "
        "and filters; select a conceptually diverse set and avoid repeated wording "
        "or concepts where possible. The response must match the required schema.\n"
        f"Prompt version: {MOCK_SELECTION_PROMPT_VERSION}\n"
        f"Difficulty: {difficulty}\n"
        f"Required count: {requested_count}\n"
        f"Additional filters: {json.dumps(filters, sort_keys=True)}\n"
        f"Candidates: {json.dumps(candidates, ensure_ascii=True)}"
    )
