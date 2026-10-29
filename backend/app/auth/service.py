import secrets

from sqlalchemy import text

from app.auth.security import get_password_hash


def get_user_by_id(conn, user_id: int) -> dict | None:
    row = conn.execute(
        text("SELECT * FROM users WHERE user_id = :user_id"),
        {"user_id": user_id},
    ).mappings().first()
    return dict(row) if row else None


def get_user_by_email(conn, email: str) -> dict | None:
    row = conn.execute(
        text("SELECT * FROM users WHERE email = :email"),
        {"email": email.strip().lower()},
    ).mappings().first()
    return dict(row) if row else None


def get_user_by_supabase_id(conn, supabase_user_id: str) -> dict | None:
    row = conn.execute(
        text("SELECT * FROM users WHERE supabase_user_id = :supabase_user_id"),
        {"supabase_user_id": supabase_user_id},
    ).mappings().first()
    return dict(row) if row else None


def resolve_supabase_user(conn, claims: dict, verified_user: dict) -> dict:
    """Map a verified Supabase user to an existing or newly created MySQL user."""
    supabase_user_id = claims["sub"]
    email = str(verified_user.get("email") or "").strip().lower()
    if not email or not verified_user.get("email_confirmed_at"):
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="Confirm your email with Supabase before accessing PlacPrep")
    if str(claims.get("email") or "").strip().lower() != email:
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="Supabase token email does not match the verified account")

    user = get_user_by_email(conn, email)
    if user:
        if user.get("supabase_user_id") not in (None, supabase_user_id):
            from fastapi import HTTPException

            raise HTTPException(status_code=409, detail="This PlacPrep account is linked to a different Supabase identity")
        conn.execute(
            text("UPDATE users SET supabase_user_id = :supabase_user_id WHERE user_id = :user_id AND supabase_user_id IS NULL"),
            {"supabase_user_id": supabase_user_id, "user_id": user["user_id"]},
        )
        mapped_user = get_user_by_id(conn, int(user["user_id"]))
        if mapped_user.get("supabase_user_id") != supabase_user_id:
            from fastapi import HTTPException

            raise HTTPException(status_code=409, detail="This PlacPrep account is linked to a different Supabase identity")
        return mapped_user

    metadata = verified_user.get("user_metadata") or {}
    display_name = (
        metadata.get("display_name")
        or metadata.get("full_name")
        or metadata.get("name")
        or email.split("@", 1)[0]
    )
    result = conn.execute(
        text("""
            INSERT INTO users (email, password_hash, display_name, role, is_active, supabase_user_id)
            VALUES (:email, :password_hash, :display_name, 'STUDENT', 1, :supabase_user_id)
        """),
        {
            "email": email,
            "password_hash": get_password_hash(secrets.token_urlsafe(48)),
            "display_name": str(display_name)[:120],
            "supabase_user_id": supabase_user_id,
        },
    )
    return get_user_by_id(conn, int(result.lastrowid))
