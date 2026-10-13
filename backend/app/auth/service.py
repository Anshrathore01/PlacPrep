from sqlalchemy import text
from app.auth.security import get_password_hash, verify_password, create_access_token

def get_user_by_email(conn, email: str) -> dict:
    row = conn.execute(
        text("SELECT * FROM users WHERE email = :email"),
        {"email": email.lower()}
    ).mappings().first()
    return dict(row) if row else None

def get_user_by_id(conn, user_id: int) -> dict:
    row = conn.execute(
        text("SELECT * FROM users WHERE user_id = :user_id"),
        {"user_id": user_id}
    ).mappings().first()
    return dict(row) if row else None

def create_user(conn, email: str, password: str, display_name: str) -> dict:
    email = email.lower()
    password_hash = get_password_hash(password)
    result = conn.execute(
        text("""
            INSERT INTO users (email, password_hash, display_name, role, is_active)
            VALUES (:email, :password_hash, :display_name, 'STUDENT', 1)
        """),
        {
            "email": email,
            "password_hash": password_hash,
            "display_name": display_name
        }
    )
    user_id = result.lastrowid
    return get_user_by_id(conn, user_id)

def authenticate_user(conn, email: str, password: str) -> dict:
    user = get_user_by_email(conn, email)
    if not user:
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    return user
