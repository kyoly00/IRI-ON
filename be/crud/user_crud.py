from sqlalchemy.orm import Session
from models.user import User

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
