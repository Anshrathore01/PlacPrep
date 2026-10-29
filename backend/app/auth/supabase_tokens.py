import json
import os
import time
import urllib.error
import urllib.request
import uuid

import jwt
from fastapi import HTTPException
from jwt import PyJWKClient
from jwt.exceptions import PyJWTError

from app.environment import load_environment

load_environment()

SUPABASE_URL = (os.getenv("SUPABASE_URL") or "").strip().rstrip("/")
SUPABASE_PUBLISHABLE_KEY = (os.getenv("SUPABASE_PUBLISHABLE_KEY") or "").strip()
JWKS_CLIENT = PyJWKClient(f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json", cache_jwk_set=True, lifespan=600) if SUPABASE_URL else None


def _config() -> tuple[str, str]:
    if not SUPABASE_URL or not SUPABASE_PUBLISHABLE_KEY:
        raise HTTPException(status_code=503, detail="Supabase token verification is not configured in the local backend")
    return SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY


def _read_unverified_claims(token: str) -> dict:
    try:
        return jwt.decode(
            token,
            options={"verify_signature": False, "verify_exp": True, "verify_aud": False, "verify_iss": False},
            algorithms=["HS256", "RS256", "ES256", "EdDSA"],
            leeway=0,
        )
    except (PyJWTError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid or expired Supabase access token") from None


def verify_supabase_access_token(token: str) -> dict:
    """Verify Supabase JWT signatures and standard project claims."""
    project_url, _ = _config()
    issuer = f"{project_url}/auth/v1"
    try:
        header = jwt.get_unverified_header(token)
        algorithm = header.get("alg")
        if algorithm == "HS256":
            # Legacy Supabase shared-secret keys are verified by Auth itself. Never
            # accept the locally decoded claims until /auth/v1/user validates them.
            claims = _read_unverified_claims(token)
            verified_user = get_verified_supabase_user(token, claims)
        elif algorithm in {"RS256", "ES256", "EdDSA"} and JWKS_CLIENT is not None:
            signing_key = JWKS_CLIENT.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=[algorithm],
                audience="authenticated",
                issuer=issuer,
                options={"require": ["exp", "sub", "aud", "iss"]},
            )
            verified_user = None
        else:
            raise HTTPException(status_code=401, detail="Unsupported Supabase token signing algorithm")
    except HTTPException:
        raise
    except (PyJWTError, urllib.error.URLError, TimeoutError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid or expired Supabase access token") from None

    if claims.get("iss") != issuer or claims.get("aud") != "authenticated":
        raise HTTPException(status_code=401, detail="Supabase token issuer or audience is invalid")
    if not isinstance(claims.get("exp"), (int, float)) or claims["exp"] <= time.time():
        raise HTTPException(status_code=401, detail="Supabase access token has expired")
    try:
        claims["sub"] = str(uuid.UUID(str(claims.get("sub"))))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(status_code=401, detail="Supabase token subject is invalid") from None
    if verified_user is not None and verified_user.get("id") != claims["sub"]:
        raise HTTPException(status_code=401, detail="Supabase token identity does not match the verified user")
    return claims


def get_verified_supabase_user(token: str, claims: dict | None = None) -> dict:
    """Ask Supabase Auth to verify shared-secret tokens and return its user record."""
    project_url, publishable_key = _config()
    request = urllib.request.Request(
        f"{project_url}/auth/v1/user",
        headers={"apikey": publishable_key, "Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            user = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code in {401, 403}:
            raise HTTPException(status_code=401, detail="Supabase rejected the access token") from None
        raise HTTPException(status_code=503, detail="Supabase Auth could not validate the local access token") from None
    except (urllib.error.URLError, TimeoutError):
        raise HTTPException(status_code=503, detail="Supabase Auth is unavailable for legacy signing-key validation") from None
    except json.JSONDecodeError:
        raise HTTPException(status_code=401, detail="Supabase rejected the access token") from None
    except Exception:
        raise HTTPException(status_code=503, detail="Unable to verify the Supabase user with the local Auth service") from None
    if not isinstance(user, dict) or not user.get("id"):
        raise HTTPException(status_code=401, detail="Supabase rejected the access token")
    if claims is not None and str(user["id"]) != str(claims.get("sub")):
        raise HTTPException(status_code=401, detail="Supabase token identity does not match the verified user")
    return user
