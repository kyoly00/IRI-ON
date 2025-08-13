import base64
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.orm import Session

from db.session import get_db
from crud import user_crud, recipe_crud
from services.cook_assistant_service import (
    build_system_prompt,
    initial_greeting,
    stt_clova_from_bytes,
    tts_skt_to_wav_bytes,
    process_user_input
)

router = APIRouter(prefix="/assistant", tags=["assistant"])

@router.websocket("/ws/cook-assistant/{user_id}/{recipe_id}")
async def cook_assistant_ws(
    websocket: WebSocket,
    user_id: int,
    recipe_id: int,
    db: Session = Depends(get_db),
):
    await websocket.accept()
    websocket._max_size = 4 * 1024 * 1024

    # DB 조회
    profile = user_crud.get_user_by_id(db, user_id)
    recipe = recipe_crud.get_ingredients_by_id(db, recipe_id)
    if not profile or not recipe:
        await websocket.send_json({"type": "error", "message": "invalid user_id or recipe_id"})
        await websocket.close()
        return

    user_profile = {
        "knife_skill": "사용 가능" if getattr(profile, "can_use_knife", False) else "서툼",
        "stove_skill": "사용 가능" if getattr(profile, "can_use_fire", False) else "서툼",
        "allergy": getattr(profile, "allergy", "") or "없음",
        "menu": getattr(recipe, "name", "요리"),
    }
    ingredients_text = getattr(recipe, "materials", "") or ""

    # 대화 컨텍스트 초기화
    system_prompt = build_system_prompt(user_profile, ingredients_text)
    messages = [{"role": "system", "content": system_prompt}]

    # 첫 인사 전송
    greet = initial_greeting(user_profile["menu"])
    messages.append({"role": "assistant", "content": greet})
    try:
        wav_bytes = tts_skt_to_wav_bytes(greet)
        await websocket.send_json({"type": "ai", "text": greet})
        await websocket.send_json({
            "type": "tts",
            "audio_base64": base64.b64encode(wav_bytes).decode("utf-8"),
            "mime": "audio/wav"
        })
    except Exception as e:
        await websocket.send_json({"type": "warn", "message": f"TTS 초기 응답 실패: {e}"})

    audio_buf = bytearray()

    try:
        while True:
            msg = await websocket.receive()

            # 1) 음성 청크 데이터 받기
            if "bytes" in msg and msg["bytes"] is not None:
                audio_buf.extend(msg["bytes"])
                continue

            # 2) 텍스트 메시지 받기
            if "text" in msg and msg["text"] is not None:
                data = json.loads(msg["text"])

                # 3) base64로 인코딩된 음성 청크 받기 (옵션)
                if data.get("type") == "audio_chunk":
                    chunk_b64 = data.get("data", "")
                    if chunk_b64:
                        audio_buf.extend(base64.b64decode(chunk_b64))
                    continue

                # 4) 'end' 신호 받으면 지금까지 받은 음성 처리
                if data.get("type") == "end":
                    if not audio_buf:
                        await websocket.send_json({"type": "warn", "message": "빈 오디오 발화"})
                        continue

                    try:
                        # 음성 → 텍스트
                        text = stt_clova_from_bytes(bytes(audio_buf))
                        audio_buf.clear()
                    except Exception as e:
                        await websocket.send_json({"type": "error", "message": f"STT 실패: {e}"})
                        continue

                    await websocket.send_json({"type": "stt", "text": text})

                    try:
                        # AI 호출
                        ai_text = process_user_input(text, messages)
                        await websocket.send_json({"type": "ai", "text": ai_text})
                    except Exception as e:
                        await websocket.send_json({"type": "error", "message": f"LLM 실패: {e}"})
                        continue

                    try:
                        # TTS 생성 및 전송
                        wav_bytes = tts_skt_to_wav_bytes(ai_text)
                        await websocket.send_json({
                            "type": "tts",
                            "audio_base64": base64.b64encode(wav_bytes).decode("utf-8"),
                            "mime": "audio/wav"
                        })
                    except Exception as e:
                        await websocket.send_json({"type": "warn", "message": f"TTS 실패: {e}"})

                    continue

                # 5) 텍스트 메시지 (음성 아닌 일반 텍스트)
                if data.get("type") == "text":
                    user_text = data.get("data", "")
                    try:
                        ai_text = process_user_input(user_text, messages)
                        await websocket.send_json({"type": "ai", "text": ai_text})
                    except Exception as e:
                        await websocket.send_json({"type": "error", "message": f"LLM 실패: {e}"})
                        continue

                    try:
                        wav_bytes = tts_skt_to_wav_bytes(ai_text)
                        await websocket.send_json({
                            "type": "tts",
                            "audio_base64": base64.b64encode(wav_bytes).decode("utf-8"),
                            "mime": "audio/wav"
                        })
                    except Exception as e:
                        await websocket.send_json({"type": "warn", "message": f"TTS 실패: {e}"})
                    continue

                # 6) 연결 종료 요청
                if data.get("type") == "close":
                    await websocket.close()
                    break

    except WebSocketDisconnect:
        pass
