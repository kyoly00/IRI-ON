from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from db.session import get_db
from crud import recipe_crud, user_crud
from schemas.recipe_schema import RecipeSchema

router = APIRouter(prefix="/recipes", tags=["recipes"])

# 전체 레시피 조회
@router.get("/", response_model=List[RecipeSchema])
def get_all_recipes(db: Session = Depends(get_db)):
    recipes = recipe_crud.get_all_recipes(db)
    return recipes

# 특정 레시피 조회
@router.get("/{recipe_id}", response_model=RecipeSchema)
def get_recipe(recipe_id: int, db: Session = Depends(get_db)):
    recipe = recipe_crud.get_recipe_by_id(db, recipe_id)
    return recipe
