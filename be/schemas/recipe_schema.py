from pydantic import BaseModel

class RecipeSchema(BaseModel):
    recipe_id: int
    name: str
    image_url: str
    time: int

    class Config:
        orm_mode = True  # ORM 객체도 자동 변환 가능
