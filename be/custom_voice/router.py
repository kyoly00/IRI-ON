"""Custom cascade의 REST session-info와 PCM WebSocket 진입점."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional
from uuid import UUID, uuid4

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, WebSocket

from db.session import SessionLocal

from .config import CustomVoiceSettings
from .context import build_session_context
from .providers import ProviderError
from .runtime import CustomVoiceRuntime


# 기존 /assistant/openai-realtime 경로와 충돌하지 않는 독립 namespace를 사용한다.
router = APIRouter(prefix="/custom-voice", tags=["custom-voice"])
load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def _normalize_session_id(value: Optional[str]) -> str:
    """trace correlation ID를 UUID hex로 제한해 로그 파일명 주입을 차단한다."""

    if value is None:
        return uuid4().hex
    try:
        return UUID(value).hex
    except ValueError as exc:
        raise ValueError("session_id must be a UUID") from exc


def _load_context(user_id: int, recipe_id: int) -> dict[str, Any]:
    """HTTP와 WebSocket이 같은 prompt builder를 사용하도록 DB lifecycle을 감싼다."""

    db = SessionLocal()
    try:
        return build_session_context(db, user_id, recipe_id)
    finally:
        db.close()


@router.get("/session-info/{user_id}/{recipe_id}")
async def get_custom_voice_session_info(user_id: int, recipe_id: int) -> dict[str, Any]:
    """연결 전에 화면이 prompt/단계 존재 여부를 검증할 수 있는 정보를 반환한다."""

    try:
        context = _load_context(user_id, recipe_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        **context,
        "architecture": "custom_cascade",
        "protocol": "pcm_s16le_mono_websocket_v1",
    }


@router.websocket("/ws/{user_id}/{recipe_id}")
async def custom_voice_websocket(
    websocket: WebSocket,
    user_id: int,
    recipe_id: int,
    session_id: Optional[str] = None,
) -> None:
    """브라우저 PCM과 custom runtime을 1:1로 연결한다."""

    try:
        context = _load_context(user_id, recipe_id)
        runtime = CustomVoiceRuntime(
            websocket=websocket,
            session_id=_normalize_session_id(session_id),
            user_id=user_id,
            recipe_id=recipe_id,
            system_prompt=context["system_prompt"],
            settings=CustomVoiceSettings.from_env(),
        )
    except (LookupError, ProviderError, ValueError) as exc:
        # handshake 이전 오류도 브라우저가 읽을 수 있는 JSON event로 변환한다.
        await websocket.accept()
        await websocket.send_json({"type": "error", "message": str(exc)})
        await websocket.close(code=1011)
        return
    await runtime.run()
