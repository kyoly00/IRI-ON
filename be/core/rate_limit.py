"""Redis 기반 분산 슬라이딩 윈도우(Sliding Window) Rate Limiter.

멀티 컨테이너/분산 환경에서 Brute-force 및 DoS 공격을 차단하며,
Redis 오프라인/테스트 환경에서는 스레드 안전한 인메모리 슬라이딩 윈도우로 동작합니다.
"""

from __future__ import annotations

from collections import defaultdict, deque
import logging
import threading
import time
from uuid import uuid4

from fastapi import HTTPException, Request, status

from .redis_client import get_redis_client

logger = logging.getLogger("iri_on.rate_limit")

_in_memory_windows: dict[str, deque[float]] = defaultdict(deque)
_memory_lock = threading.Lock()


def check_rate_limit(
    key: str,
    max_requests: int,
    window_seconds: int,
) -> tuple[bool, int]:
    """슬라이딩 윈도우 방식으로 요청 한도를 검사합니다.

    Returns:
        (is_allowed: bool, retry_after: int)
    """
    now = time.time()
    window_start = now - window_seconds
    client = get_redis_client()

    if client is not None:
        try:
            pipe = client.pipeline()
            redis_key = f"rate_limit:{key}"
            # 윈도우 이전 데이터 삭제
            pipe.zremrangebyscore(redis_key, 0, window_start)
            # 현재 요청 고유 ID 추가
            pipe.zadd(redis_key, {uuid4().hex: now})
            # 현재 윈도우 요청 수 카운트
            pipe.zcard(redis_key)
            # 만료 시간 갱신
            pipe.expire(redis_key, window_seconds + 1)
            results = pipe.execute()
            current_count = int(results[2])

            if current_count > max_requests:
                return False, window_seconds
            return True, 0
        except Exception as exc:
            logger.warning("[RateLimit] Redis rate limit check failed (%s). Falling back to memory.", exc)

    # In-Memory Fallback
    with _memory_lock:
        queue = _in_memory_windows[key]
        while queue and queue[0] <= window_start:
            queue.popleft()

        if len(queue) >= max_requests:
            oldest = queue[0]
            retry_after = max(1, int(oldest + window_seconds - now))
            return False, retry_after

        queue.append(now)
        return True, 0


def clear_rate_limits_for_test() -> None:
    """테스트 격리를 위해 인메모리 및 Redis rate limit 키를 비웁니다."""
    client = get_redis_client()
    if client is not None:
        try:
            keys = client.keys("rate_limit:*")
            if keys:
                client.delete(*keys)
        except Exception:
            pass
    with _memory_lock:
        _in_memory_windows.clear()


def RateLimiter(requests: int = 5, window: int = 60, key_prefix: str = "default"):
    """FastAPI Depends용 Rate Limiter 의존성 팩토리."""

    async def _rate_limiter_dependency(request: Request) -> None:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            client_ip = forwarded.split(",")[0].strip()
        else:
            client_ip = request.client.host if request.client else "unknown"

        identifier = f"{key_prefix}:{request.url.path}:{client_ip}"
        allowed, retry_after = check_rate_limit(identifier, requests, window)

        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests",
                headers={"Retry-After": str(retry_after)},
            )

    return _rate_limiter_dependency
