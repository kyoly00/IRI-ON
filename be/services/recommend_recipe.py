from typing import List
from sqlalchemy.orm import Session
from crud.recipe_crud import get_recipes_by_ingredients
from crud.user_crud import get_user_ingredients
from schemas.recipe_schema import RecipeSchema

def recommend_recipes(user_id: int, db: Session) -> List[RecipeSchema]:
    # 사용자의 재료를 가져옵니다.
    user_ingredients = get_user_ingredients(db, user_id)
    # 사용자의 재료를 기반으로 레시피를 검색합니다.
    recommended_recipes = get_recipes_by_ingredients(db, user_ingredients)
    return recommended_recipes
