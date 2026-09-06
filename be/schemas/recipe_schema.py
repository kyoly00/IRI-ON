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
