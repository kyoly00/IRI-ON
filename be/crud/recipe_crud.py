from typing import List
from sqlalchemy import func
from sqlalchemy.orm import Session
from models.recipe.recipe import Recipe
from models.recipe.recipe_ingredient import RecipeIngredient
from models.recipe.recipe_tool import RecipeTool
from schemas.ingredient_id_schema import IngredientIDSchema
from schemas.tool_id_schema import ToolIDSchema
from schemas.recipe_schema import RecipeSchema

def get_all_recipes(db: Session) -> List[RecipeSchema]:
    return db.query(
        Recipe.recipe_id,
        Recipe.image_url,
        Recipe.name,
        Recipe.time,
        Recipe.category,
        Recipe.difficulty
    ).all()

def get_recipe_by_id(db: Session, recipe_id: int) -> RecipeSchema:
    return db.query(
        Recipe.recipe_id,
        Recipe.image_url,
        Recipe.name,
        Recipe.time,
        Recipe.category,
        Recipe.difficulty
        ).filter(Recipe.recipe_id == recipe_id).first()

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
