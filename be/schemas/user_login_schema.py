from typing import Optional
from pydantic import BaseModel


class UserLoginSchema(BaseModel):
    """로그인 요청 스키마."""
    id: str
    password: str


class UserLoginResponseSchema(BaseModel):
    """로그인 응답 스키마."""
    user_id: int
    id: str
    name: Optional[str] = "셰프"
    has_profile: bool = False

    class Config:
        orm_mode = True
