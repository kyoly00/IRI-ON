"""보호된 API에서 사용하는 인증·인가 도우미입니다."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import secrets
import time
from typing import Any, Optional
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from core.redis_client import blacklist_jti, is_jti_blacklisted
from db.session import get_db
from models.user.user import User

load_dotenv(Path(__file__).resolve().with_name(".env"))

# bcrypt_sha256 pre-hashes inputs and avoids bcrypt's 72-byte password limit.
# Keep bcrypt for verifying hashes created by the previous implementation.
password_context = CryptContext(schemes=["bcrypt_sha256", "bcrypt"], deprecated="auto")
bearer = HTTPBearer(auto_error=False)
_development_jwt_secret: str | None = None


def hash_password(password: str) -> str:
    """신규 계정의 비밀번호를 bcrypt 해시로 변환합니다."""
    return password_context.hash(password)


def verify_password(password: str, stored_password: str) -> bool:
    """비밀번호를 검증합니다. 운영 환경에서는 평문 비밀번호 허용을 원천 차단합니다."""
    if not stored_password.startswith(("$2", "$bcrypt-sha256$")):
        allow_plaintext = os.getenv("ALLOW_PLAINTEXT_LOGIN", "false").lower() == "true"
        if allow_plaintext:
            return secrets.compare_digest(password, stored_password)
        return False
    return password_context.verify(password, stored_password)


def password_needs_upgrade(stored_password: str) -> bool:
    if not stored_password.startswith(("$2", "$bcrypt-sha256$")):
        return True
    return password_context.needs_update(stored_password)


def _jwt_secret() -> str:
    """JWT 발급·검증 전에 서버 전용 서명 비밀값을 읽고 검증합니다."""
    global _development_jwt_secret
    value = os.getenv("JWT_SECRET", "")
    if len(value) >= 32:
        return value
    if os.getenv("ENVIRONMENT", "development").lower() != "production":
        # Allows local startup without a .env file while keeping production strict.
        if _development_jwt_secret is None:
            _development_jwt_secret = secrets.token_urlsafe(48)
        return _development_jwt_secret
    raise RuntimeError("JWT_SECRET must be configured with at least 32 characters")


def create_access_token(user_id: int, jti: Optional[str] = None) -> str:
    """인증된 DB 사용자 ID를 주체로 하는 짧은 수명(기본 15~30분)의 Access Token을 생성합니다."""
    expire_minutes = int(os.getenv("JWT_ACCESS_EXPIRE_MINUTES", os.getenv("JWT_EXPIRE_MINUTES", "15")))
    expires = datetime.now(timezone.utc) + timedelta(minutes=expire_minutes)
    payload = {
        "sub": str(user_id),
        "type": "access",
        "jti": jti or uuid4().hex,
        "exp": expires,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256")


def create_refresh_token(user_id: int, jti: Optional[str] = None) -> str:
    """토큰 갱신 전용 긴 수명(기본 7~14일)의 Refresh Token을 생성합니다."""
    expire_days = int(os.getenv("JWT_REFRESH_EXPIRE_DAYS", "7"))
    expires = datetime.now(timezone.utc) + timedelta(days=expire_days)
    payload = {
        "sub": str(user_id),
        "type": "refresh",
        "jti": jti or uuid4().hex,
        "exp": expires,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256")


def create_token_pair(user_id: int) -> dict[str, Any]:
    """Access Token과 Refresh Token 쌍을 동시에 생성합니다."""
    access_token = create_access_token(user_id)
    refresh_token = create_refresh_token(user_id)
    access_minutes = int(os.getenv("JWT_ACCESS_EXPIRE_MINUTES", os.getenv("JWT_EXPIRE_MINUTES", "15")))
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": access_minutes * 60,
    }


def decode_token(token: str, expected_type: Optional[str] = None) -> dict[str, Any]:
    """JWT 토큰의 서명, 만료 시간, 토큰 타입 및 블랙리스트 등록 여부를 엄격히 검증합니다."""
    try:
        payload = jwt.decode(token, _jwt_secret(), algorithms=["HS256"])
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    jti = payload.get("jti")
    if jti and is_jti_blacklisted(jti):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_type = payload.get("type", "access")
    if expected_type and token_type != expected_type:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token type: expected {expected_type}, got {token_type}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload


def revoke_token(token: str) -> None:
    """토큰의 남은 만료 시간만큼 Redis 블랙리스트에 등록하여 즉시 무효화합니다."""
    try:
        payload = jwt.decode(token, _jwt_secret(), algorithms=["HS256"], options={"verify_exp": False})
        jti = payload.get("jti")
        exp = payload.get("exp")
        if not jti:
            return
        now = time.time() if exp else 0
        ttl = max(1, int(exp - now)) if exp else 3600
        blacklist_jti(jti, ttl)
    except Exception:
        pass


def verify_ws_token(token: str, expected_user_id: Optional[int] = None) -> int:
    """WebSocket 2단계 인증 시 토큰을 검증하고 user_id를 반환합니다. 실패 시 ValueError를 발생시킵니다."""
    try:
        payload = decode_token(token, expected_type="access")
        user_id = int(payload["sub"])
        if expected_user_id is not None and user_id != expected_user_id:
            raise ValueError(f"User mismatch: expected {expected_user_id}, got {user_id}")
        return user_id
    except HTTPException as exc:
        raise ValueError(exc.detail) from exc
    except Exception as exc:
        raise ValueError(f"Invalid access token: {exc}") from exc


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    """유효한 Bearer 토큰에서 현재 사용자를 확인하는 FastAPI 의존성입니다."""
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication is required")

    payload = decode_token(credentials.credentials, expected_type="access")
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token subject") from exc

    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User no longer exists")
    return user

