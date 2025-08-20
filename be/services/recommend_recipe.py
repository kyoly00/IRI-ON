from typing import List
from sqlalchemy.orm import Session
from crud.recipe_crud import get_recommended_recipes, get_tool_ids_by_recipe
from crud.user_crud import get_user_ingredients_ids, get_user_tools_ids, get_user_by_id
from crud.domain_crud import get_tool_category_by_id
from schemas.recipe_schema import RecipeSchema
from models.recipe.recipe import Difficulty
from models.domain.tool import Category as ToolCategory

def recommend_recipes(db: Session, user_id: int) -> List[RecipeSchema]:
    recommended_recipes = get_recipes_by_user_profile(db, user_id)
    user_tool_skill = get_user_tool_skill(db, user_id)

    # 난이도 나누기
    # 각 레시피에 필요한 도구들의 카테고리 기반으로 모든 도구가 사용자 스킬에서 true면 easy, true와 false가 섞여있으면 medium, 모두 false면 hard
    for recipe in recommended_recipes:
        # 각 도구의 카테고리 확인
        recipe_tool_ids = [tool.tool_id for tool in get_tool_ids_by_recipe(db, recipe.recipe_id)]
        tool_categories = [get_tool_category_by_id(db, tool_id)[0] for tool_id in recipe_tool_ids]

        if all(user_tool_skill[category] for category in tool_categories):
            recipe.difficulty = Difficulty.EASY
        elif any(user_tool_skill[category] for category in tool_categories):
            recipe.difficulty = Difficulty.MEDIUM
        else:
            recipe.difficulty = Difficulty.HARD
    return recommended_recipes

def get_recipes_by_user_profile(db: Session, user_id: int) -> List[RecipeSchema]:
    # 사용자의 재료를 가져옵니다.
    user_ingredients = get_user_ingredients_ids(db, user_id)
    # 사용자의 도구를 가져옵니다.
    user_tools = get_user_tools_ids(db, user_id)
    # 사용자의 재료와 도구를 기반으로 레시피를 검색합니다.
    recommended_recipes = get_recommended_recipes(db, user_ingredients, user_tools)
    return recommended_recipes

def get_user_tool_skill(db: Session, user_id: int):
    # 사용자 도구 스킬
    user_profile = get_user_by_id(db, user_id)
    user_tool_skill = {
        ToolCategory.fire: user_profile.can_use_fire,
        ToolCategory.knife: user_profile.can_use_knife,
        ToolCategory.peeler: user_profile.can_use_peeler,
        ToolCategory.scissors: user_profile.can_use_scissors,
        ToolCategory.other: True
    }
    return user_tool_skill