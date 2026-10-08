from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class UserLoginSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")
    """로그인 요청 스키마."""
    id: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=8, max_length=20)


class UserLoginResponseSchema(BaseModel):
    """로그인 응답 스키마."""
    model_config = ConfigDict(from_attributes=True)
    user_id: int
    id: str
    name: Optional[str] = "셰프"
    has_profile: bool = False
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"

class RefreshTokenRequestSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")
    refresh_token: str


class TokenRefreshResponseSchema(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
