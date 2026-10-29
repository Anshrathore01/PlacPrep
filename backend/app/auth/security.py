from passlib.context import CryptContext

# users.password_hash remains a required legacy MySQL column. New Supabase users
# receive an undisclosed random hash; Supabase is the sole password authenticator.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)
