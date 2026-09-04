from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from db.session import get_db
import crud.user_crud as user_crud
from schemas.user_profile_schema import UserProfileSchema
from schemas.user_id_schema import UserIDSchema
from schemas.user_sign_up_schema import UserSignUpSchema
from schemas.user_login_schema import UserLoginSchema, UserLoginResponseSchema
from schemas.ingredient_id_schema import IngredientIDSchema
from schemas.tool_id_schema import ToolIDSchema

router = APIRouter(prefix="/users", tags=["users"])

# 회원가입 - 유저 생성
@router.post("/signUp", response_model=UserIDSchema)
def create_user(user: UserSignUpSchema, db: Session = Depends(get_db)):
    """새로운 회원을 가입시킵니다."""
    try:
        new_user = user_crud.add_user(db, user)
        return UserIDSchema(user_id=new_user.user_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

# 로그인 - 유저 인증
@router.post("/login", response_model=UserLoginResponseSchema)
@router.post("/signIn", response_model=UserLoginResponseSchema)
def login_user(login_data: UserLoginSchema, db: Session = Depends(get_db)):
    """아이디(이메일)와 비밀번호로 로그인합니다."""
    user = user_crud.authenticate_user(db, login_data.id, login_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="이메일 또는 비밀번호가 일치하지 않습니다.",
        )
    
    # 프로필 작성 여부 체크 (이름이나 도구/알레르기 설정 여부)
    has_profile = bool(user.name and user.name != "셰프") or bool(user.allergy) or user.can_use_fire or user.can_use_knife
    
    return UserLoginResponseSchema(
        user_id=user.user_id,
        id=user.id,
        name=user.name or "셰프",
        has_profile=has_profile,
    )

# 프로필 생성 / 업데이트
@router.post("/profile")
def create_user_profile(user_id: int, user_profile: UserProfileSchema, db: Session = Depends(get_db)):
    user = user_crud.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="존재하지 않는 유저입니다.")
    updated_user = user_crud.save_profile(db, user_id, user_profile)
    return {
        "success": True,
        "user_id": updated_user.user_id,
        "name": updated_user.name,
    }

# 사용자가 가지고 있는 재료 저장
@router.post("/ingredients", response_model=UserIDSchema)
def save_user_ingredients(user_id: int, ingredients_ids: List[IngredientIDSchema], db: Session = Depends(get_db)):
    user_crud.save_ingredients(db, user_id, ingredients_ids)
    return UserIDSchema(user_id=user_id)

# 사용자가 가지고 있는 재료 조회
@router.get("/ingredients")
@router.get("/{user_id}/ingredients")
def get_user_ingredients(user_id: int, db: Session = Depends(get_db)):
    """사용자가 저장한 재료 ID 목록을 반환합니다."""
    return user_crud.get_user_ingredients_ids(db, user_id)

# 사용자가 가지고 있는 도구 저장
@router.post("/tools", response_model=UserIDSchema)
def save_user_tools(user_id: int, tools_ids: List[ToolIDSchema], db: Session = Depends(get_db)):
    user_crud.save_tools(db, user_id, tools_ids)
    return UserIDSchema(user_id=user_id)

# 사용자가 가지고 있는 도구 조회
@router.get("/tools")
@router.get("/{user_id}/tools")
def get_user_tools(user_id: int, db: Session = Depends(get_db)):
    """사용자가 저장한 도구 ID 목록을 반환합니다."""
    return user_crud.get_user_tools_ids(db, user_id)

# 사용자 프로필 조회 (쿼리 파라미터 & 경로 파라미터 모두 지원)
@router.get("/profile")
@router.get("/{user_id}/profile")
def get_user_profile(user_id: int, db: Session = Depends(get_db)):
    profile = user_crud.get_user_by_id(db, user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "name": profile.name,
        "can_use_fire": profile.can_use_fire,
        "can_use_knife": profile.can_use_knife,
        "can_use_peeler": profile.can_use_peeler,
        "can_use_scissors": profile.can_use_scissors,
        "allergy": profile.allergy or "",
    }
