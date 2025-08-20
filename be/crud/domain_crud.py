from sqlalchemy.orm import Session
from models.domain.ingredient import Ingredient
from models.domain.tool import Tool
from schemas.ingredient_id_schema import IngredientIDSchema
from schemas.tool_id_schema import ToolIDSchema

def get_all_ingredients(db: Session):
    return db.query(
        Ingredient.ingredient_id,
        Ingredient.name
    ).all()

def get_ingredient_id_by_name(db: Session, name: str) -> IngredientIDSchema:
    return db.query(Ingredient.ingredient_id).filter(Ingredient.name == name).first()

def get_all_tools(db: Session):
    return db.query(
        Tool.tool_id,
        Tool.name
    ).all()

def get_tool_id_by_name(db: Session, name: str) -> ToolIDSchema:
    return db.query(Tool.tool_id).filter(Tool.name == name).first()

def get_tool_category_by_id(db: Session, tool_id: int):
    return db.query(Tool.category).filter(Tool.tool_id == tool_id).first()
