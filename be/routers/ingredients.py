from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from db.session import get_db
from crud import ingredient_crud
from schemas.ingredient_schema import IngredientSchema

router = APIRouter(prefix="/ingredients", tags=["ingredients"])

# 전체 재료 조회
@router.get("/", response_model=List[IngredientSchema])
def get_all_ingredients(db: Session = Depends(get_db)):
    ingredients = ingredient_crud.get_all_ingredients(db)
    return ingredients
