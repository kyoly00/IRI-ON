from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from db.session import get_db
import crud.user_crud as user_crud
from schemas.user_profile_schema import UserProfileSchema
from schemas.user_id_schema import UserIDSchema
from schemas.user_sign_up_schema import UserSignUpSchema
from schemas.ingredient_id_schema import IngredientIDSchema
from schemas.tool_id_schema import ToolIDSchema

router = APIRouter(prefix="/users", tags=["users"])

# 회원가입 - 유저 생성
@router.post("/signUp", response_model=UserIDSchema)
def create_user(user: UserSignUpSchema, db: Session = Depends(get_db)):
    new_user = user_crud.add_user(db, user)
    return UserIDSchema(user_id=new_user.user_id)

# 프로필 생성
@router.post("/profile")
def create_user_profile(user_id: int, user_profile: UserProfileSchema, db: Session = Depends(get_db)):
    new_user = user_crud.save_profile(db, user_id, user_profile)
    return new_user

# 사용자가 가지고 있는 재료 저장
@router.post("/ingredients", response_model=UserIDSchema)
def save_user_ingredients(user_id: int, ingredients_ids: List[IngredientIDSchema], db: Session = Depends(get_db)):
    user_crud.save_ingredients(db, user_id, ingredients_ids)
    return UserIDSchema(user_id=user_id)

# 사용자가 가지고 있는 도구 저장
@router.post("/tools", response_model=UserIDSchema)
def save_user_tools(user_id: int, tools_ids: List[ToolIDSchema], db: Session = Depends(get_db)):
    user_crud.save_tools(db, user_id, tools_ids)
    return UserIDSchema(user_id=user_id)

# 사용자 프로필 조회
@router.get("/{user_id}/profile")
def get_user_profile(user_id: int, db: Session = Depends(get_db)):
    profile = user_crud.get_user_by_id(db, user_id)
    if not profile:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="User not found")
    return profile
