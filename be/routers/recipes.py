from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from db.session import get_db
from crud import recipe_crud
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

# # 특정 레시피를 프로필 기반으로 보조하는 요리 보조 ai 호출
# @router.post("/{recipe_id}/cook-assistant")
# def call_cook_assistant(user_id: int, recipe_id: int, db: Session = Depends(get_db)):
#     # 사용자 프로필 정보
#     profile = db.query(models.user.User).filter(models.user.User.user_id == user_id).first()
#     ai_response = call_ai_service(profile)
#     return ai_response
