from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from crud import recipe_crud, user_crud
from db.session import get_db
from schemas.recipe_schema import RecipeDetailSchema, RecipeSchema
from services.recommend_recipe import recommend_recipes
from services.youtube_recipe_timeline import process_recipe_timeline

router = APIRouter(prefix="/recipes", tags=["recipes"])


@router.get("/", response_model=List[RecipeSchema])
def get_all_recipes(
    search: str = "",
    category: str = "전체",
    video_only: bool = Query(False),
    db: Session = Depends(get_db),
):
    return recipe_crud.get_all_recipes(db, search, category, video_only)


# 고정 경로는 /{recipe_id}보다 먼저 선언해야 숫자 변환 422를 피할 수 있다.
@router.get("/recommendations/{user_id}", response_model=List[RecipeSchema])
def get_recommended_recipes(user_id: int, db: Session = Depends(get_db)):
    if not user_crud.get_user_by_id(db, user_id):
        return []
    recipes = recommend_recipes(db, user_id=user_id)
    return [recipe_crud.recipe_summary(recipe) for recipe in recipes]


@router.get("/{recipe_id}", response_model=RecipeDetailSchema)
def get_recipe(recipe_id: int, db: Session = Depends(get_db)):
    recipe = recipe_crud.get_recipe_detail(db, recipe_id)
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")
    return recipe


@router.get("/{recipe_id}/steps")
def get_recipe_steps(recipe_id: int, db: Session = Depends(get_db)):
    recipe = recipe_crud.get_recipe_detail(db, recipe_id)
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")
    return {
        "recipe_id": recipe_id,
        "video_id": recipe["video_id"],
        "video_url": recipe["video_url"],
        "timeline_ready": recipe["timeline_ready"],
        "steps": recipe["steps"],
    }


@router.post("/{recipe_id}/timeline")
def create_recipe_timeline(
    recipe_id: int,
    model: Optional[str] = None,
    db: Session = Depends(get_db),
):
    recipe = recipe_crud.get_recipe_model_by_id(db, recipe_id)
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")
    try:
        steps = process_recipe_timeline(db, recipe, model=model)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {
        "recipe_id": recipe_id,
        "timeline_ready": True,
        "steps": [recipe_crud.step_dict(step) for step in steps],
    }


@router.get("/{recipe_id}/steps/{step}/video")
def get_step_video(recipe_id: int, step: int, db: Session = Depends(get_db)):
    step_video = recipe_crud.get_step_video(db, recipe_id, step)
    if not step_video:
        raise HTTPException(status_code=404, detail="Recipe step not found")
    return recipe_crud.step_dict(step_video)
