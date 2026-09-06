from typing import List, Optional
from sqlalchemy import func
from sqlalchemy.orm import Session
from models.recipe.recipe import Recipe
from models.recipe.recipe_ingredient import RecipeIngredient
from models.recipe.recipe_tool import RecipeTool
from models.recipe.recipe_step import RecipeStep
from schemas.ingredient_id_schema import IngredientIDSchema
from schemas.tool_id_schema import ToolIDSchema
from schemas.recipe_schema import RecipeSchema
from services.youtube_recipe_timeline import extract_video_id, parse_recipe_steps


def _enum_value(value):
    return getattr(value, "value", value)


def recipe_summary(recipe: Recipe) -> dict:
    return {
        "recipe_id": recipe.recipe_id,
        "image_url": recipe.image_url,
        "name": recipe.name,
        "time": recipe.time,
        "category": _enum_value(recipe.category),
        "difficulty": _enum_value(recipe.difficulty),
        "video_url": recipe.video_url,
        "has_video": bool(extract_video_id(recipe.video_url)),
    }


def step_dict(step: RecipeStep) -> dict:
    start_url = step.start_url or step.url or ""
    return {
        "step": step.step,
        "text": step.text or "",
        "video_id": step.video_id or extract_video_id(start_url),
        "start_url": start_url,
        "url": start_url,
        "start_seconds": step.start_seconds,
        "step_len": step.step_len,
    }

def get_all_recipes(
    db: Session,
    search: str = "",
    category: str = "전체",
    video_only: bool = False,
) -> List[dict]:
    query = db.query(Recipe)
    if search.strip():
        query = query.filter(Recipe.name.ilike(f"%{search.strip()}%"))
    recipes = query.order_by(Recipe.recipe_id).all()
    result = [recipe_summary(recipe) for recipe in recipes]
    if category and category != "전체":
        result = [recipe for recipe in result if recipe["category"] == category]
    if video_only:
        result = [recipe for recipe in result if recipe["has_video"]]
    return result

def get_recipe_model_by_id(db: Session, recipe_id: int) -> Optional[Recipe]:
    return db.query(Recipe).filter(Recipe.recipe_id == recipe_id).first()


def get_recipe_by_id(db: Session, recipe_id: int) -> Optional[dict]:
    recipe = get_recipe_model_by_id(db, recipe_id)
    return recipe_summary(recipe) if recipe else None


def get_recipe_detail(db: Session, recipe_id: int) -> Optional[dict]:
    recipe = get_recipe_model_by_id(db, recipe_id)
    if not recipe:
        return None
    stored_steps = (
        db.query(RecipeStep)
        .filter(RecipeStep.recipe_id == recipe_id)
        .order_by(RecipeStep.step)
        .all()
    )
    steps = [step_dict(step) for step in stored_steps]
    distinct_videos = {step["video_id"] for step in steps if step["video_id"]}
    timeline_ready = bool(
        steps
        and (
            all(step["step_len"] for step in steps)
            # 기존 새우볶음밥은 단계별로 잘라 둔 독립 영상이므로 그대로 완성 타임라인이다.
            or len(distinct_videos) == len(steps)
        )
    )

    # 타임라인을 아직 생성하지 않은 레시피도 원 CSV 단계를 바로 보여 준다.
    if not steps:
        video_id = extract_video_id(recipe.video_url)
        start_url = f"https://youtu.be/{video_id}?t=0" if video_id else ""
        steps = [
            {
                "step": index,
                "text": text,
                "video_id": video_id,
                "start_url": start_url,
                "url": start_url,
                "start_seconds": 0 if video_id else None,
                "step_len": None,
            }
            for index, text in enumerate(parse_recipe_steps(recipe.instructions), start=1)
        ]

    return {
        **recipe_summary(recipe),
        "description": recipe.description or "",
        "servings": recipe.servings,
        "materials": recipe.materials or "",
        "tools": recipe.tools or "",
        "tips": recipe.tips or "",
        "instructions": recipe.instructions or "",
        "video_id": extract_video_id(recipe.video_url),
        "timeline_ready": timeline_ready,
        "steps": steps,
    }

def get_recipe_by_name(db: Session, name: str) -> RecipeSchema:
    return db.query(Recipe).filter(Recipe.name == name).first()

def get_recommended_recipes(db: Session, ingredients: List[IngredientIDSchema], tools: List[ToolIDSchema]) -> List[RecipeSchema]:
    if not ingredients or not tools:
        return []

    ingredient_ids = [i.ingredient_id for i in ingredients]
    tool_ids = [t.tool_id for t in tools]

    recipes = (
        db.query(Recipe)
        .join(RecipeIngredient, Recipe.recipe_id == RecipeIngredient.recipe_id)
        .group_by(Recipe.recipe_id)
        .having(
            func.count(RecipeIngredient.ingredient_id) ==
            func.count(func.if_(RecipeIngredient.ingredient_id.in_(ingredient_ids), 1, None))
        )
    )

    recipes = recipes.join(RecipeTool, Recipe.recipe_id == RecipeTool.recipe_id).group_by(Recipe.recipe_id).having(
        func.count(RecipeTool.tool_id) ==
        func.count(func.if_(RecipeTool.tool_id.in_(tool_ids), 1, None))
    )

    return recipes.all()

def get_tool_ids_by_recipe(db: Session, recipe_id: int) -> List[ToolIDSchema]:
    return db.query(RecipeTool.tool_id).filter(RecipeTool.recipe_id == recipe_id).all()

def get_step_video(db: Session, recipe_id: int, step: int):
    return (
        db.query(RecipeStep)
        .filter(RecipeStep.recipe_id == recipe_id, RecipeStep.step == step)
        .first()
    )
