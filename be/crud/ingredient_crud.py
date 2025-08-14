from sqlalchemy.orm import Session
from models.domain.ingredient import Ingredient

def get_all_ingredients(db: Session):
    return db.query(
        Ingredient.ingredient_id,
        Ingredient.name
    ).all()
