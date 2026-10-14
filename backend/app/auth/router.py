import os

from fastapi import APIRouter, Depends, HTTPException, status
from google.auth.exceptions import GoogleAuthError
from sqlalchemy.exc import IntegrityError

from app.auth import schemas, security, service
from app.auth.dependencies import get_current_user
from app.database import engine

router = APIRouter(prefix="/auth", tags=["Auth"])


def verify_google_credential(credential: str, nonce: str) -> dict:
    """Verify GIS ID token signature and standard OIDC claims via google-auth."""
    from google.auth.transport.requests import Request
    from google.oauth2 import id_token

    client_id = os.getenv("GOOGLE_CLIENT_ID")
    if not client_id:
        raise HTTPException(status_code=503, detail="Google sign-in is not configured")
    try:
        claims = id_token.verify_oauth2_token(credential, Request(), client_id)
    except (ValueError, GoogleAuthError):
        raise HTTPException(status_code=401, detail="Invalid or expired Google credential") from None
    if claims.get("iss") not in {"accounts.google.com", "https://accounts.google.com"}:
        raise HTTPException(status_code=401, detail="Invalid Google credential issuer")
    if claims.get("nonce") != nonce:
        raise HTTPException(status_code=401, detail="Google sign-in nonce validation failed")
    if not claims.get("email_verified"):
        raise HTTPException(status_code=403, detail="A verified Google email is required")
    if not all(isinstance(claims.get(key), str) and claims[key] for key in ("sub", "email")):
        raise HTTPException(status_code=401, detail="Google account is missing required identity claims")
    return {"sub": claims["sub"], "email": claims["email"].lower(), "name": claims.get("name") or claims["email"].split("@")[0], "picture": claims.get("picture")}


def google_identity_or_error(payload: schemas.GoogleCredentialRequest) -> dict:
    identity = verify_google_credential(payload.credential, payload.nonce)
    with engine.begin() as conn:
        if not service.consume_google_nonce(conn, payload.nonce):
            raise HTTPException(status_code=401, detail="Google sign-in request expired or was already used")
    return identity


@router.get("/google/nonce")
def google_nonce():
    with engine.begin() as conn:
        return {"nonce": service.create_google_nonce(conn)}


def token_for_user(user: dict) -> dict:
    if not user.get("is_active"):
        raise HTTPException(status_code=403, detail="Inactive user")
    return {"access_token": security.create_access_token(data={"sub": str(user["user_id"]), "role": user["role"]})}


@router.post("/google", response_model=schemas.TokenResponse)
def google_login(payload: schemas.GoogleCredentialRequest):
    identity = google_identity_or_error(payload)
    try:
        with engine.begin() as conn:
            user = service.find_user_by_google_id(conn, identity["sub"])
            if user is None:
                existing = service.get_user_by_email(conn, identity["email"])
                if existing:
                    raise HTTPException(status_code=409, detail="An account already uses this email. Sign in with your password, then link Google from the account linking page.")
                user = service.create_google_user(conn, identity)
            return token_for_user(user)
    except IntegrityError:
        raise HTTPException(status_code=409, detail="This Google account or email is already linked to another account") from None


@router.post("/google/link", response_model=schemas.UserResponse)
def link_google(payload: schemas.GoogleCredentialRequest, current_user: dict = Depends(get_current_user)):
    identity = google_identity_or_error(payload)
    if identity["email"] != current_user["email"].lower():
        raise HTTPException(status_code=403, detail="The Google email must match the signed-in account")
    try:
        with engine.begin() as conn:
            owner = service.find_user_by_google_id(conn, identity["sub"])
            if owner and owner["user_id"] != current_user["user_id"]:
                raise HTTPException(status_code=409, detail="This Google account is already linked to another user")
            user = service.attach_google_identity(conn, current_user["user_id"], identity)
            if not user:
                raise HTTPException(status_code=409, detail="A Google account is already linked to this user")
            return user
    except IntegrityError:
        raise HTTPException(status_code=409, detail="This Google account is already linked to another user") from None


@router.post(
    "/register",
    response_model=schemas.UserResponse,
    status_code=201,
    responses={409: {"description": "An account with this email already exists."}},
)
def register(payload: schemas.RegisterRequest):
    with engine.begin() as conn:
        existing = service.get_user_by_email(conn, payload.email)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already registered",
            )

        user = service.create_user(
            conn,
            email=payload.email,
            password=payload.password,
            display_name=payload.display_name,
        )
        return user


@router.post("/login", response_model=schemas.TokenResponse)
def login(payload: schemas.LoginRequest):
    with engine.connect() as conn:
        user = service.authenticate_user(conn, payload.email, payload.password)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if not user.get("is_active"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Inactive user",
            )

        access_token = security.create_access_token(
            data={"sub": str(user["user_id"]), "role": user["role"]}
        )
        return {"access_token": access_token}


@router.get("/me", response_model=schemas.UserResponse)
def read_users_me(current_user: dict = Depends(get_current_user)):
    return current_user
