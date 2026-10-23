import os
import logging
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
logger = logging.getLogger(__name__)


def _youtube_video_limit_label() -> str:
    """서비스의 실제 최대 영상 길이를 사용자용 문구로 표시한다."""
    try:
        seconds = int(os.getenv("YOUTUBE_RECIPE_MAX_VIDEO_SECONDS", "900"))
    except ValueError:
        seconds = 900
    seconds = min(7_200, max(1, seconds))
    if seconds % 60 == 0:
        return f"{seconds // 60}분 이내"
    return f"{seconds // 60}분 {seconds % 60}초 이내"


def _youtube_import_error_detail(error: Exception) -> tuple[int, str]:
    """원본 라이브러리 오류를 사용자가 바로 행동할 수 있는 안내로 바꾼다."""
    detail = str(error)
    lowered = detail.lower()
    if detail.startswith("COOKING_VIDEO_REQUIRED:"):
        reason = detail.split(":", 1)[1].strip()
        return 422, f"요리 영상이 아닌 것 같아요. 재료 준비와 조리 과정이 나오는 요리 영상을 넣어 주세요. {reason}"
    if "too long" in lowered or "영상이 너무 깁니다" in detail:
        return 422, f"영상이 너무 길어요. {_youtube_video_limit_label()}의 요리 영상으로 다시 시도해 주세요."
    if "timeout" in lowered or "timed out" in lowered:
        return 504, f"영상 확인 시간이 초과됐어요. {_youtube_video_limit_label()}의 요리 영상으로 다시 시도해 주세요."
    if "subtitle" in lowered or "자막" in detail or "ocr" in lowered:
        return 422, "조리 과정을 확인할 자막을 찾지 못했어요. 자막이 있거나 조리 장면이 선명한 요리 영상을 넣어 주세요."
    return 422, f"영상 레시피를 만들지 못했어요. 공개된 요리 영상인지 확인한 뒤 다시 시도해 주세요. ({detail[:180]})"


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
        logger.warning("youtube_import_failed stage=runtime error_type=%s error=%s", type(error).__name__, str(error)[:300])
        status_code, detail = _youtube_import_error_detail(error)
        raise HTTPException(status_code=status_code, detail=detail) from error
    except Exception as error:
        # OpenAI/httpx timeout 등 외부 호출 실패가 500으로 노출되지 않게 한다.
        logger.exception("youtube_import_failed stage=external error_type=%s", type(error).__name__)
        status_code, detail = _youtube_import_error_detail(error)
        raise HTTPException(status_code=status_code, detail=detail) from error
    return {
        "created": True,
        "message": "영상 자막을 검증하고 단계별 레시피를 만들었어요. 바로 음성 요리를 시작할 수 있어요.",
        "recipe": recipe_crud.get_recipe_detail(db, recipe.recipe_id),
    }


@router.get("/{recipe_id}", response_model=RecipeDetailSchema)
def get_recipe(recipe_id: int, servings: Optional[int] = Query(None, ge=1, le=50), db: Session = Depends(get_db)):
    recipe = recipe_crud.get_recipe_detail(db, recipe_id, servings=servings)
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
