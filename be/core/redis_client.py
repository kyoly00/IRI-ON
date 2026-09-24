"""Redis 분산 캐시/저장소 및 토큰 블랙리스트 관리 모듈.

Redis 서버 연결을 지원하며, Redis가 오프라인이거나 테스트 환경일 경우
자동으로 스레드 안전한 인메모리 저장소로 graceful fallback하여 무중단 운영을 보장합니다.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Optional

logger = logging.getLogger("iri_on.redis")

_redis_client = None
_redis_checked = False
_in_memory_blacklist: dict[str, float] = {}
_blacklist_lock = threading.Lock()


def get_redis_client():
    """Redis 클라이언트를 가져오거나 연결 불가 시 None을 반환합니다."""
    global _redis_client, _redis_checked
    if _redis_checked:
        return _redis_client

    _redis_checked = True
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    try:
        import redis
        client = redis.from_url(redis_url, socket_timeout=1.0, socket_connect_timeout=1.0)
        client.ping()
        _redis_client = client
        logger.info("[Redis] Connected to Redis at %s", redis_url)
    except Exception as exc:
        _redis_client = None
        logger.info("[Redis] Redis is not available (%s). Using in-memory fallback.", exc)
    return _redis_client


def blacklist_jti(jti: str, ttl_seconds: int) -> None:
    """토큰의 jti(JWT ID)를 블랙리스트에 등록합니다."""
    if not jti or ttl_seconds <= 0:
        return

    client = get_redis_client()
    if client is not None:
        try:
            client.setex(f"blacklist:{jti}", ttl_seconds, "revoked")
            return
        except Exception as exc:
            logger.warning("[Redis] Failed to set blacklist in Redis (%s). Using fallback.", exc)

    with _blacklist_lock:
        _in_memory_blacklist[jti] = time.time() + ttl_seconds
        # 만료된 항목 정리
        now = time.time()
        expired_keys = [k for k, exp in _in_memory_blacklist.items() if exp <= now]
        for k in expired_keys:
            del _in_memory_blacklist[k]


def is_jti_blacklisted(jti: str) -> bool:
    """토큰의 jti가 블랙리스트에 등록(폐기)되었는지 확인합니다."""
    if not jti:
        return False

    client = get_redis_client()
    if client is not None:
        try:
            return bool(client.exists(f"blacklist:{jti}"))
        except Exception as exc:
            logger.warning("[Redis] Failed to check blacklist in Redis (%s). Using fallback.", exc)

    with _blacklist_lock:
        expiry = _in_memory_blacklist.get(jti)
        if expiry is None:
            return False
        if time.time() > expiry:
            del _in_memory_blacklist[jti]
            return False
        return True


def clear_blacklist_for_test() -> None:
    """테스트 격리를 위해 블랙리스트를 비웁니다."""
    client = get_redis_client()
    if client is not None:
        try:
            keys = client.keys("blacklist:*")
            if keys:
                client.delete(*keys)
        except Exception:
            pass
    with _blacklist_lock:
        _in_memory_blacklist.clear()
