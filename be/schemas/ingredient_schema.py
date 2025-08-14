from pydantic import BaseModel

class IngredientSchema(BaseModel):
    ingredient_id: int
    name: str

    class Config:
        orm_mode = True  # ORM 객체도 자동 변환 가능
