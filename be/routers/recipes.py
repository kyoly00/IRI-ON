from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session
from models.user.user import User
from security import get_current_user

from crud import recipe_crud, user_crud
from db.session import get_db
from schemas.recipe_schema import RecipeDetailSchema, RecipeSchema, YouTubeRecipeImportSchema
from services.recommend_recipe import recommend_recipes
from services.youtube_recipe_timeline import (
    YouTubeRecipeDuplicateError,
    import_youtube_recipe,
    process_recipe_timeline,
    resolve_timeline_policy,
)

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
@router.get("/recommendations", response_model=List[RecipeSchema])
def get_recommended_recipes(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """접근 토큰으로 확인된 현재 사용자의 맞춤 레시피만 반환합니다."""
    recipes = recommend_recipes(db, user_id=current_user.user_id)
    return [recipe_crud.recipe_summary(recipe) for recipe in recipes]


@router.post("/import-youtube", status_code=status.HTTP_201_CREATED)
def import_recipe_from_youtube(
    payload: YouTubeRecipeImportSchema,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """새 YouTube 링크를 먼저 검증·단계화하고 성공한 경우에만 DB 레시피로 등록한다."""

    try:
        policy = resolve_timeline_policy(
            min_duration_seconds=payload.min_duration_seconds,
            min_steps=payload.min_steps,
            max_steps=payload.max_steps,
        )
        recipe = import_youtube_recipe(
            db,
            video_url=payload.video_url,
            requested_name=payload.name,
            difficulty=payload.difficulty,
            model=payload.model,
            policy=policy,
        )
    except YouTubeRecipeDuplicateError as duplicate:
        # 중복은 오류가 아니라 이미 준비된 레시피로 안내할 수 있는 정상 결과다.
        response.status_code = status.HTTP_200_OK
        existing = recipe_crud.get_recipe_detail(db, duplicate.recipe_id)
        return {
            "created": False,
            "message": f"이미 등록된 영상이에요. '{duplicate.recipe_name}' 레시피로 안내할게요.",
            "recipe": existing,
        }
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {
        "created": True,
        "message": "영상 자막을 검증하고 단계별 레시피를 만들었어요. 바로 음성 요리를 시작할 수 있어요.",
        "recipe": recipe_crud.get_recipe_detail(db, recipe.recipe_id),
    }


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
    min_duration_seconds: Optional[int] = Query(None, ge=0, le=86_400),
    min_steps: Optional[int] = Query(None, ge=1, le=60),
    max_steps: Optional[int] = Query(None, ge=1, le=60),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    recipe = recipe_crud.get_recipe_model_by_id(db, recipe_id)
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")
    try:
        policy = resolve_timeline_policy(
            min_duration_seconds=min_duration_seconds,
            min_steps=min_steps,
            max_steps=max_steps,
        )
        steps = process_recipe_timeline(db, recipe, model=model, policy=policy)
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
