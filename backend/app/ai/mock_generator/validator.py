from fastapi import HTTPException


def validate_selected_ids(
    selected_ids: list[int],
    candidates: list[dict],
    requested_count: int,
    difficulty: str,
) -> list[int]:
    """Treat model output as untrusted and require exact candidate membership."""
    candidate_by_id = {int(candidate["question_id"]): candidate for candidate in candidates}
    if len(selected_ids) != len(set(selected_ids)):
        raise HTTPException(status_code=502, detail="AI returned duplicate question IDs.")
    if len(selected_ids) != requested_count:
        raise HTTPException(
            status_code=502,
            detail="AI returned an unexpected number of question IDs.",
        )
    if any(question_id not in candidate_by_id for question_id in selected_ids):
        raise HTTPException(
            status_code=502,
            detail="AI selected a question outside the eligible candidate pool.",
        )
    if any(
        candidate_by_id[question_id]["difficulty"] != difficulty
        for question_id in selected_ids
    ):
        raise HTTPException(
            status_code=502,
            detail="AI selected a question with an unexpected difficulty.",
        )
    return selected_ids
