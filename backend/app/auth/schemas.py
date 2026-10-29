from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class UserResponse(BaseModel):
    user_id: int
    email: str
    display_name: Optional[str] = None
    role: str
    is_active: bool
    created_at: Optional[datetime] = None
