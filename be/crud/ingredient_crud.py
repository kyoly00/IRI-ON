from sqlalchemy.orm import Session
from models.domain.ingredient import Ingredient

def get_all_ingredients(db: Session):
    return db.query(
        Ingredient.ingredient_id,
        Ingredient.name
    ).all()

def get_ingredient_id_by_name(db: Session, name: str):
    return db.query(Ingredient.ingredient_id).filter(Ingredient.name == name).first()
