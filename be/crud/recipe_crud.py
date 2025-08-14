from typing import List
from sqlalchemy.orm import Session
from models.recipe.recipe import Recipe
from models.domain.ingredient import Ingredient
from schemas.ingredient_id_schema import IngredientIDSchema

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
    return db.query(
        Recipe.recipe_id,
        Recipe.image_url,
        Recipe.name,
        Recipe.time,
        Recipe.category
    ).filter(Recipe.ingredients.any(Ingredient.id.in_(ingredients))).all()
