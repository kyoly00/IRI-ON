import io
import json
import os
from typing import List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.security import HTTPAuthorizationCredentials
from PIL import Image, ImageOps, UnidentifiedImageError
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
from services.avatar_storage import (
    AvatarStorageError,
    delete_avatar,
    signed_avatar_url,
    upload_avatar,
)

router = APIRouter(prefix="/users", tags=["users"])


@router.post(
    "/signUp",
    response_model=UserLoginResponseSchema,
    status_code=status.HTTP_201_CREATED,
)
def create_user(payload: UserSignUpSchema, db: Session = Depends(get_db)):
    try:
        user = user_crud.add_user(db, payload)
        tokens = create_token_pair(user.user_id)
        return UserLoginResponseSchema(
            user_id=user.user_id,
            id=user.id,
            name=user.name or "셰프",
            has_profile=False,
            access_token=tokens["access_token"],
            refresh_token=tokens["refresh_token"],
        )
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
    has_profile = (
        bool(user.name and user.name != "셰프")
        or bool(user.allergy)
        or user.can_use_fire
        or user.can_use_knife
    )
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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token subject",
        ) from exc

    user = db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists",
        )

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
    return {
        "user_id": current_user.user_id,
        "id": current_user.id,
        "name": current_user.name or "셰프",
    }


@router.post("/profile")
def save_profile(
    payload: UserProfileSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """접근 토큰에서 확인된 현재 사용자 프로필만 수정합니다."""
    old_avatar = current_user.avatar_value if current_user.avatar_type == "upload" else None
    user = user_crud.save_profile(db, current_user.user_id, payload)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if old_avatar and user.avatar_type == "preset":
        try:
            delete_avatar(old_avatar)
        except AvatarStorageError:
            pass
    return {"success": True, "user_id": user.user_id, "name": user.name}


@router.get("/profile")
def get_profile(current_user: User = Depends(get_current_user)):
    def parse_list(value: str | None) -> list[str]:
        if not value:
            return []
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except json.JSONDecodeError:
            pass
        return [item.strip() for item in value.split(",") if item.strip()]

    return {
        "name": current_user.name,
        "cooking_level": current_user.cooking_level or 1,
        "age_group": current_user.age_group or "unspecified",
        "supervision_level": current_user.supervision_level or "sometimes_help",
        "fire_skill": current_user.fire_skill
        or ("independent" if current_user.can_use_fire else "with_help"),
        "knife_skill": current_user.knife_skill
        or ("independent" if current_user.can_use_knife else "with_help"),
        "peeler_skill": current_user.peeler_skill
        or ("independent" if current_user.can_use_peeler else "with_help"),
        "scissors_skill": current_user.scissors_skill
        or ("independent" if current_user.can_use_scissors else "with_help"),
        "can_use_fire": bool(current_user.can_use_fire),
        "can_use_knife": bool(current_user.can_use_knife),
        "can_use_peeler": bool(current_user.can_use_peeler),
        "can_use_scissors": bool(current_user.can_use_scissors),
        "avatar_type": current_user.avatar_type or "preset",
        "avatar_value": current_user.avatar_value or "baby1",
        "avatar_url": (
            signed_avatar_url(current_user.avatar_value)
            if current_user.avatar_type == "upload"
            else None
        ),
        "photo_consent_confirmed": bool(current_user.photo_consent_confirmed),
        "allergy_status": current_user.allergy_status or "unknown",
        "allergies": parse_list(current_user.allergy),
        "dietary_restrictions": parse_list(current_user.dietary_restrictions),
        "disliked_ingredients": parse_list(current_user.disliked_ingredients),
    }


@router.post("/avatar")
async def save_avatar(
    image: UploadFile = File(...),
    consent_confirmed: bool = Form(False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.age_group in {"under_8", "8_13"} and not consent_confirmed:
        raise HTTPException(status_code=400, detail="보호자 확인 후 사진을 등록할 수 있습니다.")

    max_bytes = int(os.getenv("AVATAR_MAX_UPLOAD_BYTES", str(2 * 1024 * 1024)))
    raw = await image.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise HTTPException(status_code=413, detail="프로필 이미지는 2MB 이하만 가능합니다.")
    try:
        source = Image.open(io.BytesIO(raw))
        source.verify()
        source = Image.open(io.BytesIO(raw))
        if source.format not in {"JPEG", "PNG", "WEBP"}:
            raise HTTPException(status_code=415, detail="JPEG, PNG, WebP 이미지만 가능합니다.")
        source = ImageOps.exif_transpose(source).convert("RGB")
        rendered = ImageOps.fit(source, (512, 512), method=Image.Resampling.LANCZOS)
        output = io.BytesIO()
        rendered.save(output, format="WEBP", quality=85, method=6)
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(status_code=415, detail="올바른 이미지 파일이 아닙니다.") from exc

    new_path = f"users/{current_user.user_id}/{uuid4().hex}.webp"
    old_path = current_user.avatar_value if current_user.avatar_type == "upload" else None
    try:
        upload_avatar(new_path, output.getvalue())
    except AvatarStorageError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    current_user.avatar_type = "upload"
    current_user.avatar_value = new_path
    current_user.photo_consent_confirmed = consent_confirmed
    db.commit()
    if old_path:
        try:
            delete_avatar(old_path)
        except AvatarStorageError:
            pass
    return {
        "avatar_type": "upload",
        "avatar_value": new_path,
        "avatar_url": signed_avatar_url(new_path),
    }


@router.post("/ingredients", response_model=UserIDSchema)
def save_ingredients(
    payload: List[IngredientIDSchema],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_crud.save_ingredients(db, current_user.user_id, payload)
    return UserIDSchema(user_id=current_user.user_id)


@router.get("/ingredients")
def get_ingredients(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return user_crud.get_user_ingredients_ids(db, current_user.user_id)


@router.post("/tools", response_model=UserIDSchema)
def save_tools(
    payload: List[ToolIDSchema],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_crud.save_tools(db, current_user.user_id, payload)
    return UserIDSchema(user_id=current_user.user_id)


@router.get("/tools")
def get_tools(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return user_crud.get_user_tools_ids(db, current_user.user_id)
