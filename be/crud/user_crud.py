from typing import List
from sqlalchemy.orm import Session
from models.user import User
from models.user.user_ingredient import UserIngredient
from schemas.user_profile_schema import UserProfileSchema
from schemas.user_sign_up_schema import UserSignUpSchema
from schemas.ingredient_id_schema import IngredientIDSchema

def save_user(db: Session, user: UserSignUpSchema):
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
        db_user.allergy = user_profile.allergy
        db.commit()
        db.refresh(db_user)
    return db_user

def get_all_users(db: Session):
    return db.query(
        User.user_id,
        User.name,
        User.can_use_fire,
        User.can_use_knife,
        User.allergy,
    ).all()

def get_user_by_id(db: Session, user_id: int):
    return db.query(
        User.user_id,
        User.name,
        User.can_use_fire,
        User.can_use_knife,
        User.allergy,
    ).filter(User.user_id == user_id).first()

def save_ingredients(db: Session, user_id: int, ingredients_ids: List[IngredientIDSchema]):
    for ingredient in ingredients_ids:
        db_ingredient = UserIngredient(
            user_id=user_id,
            ingredient_id=ingredient.ingredient_id
        )
        db.add(db_ingredient)
    db.commit()

