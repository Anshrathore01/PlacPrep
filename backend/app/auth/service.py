from sqlalchemy import text
import secrets
import hashlib
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

def find_user_by_google_id(conn, google_id: str) -> dict:
    row = conn.execute(text("SELECT * FROM users WHERE google_id = :google_id"), {"google_id": google_id}).mappings().first()
    return dict(row) if row else None

def create_google_user(conn, identity: dict) -> dict:
    # The schema requires password_hash. Store a random, undisclosed password hash
    # so the account has no usable password login until the user explicitly sets one.
    result = conn.execute(text("""
        INSERT INTO users (email, password_hash, display_name, role, is_active, google_id, profile_picture)
        VALUES (:email, :password_hash, :display_name, 'STUDENT', 1, :google_id, :profile_picture)
    """), {
        "email": identity["email"].lower(),
        "password_hash": get_password_hash(secrets.token_urlsafe(48)),
        "display_name": identity["name"][:120],
        "google_id": identity["sub"],
        "profile_picture": identity.get("picture"),
    })
    return get_user_by_id(conn, result.lastrowid)

def attach_google_identity(conn, user_id: int, identity: dict) -> dict:
    conn.execute(text("""
        UPDATE users SET google_id = :google_id, profile_picture = :profile_picture
        WHERE user_id = :user_id AND google_id IS NULL
    """), {"google_id": identity["sub"], "profile_picture": identity.get("picture"), "user_id": user_id})
    return get_user_by_id(conn, user_id)

def create_google_nonce(conn) -> str:
    nonce = secrets.token_urlsafe(32)
    conn.execute(text("DELETE FROM google_auth_nonces WHERE expires_at <= UTC_TIMESTAMP(6)"))
    conn.execute(text("""
        INSERT INTO google_auth_nonces (nonce_hash, expires_at)
        VALUES (:nonce_hash, DATE_ADD(UTC_TIMESTAMP(6), INTERVAL 5 MINUTE))
    """), {"nonce_hash": hashlib.sha256(nonce.encode()).hexdigest()})
    return nonce

def consume_google_nonce(conn, nonce: str) -> bool:
    result = conn.execute(text("""
        DELETE FROM google_auth_nonces
        WHERE nonce_hash = :nonce_hash AND expires_at > UTC_TIMESTAMP(6)
    """), {"nonce_hash": hashlib.sha256(nonce.encode()).hexdigest()})
    return result.rowcount == 1
