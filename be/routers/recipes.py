from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from db.session import get_db
from services.recommend_recipe import recommend_recipes
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

# 추천 레시피 조회
@router.get("/recommendations/{user_id}", response_model=List[RecipeSchema])
def get_recommended_recipes(user_id: int, db: Session = Depends(get_db)):
    recommended_recipes = recommend_recipes(db, user_id=user_id)
    return recommended_recipes

# 레시피 단계 조회
@router.get("/{recipe_id}/steps")
def get_recipe_steps(recipe_id: int, db: Session = Depends(get_db)):
    from crud import recipe_crud
    from models.recipe.recipe_step import RecipeStep
    
    steps = db.query(RecipeStep).filter(RecipeStep.recipe_id == recipe_id).order_by(RecipeStep.step).all()
    return [{"step": step.step, "url": step.url or ""} for step in steps]

# 단계별 비디오 URL 조회
@router.get("/{recipe_id}/steps/{step}/video")
def get_step_video(recipe_id: int, step: int, db: Session = Depends(get_db)):
    from crud import recipe_crud
    step_video = recipe_crud.get_step_video(db, recipe_id, step)
    if not step_video:
        return {"url": ""}
    return {"url": step_video.url or ""}
