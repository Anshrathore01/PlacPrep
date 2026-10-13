from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import schemas, security, service
from app.auth.dependencies import get_current_user
from app.database import engine

router = APIRouter(prefix="/auth", tags=["Auth"])


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
