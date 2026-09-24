from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from core.rate_limit import RateLimiter
import crud.user_crud as user_crud
from db.session import get_db
from models.user.user import User
from schemas.ingredient_id_schema import IngredientIDSchema
from schemas.tool_id_schema import ToolIDSchema
from schemas.user_id_schema import UserIDSchema
from schemas.user_login_schema import (
    RefreshTokenRequestSchema,
    TokenRefreshResponseSchema,
    UserLoginResponseSchema,
    UserLoginSchema,
)
from schemas.user_profile_schema import UserProfileSchema
from schemas.user_sign_up_schema import UserSignUpSchema
from security import (
    bearer,
    create_access_token,
    create_token_pair,
    decode_token,
    get_current_user,
    revoke_token,
)

router = APIRouter(prefix="/users", tags=["users"])


@router.post("/signUp", response_model=UserIDSchema, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserSignUpSchema, db: Session = Depends(get_db)):
    try:
        user = user_crud.add_user(db, payload)
        return UserIDSchema(user_id=user.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post(
    "/login",
    response_model=UserLoginResponseSchema,
    dependencies=[Depends(RateLimiter(requests=5, window=60, key_prefix="auth_login"))],
)
@router.post(
    "/signIn",
    response_model=UserLoginResponseSchema,
    dependencies=[Depends(RateLimiter(requests=5, window=60, key_prefix="auth_login"))],
)
def login_user(payload: UserLoginSchema, db: Session = Depends(get_db)):
    """인증 정보를 확인하고 보호 API에서 사용할 Bearer 토큰을 발급합니다."""
    user = user_crud.authenticate_user(db, payload.id, payload.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    has_profile = bool(user.name and user.name != "셰프") or bool(user.allergy) or user.can_use_fire or user.can_use_knife
    tokens = create_token_pair(user.user_id)
    return UserLoginResponseSchema(
        user_id=user.user_id,
        id=user.id,
        name=user.name or "셰프",
        has_profile=has_profile,
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
    )


@router.post(
    "/refresh",
    response_model=TokenRefreshResponseSchema,
    dependencies=[Depends(RateLimiter(requests=10, window=60, key_prefix="auth_refresh"))],
)
def refresh_token_endpoint(payload: RefreshTokenRequestSchema, db: Session = Depends(get_db)):
    """Refresh Token을 검증하여 새로운 Access Token 및 Refresh Token을 발급합니다."""
    token_data = decode_token(payload.refresh_token, expected_type="refresh")
    try:
        user_id = int(token_data["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token subject") from exc

    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User no longer exists")

    # Token rotation: 기존 refresh token 무효화
    revoke_token(payload.refresh_token)

    tokens = create_token_pair(user.user_id)
    return TokenRefreshResponseSchema(
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        token_type="bearer",
    )


@router.post("/logout")
def logout_user(
    payload: Optional[RefreshTokenRequestSchema] = None,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
    current_user: User = Depends(get_current_user),
):
    """현재 Access Token 및 (제공 시) Refresh Token을 Redis 블랙리스트에 등록합니다."""
    if credentials and credentials.credentials:
        revoke_token(credentials.credentials)
    if payload and payload.refresh_token:
        revoke_token(payload.refresh_token)
    return {"success": True, "message": "Successfully logged out"}


@router.get("/me")
def get_me(current_user: User = Depends(get_current_user)):
    return {"user_id": current_user.user_id, "id": current_user.id, "name": current_user.name or "셰프"}


@router.post("/profile")
def save_profile(payload: UserProfileSchema, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """접근 토큰에서 확인된 현재 사용자 프로필만 수정합니다."""
    user = user_crud.save_profile(db, current_user.user_id, payload)
    return {"success": True, "user_id": user.user_id, "name": user.name}


@router.get("/profile")
def get_profile(current_user: User = Depends(get_current_user)):
    return {"name": current_user.name, "can_use_fire": current_user.can_use_fire,
            "can_use_knife": current_user.can_use_knife, "can_use_peeler": current_user.can_use_peeler,
            "can_use_scissors": current_user.can_use_scissors, "allergy": current_user.allergy or ""}


@router.post("/ingredients", response_model=UserIDSchema)
def save_ingredients(payload: List[IngredientIDSchema], current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user_crud.save_ingredients(db, current_user.user_id, payload)
    return UserIDSchema(user_id=current_user.user_id)


@router.get("/ingredients")
def get_ingredients(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return user_crud.get_user_ingredients_ids(db, current_user.user_id)


@router.post("/tools", response_model=UserIDSchema)
def save_tools(payload: List[ToolIDSchema], current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user_crud.save_tools(db, current_user.user_id, payload)
    return UserIDSchema(user_id=current_user.user_id)


@router.get("/tools")
def get_tools(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return user_crud.get_user_tools_ids(db, current_user.user_id)
