from sqlalchemy.orm import Session
from models.recipe import Recipe

def get_all_recipes(db: Session):
    return db.query(
        Recipe.recipe_id,
        Recipe.image_url,
        Recipe.name,
        Recipe.time,
    ).all()

def get_recipe_by_id(db: Session, recipe_id: int):
    return db.query(
        Recipe.recipe_id,
        Recipe.image_url,
        Recipe.name,
        Recipe.time,
        ).filter(Recipe.recipe_id == recipe_id).first()