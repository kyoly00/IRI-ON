from typing import List
from sqlalchemy.orm import Session
from models.user import User
from models.user.user_ingredient import UserIngredient
from models.user.user_tool import UserTool
from schemas.user_profile_schema import UserProfileSchema
from schemas.user_sign_up_schema import UserSignUpSchema
from schemas.ingredient_id_schema import IngredientIDSchema
from schemas.tool_id_schema import ToolIDSchema

def add_user(db: Session, user: UserSignUpSchema):
    db_user = User(
        id=user.id,
        password=user.password
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

def save_profile(db: Session, user_id: int, user_profile: UserProfileSchema):
    db_user = db.query(User).filter(User.user_id == user_id).first()
    if db_user:
        db_user.name = user_profile.name
        db_user.can_use_fire = user_profile.can_use_fire
        db_user.can_use_knife = user_profile.can_use_knife
        db_user.can_use_peeler = user_profile.can_use_peeler
        db_user.can_use_scissors = user_profile.can_use_scissors
        db_user.allergy = user_profile.allergy
        db.commit()
        db.refresh(db_user)
    return db_user

def get_user_by_id(db: Session, user_id: int) -> UserProfileSchema:
    return db.query(
        User.name,
        User.can_use_fire,
        User.can_use_knife,
        User.can_use_peeler,
        User.can_use_scissors,
        User.allergy,
    ).filter(User.user_id == user_id).first()

def save_ingredients(db: Session, user_id: int, ingredients_ids: List[IngredientIDSchema]):
    # 이미 사용자가 가진 재료 ID 조회
    existing_ids = {
        ing.ingredient_id
        for ing in db.query(UserIngredient.ingredient_id)
                     .filter(UserIngredient.user_id == user_id)
                     .all()
    }

    for ingredient in ingredients_ids:
        if ingredient.ingredient_id in existing_ids:
            continue  # 이미 있으면 추가하지 않음

        db_ingredient = UserIngredient(
            user_id=user_id,
            ingredient_id=ingredient.ingredient_id
        )
        db.add(db_ingredient)
    db.commit()

def get_user_ingredients_ids(db: Session, user_id: int) -> List[IngredientIDSchema]:
    return db.query(UserIngredient.ingredient_id).filter(UserIngredient.user_id == user_id).all()

def save_tools(db: Session, user_id: int, tools_ids: List[ToolIDSchema]):
    # 이미 사용자가 가진 도구 ID 조회
    existing_ids = {
        tool.tool_id
        for tool in db.query(UserTool.tool_id)
                     .filter(UserTool.user_id == user_id)
                     .all()
    }

    for tool in tools_ids:
        if tool.tool_id in existing_ids:
            continue  # 이미 있으면 추가하지 않음

        db_tool = UserTool(
            user_id=user_id,
            tool_id=tool.tool_id
        )
        db.add(db_tool)
    db.commit()

def get_user_tools_ids(db: Session, user_id: int) -> List[ToolIDSchema]:
    return db.query(UserTool.tool_id).filter(UserTool.user_id == user_id).all()
