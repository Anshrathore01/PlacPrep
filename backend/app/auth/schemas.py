from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, description="Password must be at least 8 characters long")
    display_name: str = Field(..., min_length=1)

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

class UserResponse(BaseModel):
    user_id: int
    email: str
    display_name: Optional[str] = None
    role: str
    is_active: bool
    created_at: Optional[datetime] = None
