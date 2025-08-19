from sqlalchemy.orm import Session
from models.domain.ingredient import Ingredient
from models.domain.tool import Tool

def get_all_ingredients(db: Session):
    return db.query(
        Ingredient.ingredient_id,
        Ingredient.name
    ).all()

def get_ingredient_id_by_name(db: Session, name: str):
    return db.query(Ingredient.ingredient_id).filter(Ingredient.name == name).first()

def get_all_tools(db: Session):
    return db.query(
        Tool.tool_id,
        Tool.name
    ).all()

def get_tool_id_by_name(db: Session, name: str):
    return db.query(Tool.tool_id).filter(Tool.name == name).first()
