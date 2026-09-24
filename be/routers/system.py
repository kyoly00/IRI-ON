import os

from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from db.session import engine

router = APIRouter(tags=["system"])


@router.get("/health")
def health():
    """Liveness probe: API 프로세스가 요청을 받을 수 있는지 확인합니다."""
    return {"status": "ok"}


@router.get("/ready")
def ready():
    """Readiness probe: 필수 Secret과 MySQL 연결이 준비됐는지 확인합니다."""
    if not os.getenv("JWT_SECRET") or not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(status_code=503, detail="Required service configuration is unavailable")
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database is unavailable") from exc
    return {"status": "ready"}
