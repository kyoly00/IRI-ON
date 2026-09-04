from typing import List, Optional
from sqlalchemy.orm import Session
from models.user import User
from models.user.user_ingredient import UserIngredient
from models.user.user_tool import UserTool
from schemas.user_profile_schema import UserProfileSchema
from schemas.user_sign_up_schema import UserSignUpSchema
from schemas.ingredient_id_schema import IngredientIDSchema
from schemas.tool_id_schema import ToolIDSchema

def get_user_by_login_id(db: Session, login_id: str) -> Optional[User]:
    """로그인 ID(이메일)로 사용자를 조회합니다."""
    return db.query(User).filter(User.id == login_id).first()

def add_user(db: Session, user: UserSignUpSchema) -> User:
    """새로운 사용자를 생성합니다. (중복 방지)"""
    existing = get_user_by_login_id(db, user.id)
    if existing:
        raise ValueError(f"이미 존재하는 아이디입니다: {user.id}")

    db_user = User(
        id=user.id,
        password=user.password
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

def authenticate_user(db: Session, login_id: str, password: str) -> Optional[User]:
    """아이디와 비밀번호로 사용자를 인증합니다."""
    user = get_user_by_login_id(db, login_id)
    if not user:
        return None
    if user.password != password:
        return None
    return user

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

def get_user_by_id(db: Session, user_id: int) -> Optional[User]:
    """user_id로 User 전체 모델 인스턴스를 조회합니다."""
    return db.query(User).filter(User.user_id == user_id).first()

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
