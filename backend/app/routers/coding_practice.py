import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from app.auth.dependencies import get_current_user, get_optional_current_user
from app.database import engine

router = APIRouter(prefix="/coding-practice", tags=["coding practice"])
CATALOG = json.loads(Path(__file__).resolve().parents[1].joinpath("service_coding_questions.json").read_text())
PROBLEM_IDS = {problem["id"] for section in CATALOG for problem in section["problems"]}
PRODUCT_QUESTIONS = json.loads(Path(__file__).resolve().parents[1].joinpath("product_dsa_questions.json").read_text())
PRODUCT_PROBLEM_IDS = {problem["id"] for problem in PRODUCT_QUESTIONS}
PROBLEM_IDS.update(PRODUCT_PROBLEM_IDS)
COMPANIES = ["TCS", "Infosys", "HCL Tech", "LTIMindtree"]


class ProgressUpdate(BaseModel):
    is_solved: bool


@router.get("/product")
def get_product_questions(user: dict = Depends(get_current_user)):
    """Return the shared product-company bank with this user's progress overlaid."""
    with engine.connect() as connection:
        completed_ids = set(connection.execute(text("""
            SELECT problem_id FROM coding_practice_progress
            WHERE user_id = :user_id AND is_solved = TRUE
              AND problem_id LIKE 'product-dsa-%'
        """), {"user_id": user["user_id"]}).scalars().all())

    questions = [
        {**question, "is_completed": question["id"] in completed_ids}
        for question in PRODUCT_QUESTIONS
    ]
    completed_count = sum(question["is_completed"] for question in questions)
    return {
        "questions": questions,
        "total": len(questions),
        "completed": completed_count,
        "remaining": len(questions) - completed_count,
    }


@router.get("/catalog")
def get_catalog(user: dict | None = Depends(get_optional_current_user)):
    progress = set()
    if user:
        with engine.connect() as connection:
            progress = set(connection.execute(text("""
                SELECT problem_id FROM coding_practice_progress
                WHERE user_id = :user_id AND is_solved = TRUE
            """), {"user_id": user["user_id"]}).scalars().all())
    return {"service_companies": COMPANIES, "sections": CATALOG,
            "solved_problem_ids": sorted(progress), "authenticated": bool(user)}


@router.put("/progress/{problem_id}")
def update_progress(problem_id: str, body: ProgressUpdate, user: dict = Depends(get_current_user)):
    if problem_id not in PROBLEM_IDS:
        raise HTTPException(status_code=404, detail="Coding practice problem not found.")
    with engine.begin() as connection:
        if body.is_solved:
            connection.execute(text("""
                INSERT INTO coding_practice_progress (user_id, problem_id, is_solved)
                VALUES (:user_id, :problem_id, TRUE)
                ON DUPLICATE KEY UPDATE is_solved = TRUE
            """), {"user_id": user["user_id"], "problem_id": problem_id})
        else:
            connection.execute(text("""
                DELETE FROM coding_practice_progress
                WHERE user_id = :user_id AND problem_id = :problem_id
            """), {"user_id": user["user_id"], "problem_id": problem_id})
    return {"problem_id": problem_id, "is_solved": body.is_solved}
