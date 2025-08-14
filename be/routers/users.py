from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from db.session import get_db
import crud.user_crud as user_crud
from schemas.user_profile_schema import UserProfileSchema
from schemas.user_id_schema import UserIDSchema
from schemas.user_sign_up_schema import UserSignUpSchema



router = APIRouter(prefix="/users", tags=["users"])

# 회원가입 - 유저 생성
@router.post("/signUp", response_model=UserIDSchema)
def create_user(user: UserSignUpSchema, db: Session = Depends(get_db)):
    new_user = user_crud.save_user(db, user)
    return UserIDSchema(user_id=new_user.user_id)

# 프로필 생성
@router.post("/profile")
def create_user_profile(user_id: int, user_profile: UserProfileSchema, db: Session = Depends(get_db)):
    new_user = user_crud.save_profile(db, user_id, user_profile)
    return new_user

# 사용자가 가지고 있는 재료 저장
@router.post("/", response_model=UserProfileSchema)
def save_user_ingredients(user_id: int, ingredients_ids: list, db: Session = Depends(get_db)):
    user_crud.save_ingredients(db, user_id, ingredients_ids)
    return user_id
