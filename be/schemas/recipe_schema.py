from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class RecipeStepSchema(BaseModel):
    step: int
    text: str = ""
    video_id: Optional[str] = None
    start_url: str = ""
    url: str = ""
    start_seconds: Optional[int] = None
    step_len: Optional[int] = None

class RecipeSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    recipe_id: int
    name: str
    image_url: Optional[str] = None
    time: Optional[int] = None
    category: Optional[str] = None
    difficulty: Optional[str] = None
    video_url: Optional[str] = None
    has_video: bool = False


class RecipeDetailSchema(RecipeSchema):
    description: str = ""
    servings: Optional[int] = None
    materials: str = ""
    tools: str = ""
    tips: str = ""
    instructions: str = ""
    video_id: Optional[str] = None
    timeline_ready: bool = False
    steps: list[RecipeStepSchema] = Field(default_factory=list)


class YouTubeRecipeImportSchema(BaseModel):
    """새 YouTube 링크를 검증·단계화해 레시피로 등록할 때 받는 제어값이다."""

    video_url: str = Field(min_length=11, max_length=512)
    name: Optional[str] = Field(default=None, max_length=100)
    difficulty: Optional[str] = Field(default="초급", max_length=10)
    model: Optional[str] = Field(default=None, max_length=100)
    # 값을 보내지 않으면 환경 변수 정책을 사용한다. 기본 정책은 1단계/0초로 짧은 영상도 허용한다.
    min_duration_seconds: Optional[int] = Field(default=None, ge=0, le=86_400)
    min_steps: Optional[int] = Field(default=None, ge=1, le=60)
    max_steps: Optional[int] = Field(default=None, ge=1, le=60)
