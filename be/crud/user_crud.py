import json
from typing import List, Optional
from sqlalchemy.orm import Session
from models.user import User
from models.user.user_ingredient import UserIngredient
from models.user.user_tool import UserTool
from schemas.user_profile_schema import UserProfileSchema
from schemas.user_sign_up_schema import UserSignUpSchema
from schemas.ingredient_id_schema import IngredientIDSchema
from schemas.tool_id_schema import ToolIDSchema
from security import hash_password, password_needs_upgrade, verify_password

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
        password=hash_password(user.password)
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
    if not verify_password(password, user.password):
        return None
    if password_needs_upgrade(user.password):
        user.password = hash_password(password)
        db.commit()
        db.refresh(user)
    return user

def save_profile(db: Session, user_id: int, user_profile: UserProfileSchema):
    db_user = db.query(User).filter(User.user_id == user_id).first()
    if db_user:
        db_user.name = user_profile.name
        db_user.cooking_level = user_profile.cooking_level
        db_user.age_group = (
            None
            if user_profile.age_group == "unspecified"
            else user_profile.age_group
        )
        db_user.supervision_level = user_profile.supervision_level
        db_user.fire_skill = user_profile.fire_skill
        db_user.knife_skill = user_profile.knife_skill
        db_user.peeler_skill = user_profile.peeler_skill
        db_user.scissors_skill = user_profile.scissors_skill
        db_user.can_use_fire = user_profile.fire_skill == "independent"
        db_user.can_use_knife = user_profile.knife_skill == "independent"
        db_user.can_use_peeler = user_profile.peeler_skill == "independent"
        db_user.can_use_scissors = user_profile.scissors_skill == "independent"
        if (
            user_profile.avatar_type == "preset"
            and user_profile.avatar_value in {"baby1", "baby2", "baby3", "baby4"}
        ):
            db_user.avatar_type = "preset"
            db_user.avatar_value = user_profile.avatar_value
        db_user.photo_consent_confirmed = user_profile.photo_consent_confirmed
        db_user.allergy_status = user_profile.allergy_status
        db_user.allergy = json.dumps(user_profile.allergies, ensure_ascii=False)
        db_user.dietary_restrictions = json.dumps(
            user_profile.dietary_restrictions,
            ensure_ascii=False,
        )
        db_user.disliked_ingredients = json.dumps(
            user_profile.disliked_ingredients,
            ensure_ascii=False,
        )
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
    """보유 도구 목록을 현재 선택값으로 교체합니다."""
    requested_ids = {tool.tool_id for tool in tools_ids}
    existing = db.query(UserTool).filter(UserTool.user_id == user_id).all()
    existing_ids = {tool.tool_id for tool in existing}

    for tool in existing:
        if tool.tool_id not in requested_ids:
            db.delete(tool)
    for tool_id in requested_ids - existing_ids:
        db.add(UserTool(user_id=user_id, tool_id=tool_id))
    db.commit()

def get_user_tools_ids(db: Session, user_id: int) -> List[ToolIDSchema]:
    return db.query(UserTool.tool_id).filter(UserTool.user_id == user_id).all()
