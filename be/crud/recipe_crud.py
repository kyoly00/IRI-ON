from typing import List
from sqlalchemy import func
from sqlalchemy.orm import Session
from models.recipe.recipe import Recipe
from models.recipe.recipe_ingredient import RecipeIngredient
from models.recipe.recipe_tool import RecipeTool
from schemas.ingredient_id_schema import IngredientIDSchema
from schemas.tool_id_schema import ToolIDSchema

def get_all_recipes(db: Session):
    return db.query(
        Recipe.recipe_id,
        Recipe.image_url,
        Recipe.name,
        Recipe.time,
        Recipe.category
    ).all()

def get_recipe_by_id(db: Session, recipe_id: int):
    return db.query(
        Recipe.recipe_id,
        Recipe.image_url,
        Recipe.name,
        Recipe.time,
        Recipe.category
        ).filter(Recipe.recipe_id == recipe_id).first()

def get_recipe_id_by_name(db: Session, name: str):
    return db.query(Recipe.recipe_id).filter(Recipe.name == name).first()

def get_recipes_by_ingredients(db: Session, ingredients: List[IngredientIDSchema]):
    if not ingredients:
        return []

    ingredient_ids = [i.ingredient_id for i in ingredients]

    recipes = (
        db.query(Recipe)
        .join(RecipeIngredient, Recipe.recipe_id == RecipeIngredient.recipe_id)
        .group_by(Recipe.recipe_id)
        .having(
            func.count(RecipeIngredient.ingredient_id) ==
            func.count(func.if_(RecipeIngredient.ingredient_id.in_(ingredient_ids), 1, None))
        )
        .all()
    )
    return recipes

def get_recipes_by_tools(db: Session, tools: List[ToolIDSchema]):
    if not tools:
        return []

    tool_ids = [t.tool_id for t in tools]

    recipes = (
        db.query(Recipe)
        .join(RecipeTool, Recipe.recipe_id == RecipeTool.recipe_id)
        .group_by(Recipe.recipe_id)
        .having(
            func.count(RecipeTool.tool_id) ==
            func.count(func.if_(RecipeTool.tool_id.in_(tool_ids), 1, None))
        )
        .all()
    )
    return recipes

# def get_recipes_by_ingredients_and_tools(db: Session, ingredients: List[IngredientIDSchema], tools: List[ToolIDSchema]):
#     if not ingredients and not tools:
#         return []

#     tool_ids = [t.tool_id for t in tools]

#     recipes = (
#         db.query(Recipe)
#         .join(RecipeTool, Recipe.recipe_id == RecipeTool.recipe_id)
#         .group_by(Recipe.recipe_id)
#         .having(
#             func.count(RecipeTool.tool_id) ==
#             func.count(func.if_(RecipeTool.tool_id.in_(tool_ids), 1, None))
#         )
#         .all()
#     )
#     return recipes
