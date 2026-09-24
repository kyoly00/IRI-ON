from pydantic import BaseModel, ConfigDict, Field


class UserSignUpSchema(BaseModel):
    """회원가입 입력값을 검증하고 임의 필드 주입을 차단합니다."""
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=8, max_length=20)
