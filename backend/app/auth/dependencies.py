from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
from jwt.exceptions import PyJWTError

from app.database import engine
from app.auth.security import JWT_SECRET, JWT_ALGORITHM
from app.auth.service import get_user_by_id

security = HTTPBearer()
optional_security = HTTPBearer(auto_error=False)


def _get_user_from_token(token: str) -> dict:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id_str = payload.get("sub")
        if user_id_str is None:
            raise credentials_exception
        user_id = int(user_id_str)
    except (PyJWTError, ValueError):
        raise credentials_exception
        
    with engine.connect() as conn:
        user = get_user_by_id(conn, user_id)
        if user is None:
            raise credentials_exception
        if not user.get("is_active"):
            raise HTTPException(status_code=403, detail="Inactive user")
            
        return user


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    return _get_user_from_token(credentials.credentials)


def get_optional_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(optional_security),
) -> dict | None:
    if credentials is None:
        return None
    return _get_user_from_token(credentials.credentials)


def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user.get("role") != "ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to perform this action"
        )
    return current_user
