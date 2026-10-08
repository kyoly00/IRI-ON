import os
import time
import json
import logging
from pathlib import Path
from uuid import uuid4
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from routers import all_routers

logger = logging.getLogger("iri_on.request")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """배포 시 운영 데이터를 시드하거나 변경하지 않도록 시작 처리를 비워 둡니다."""
    # Migrations and seed data run in explicit deployment jobs, not application startup.
    yield


app = FastAPI(debug=os.getenv("ENVIRONMENT", "development") != "production", lifespan=lifespan)
# 브라우저 인증은 쿠키가 아닌 Authorization Bearer 토큰을 사용합니다.
# 따라서 credential cookie는 허용하지 않고, 쉼표로 구분된 Origin만 접근시킵니다.
origins = [item.strip() for item in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if item.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=False,
                   allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type"])
_requests: dict[str, deque[float]] = defaultdict(deque)

@app.middleware("http")
async def production_security(request: Request, call_next):
    """HTTP 요청에 프로세스 단위 요청 제한, 보안 헤더 및 500 에러 마스킹을 적용합니다."""
    request_id = request.headers.get("X-Request-ID") or uuid4().hex
    request.state.request_id = request_id

    # 헬스체크 및 OPTIONS는 Rate Limiting 제외
    is_exempt = request.method == "OPTIONS" or request.url.path in {"/health", "/ready"}
    if not is_exempt:
        window = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
        maximum = int(os.getenv("RATE_LIMIT_REQUESTS", "120"))
        client = request.client.host if request.client else "unknown"
        now = time.monotonic()
        entries = _requests[client]
        while entries and entries[0] <= now - window:
            entries.popleft()
        if len(entries) >= maximum:
            resp = JSONResponse(
                status_code=429,
                content={"detail": "Too many requests"},
                headers={"Retry-After": str(window)},
            )
            _apply_security_headers(resp, request_id)
            return resp
        entries.append(now)

    started_at = time.monotonic()
    try:
        response = await call_next(request)
    except Exception as exc:
        logger.exception(f"[UnhandledException] request_id={request_id} path={request.url.path} error={exc}")
        response = JSONResponse(
            status_code=500,
            content={"error": "Internal Server Error", "request_id": request_id},
        )

    # 구조화 로그에는 비밀값·본문·토큰을 기록하지 않습니다.
    logger.info(
        json.dumps(
            {
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "latency_ms": round((time.monotonic() - started_at) * 1000, 2),
            },
            ensure_ascii=False,
        )
    )
    _apply_security_headers(response, request_id)
    return response


def _apply_security_headers(response, request_id: str):
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none';"
    if os.getenv("ENVIRONMENT") == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """처리되지 않은 500 오류 시 내부 스택트레이스 유출을 방지하고 요청 ID를 반환합니다."""
    request_id = getattr(request.state, "request_id", None) or request.headers.get("X-Request-ID") or uuid4().hex
    logger.exception(f"[UnhandledException] request_id={request_id} path={request.url.path} error={exc}")
    resp = JSONResponse(
        status_code=500,
        content={"error": "Internal Server Error", "request_id": request_id},
    )
    _apply_security_headers(resp, request_id)
    return resp


for router in all_routers:
    app.include_router(router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
