from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.auth import service
from app.auth.supabase_tokens import get_verified_supabase_user, verify_supabase_access_token
from app.database import engine

security = HTTPBearer()
optional_security = HTTPBearer(auto_error=False)


def _resolve_application_user(token: str) -> dict:
    claims = verify_supabase_access_token(token)
    supabase_id = claims["sub"]
    try:
        with engine.begin() as conn:
            user = service.get_user_by_supabase_id(conn, supabase_id)
            if user is not None:
                if not user.get("is_active"):
                    raise HTTPException(status_code=403, detail="Inactive user")
                return user

            verified_user = get_verified_supabase_user(token, claims)
            user = service.resolve_supabase_user(conn, claims, verified_user)
            if not user.get("is_active"):
                raise HTTPException(status_code=403, detail="Inactive user")
            return user
    except HTTPException:
        raise
    except IntegrityError:
        # A concurrent first request may have established the same unique mapping.
        with engine.connect() as conn:
            user = service.get_user_by_supabase_id(conn, supabase_id)
        if user and user.get("is_active"):
            return user
        raise HTTPException(status_code=409, detail="Unable to link this Supabase account to a PlacPrep user") from None
    except DBAPIError as error:
        original = getattr(error, "orig", None)
        error_code = original.args[0] if getattr(original, "args", None) else None
        if error_code == 1054:
            raise HTTPException(
                status_code=503,
                detail="The local Supabase identity mapping migration has not been applied. Review and apply backend/migrations/013_supabase_identity.sql before signing in.",
            ) from None
        raise


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    return _resolve_application_user(credentials.credentials)


def get_optional_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(optional_security),
) -> dict | None:
    if credentials is None:
        return None
    return get_current_user(credentials)


def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user.get("role") != "ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to perform this action",
        )
    return current_user
