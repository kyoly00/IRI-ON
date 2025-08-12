from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from db.session import get_db
import models, schemas

router = APIRouter(prefix="/users", tags=["users"])

# 프로필 생성
@router.post("/profile")
def create_user_profile(user: schemas.UserProfileCreate, db: Session = Depends(get_db)):
    db_user = models.user.User(
        id=user.user_id,
        name=user.name,
        age=user.age,
        can_use_fire=user.can_use_fire,
        can_use_knife=user.can_use_knife,
        allergy=user.allergy
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user
