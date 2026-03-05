import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

import requests
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy.orm import Session

from crud import recipe_crud, user_crud
from db.session import get_db

router = APIRouter(prefix="/assistant", tags=["assistant"])

timer_steps = {1: 20, 2: 100, 8: 30, 12: 120, 16: 30}
connections: Dict[int, Dict[str, Any]] = {}
TOOLS_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "realtime_tools.json"


class RealtimeSessionRequest(BaseModel):
    model: str = "gpt-4o-realtime-preview"
    voice: str = "ash"
    instructions: Optional[str] = None


def load_tools_config() -> Dict[str, Any]:
    if not TOOLS_CONFIG_PATH.exists():
        return {"tools": [], "tool_choice": "auto"}
    try:
        with open(TOOLS_CONFIG_PATH, "r", encoding="utf-8") as config_file:
            return json.load(config_file)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"Invalid tool config: {exc}") from exc


@router.get("/openai-realtime/config")
async def get_realtime_tool_config() -> Dict[str, Any]:
    return load_tools_config()


@router.post("/openai-realtime/session")
async def create_openai_realtime_session(
    payload: RealtimeSessionRequest,
) -> Dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is not configured")

    config = load_tools_config()
    body = {
        "model": payload.model,
        "voice": payload.voice,
        "modalities": ["text", "audio"],
        "instructions": payload.instructions or "",
        "tools": config.get("tools", []),
        "tool_choice": config.get("tool_choice", "auto"),
    }

    response = requests.post(
        "https://api.openai.com/v1/realtime/sessions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=30,
    )

    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=response.text)

    session = response.json()
    if config.get("mcp_tool_endpoints"):
        session["mcp_tool_endpoints"] = config["mcp_tool_endpoints"]
    return session


def build_system_prompt(
    user_profile: dict,
    ingredients_text: str,
    tools_text: str,
    recipe_id: int,
) -> str:
    return f"""
        너는 아동을 위한 친절한 단계별 요리 보조 AI야. 모든 입출력은 한국어로만 해. 존댓말은 쓰지마.
        사용자는 칼 사용은 "{knife_skill}", 불 사용은 "{stove_skill}", 필러(껍질 벗기는 칼) 사용은 "{peeler_skill}", 가위 사용은 "{scissors_skill}" 수준이고,
        안전을 항상 잘 지키도록 자주 상기시켜야 해.

        사용할 재료: {ingredients_text}
        사용할 조리도구: {tools_text}
        알레르기: {allergy}

        ### 핵심 규칙 (반드시 지킬 것)
        1. **한 번에 한 단계씩만 안내하며, 단계 번호를 함께 알려준다.**
        2. **사용자의 지시 없이 절대로 다음 단계로 넘어가지 않는다.**
        3. **사용자가 "다 했어"라고 말하면 다음 단계를 안내하고, 원하는 단계 번호를 말하면 그 단계를 안내한다.**
        4. 각 단계의 내용과 "다 했어" 라고 말하라는 안내를 함께 전달한다.
        
        요리 단계:
            1: "손을 깨끗이 씻으세요.",
            2: "조리도구(주걱, 프라이팬)을 식탁 위에 준비하세요.",
            3: "밥, 새우, 계란, 파를 식탁 위에 준비하세요.",
            4: "굴소스, 소금, 후추를 식탁 위에 준비하세요.",
            5: "파를 잘게 썰어 준비하세요.",
            6: "가스레인지 불을 켜고 프라이팬을 화구 틀에 잘 맞게 올리세요.",
            7: "프라이팬에 기름을 한바퀴 반 두르세요.",
            8: "파를 넣고 색이 노릇해질때까지 볶으세요.",
            9: "새우를 넣으세요.",
            10: "계란을 넣으세요.",
            11: "밥을 넣으세요.",
            12: "주걱을 들지 않은 손은 프라이팬의 손잡이를 단단하게 잡고, 주걱을 든 손으로 골고루 볶으세요.",
            13: "굴소스를 한 숟가락 넣으세요.",
            14: "소금을 두번에서 세번정도 톡톡 뿌리세요.",
            15: "후추를 취향에따라 두번에서 세 번 뿌리세요.",
            16: "마지막으로 골고루 볶으세요.",
            17: "가스레인지 불을 끕니다.",
            18: "완성된 볶음밥을 그릇에 담아 맛있게 드세요."

        요리 안내 규칙:
        - 단계 번호와 무관하게 다음 메시지를 안내해: {warnings_text}
        - 8, 12, 16 단계에 다음 메세지를 안내해: {timer_text}
        - 부모님이 없는 상황임을 고려해, 어린 아동이 스스로 안전하게 조리할 수 있도록 각 단계를 아주 쉽고 단순하며 구체적으로, 천천히 설명해줘.
        - 각 단계에서 사용하는 조리기구와 위험 요소에 대해 반드시 안전 주의 문구를 포함해야 해.
        - 어려워하거나 모른다고 하면 더 쉽게 다시 설명해줘.
        - 항상 사용자를 응원하고 격려하는 말을 잊지 마.
        - 모든 답변은 최대 100자 이내로 간결하게 작성하고 이모티콘은 절대로 쓰지 말고 글자만 출력해.
        """


async def send_session_bootstrap(
    websocket: WebSocket,
    user_profile: dict,
    system_prompt: str,
    ingredients_text: str,
    tools_text: str,
) -> None:
    await websocket.send_json(
        {
            "type": "session_info",
            "data": {
                "system_prompt": system_prompt.strip(),
                "timer_steps": timer_steps,
                "user_profile": user_profile,
                "ingredients": ingredients_text,
                "tools": tools_text,
            },
        }
    )


async def handle_assistant_output(
    *,
    user_id: int,
    chunk: str,
    is_final: bool,
    db: Session,
    recipe_id: int,
) -> None:
    connection = connections.get(user_id)
    if not connection:
        return

    connection["partial_output"] += chunk

    if not is_final:
        return

    full_output = connection["partial_output"].strip()
    connection["partial_output"] = ""

    if not full_output:
        return

    await trigger_aux_tasks(
        user_id=user_id,
        full_output_text=full_output,
        db=db,
        recipe_id=recipe_id,
    )


async def trigger_aux_tasks(
    *,
    user_id: int,
    full_output_text: str,
    db: Session,
    recipe_id: int,
) -> None:
    connection = connections.get(user_id)
    if not connection:
        return

    match = re.search(r"(\d+)\s*단계", full_output_text)
    if not match:
        return

    cur_step = int(match.group(1))
    connection["current_step"] = cur_step

    websocket = connection.get("websocket")
    if websocket:
        await websocket.send_json({"type": "step_detected", "step": cur_step})

    asyncio.create_task(
        handle_video_task(
            user_id=user_id,
            recipe_id=recipe_id,
            cur_step=cur_step,
            db=db,
        )
    )

    if check_for_timer_command(cur_step):
        timer_value = timer_steps[cur_step]
        asyncio.create_task(run_timer_task(user_id=user_id, time=timer_value, cur_step=cur_step))


async def handle_video_task(
    *,
    user_id: int,
    recipe_id: int,
    cur_step: int,
    db: Session,
) -> None:
    try:
        step_video = await asyncio.to_thread(
            recipe_crud.get_step_video, db, recipe_id, cur_step
        )
        video_url = step_video.url if step_video and step_video.url else ""
    except Exception as exc:  # pragma: no cover - logging only
        print(f"❌ Error loading step video: {exc}")
        video_url = ""

    connection = connections.get(user_id)
    websocket = connection.get("websocket") if connection else None
    if not websocket:
        return

    await websocket.send_json(
        {
            "type": "video",
            "step": cur_step,
            "data": video_url,
        }
    )


def check_for_timer_command(step: int) -> bool:
    return step in timer_steps


async def run_timer_task(*, user_id: int, time: int, cur_step: int) -> None:
    connection = connections.get(user_id)
    if not connection:
        return

    websocket: Optional[WebSocket] = connection.get("websocket")
    if not websocket:
        return

    print(f"⏰ [Timer Task] {cur_step}단계 타이머 시작: {time}초")
    try:
        await asyncio.sleep(time)
        await websocket.send_json(
            {
                "type": "timer_complete",
                "step": cur_step,
                "time": time,
                "message": f"{cur_step}단계 {time}초 타이머가 끝났어. 다 했으면 '다 했어'라고 말해줘.",
            }
        )
    except Exception as exc:  # pragma: no cover - logging only
        print(f"❌ Error in run_timer_task: {exc}")


async def cleanup_connection(user_id: int) -> None:
    connection = connections.pop(user_id, None)
    if not connection:
        return

    websocket: Optional[WebSocket] = connection.get("websocket")
    if websocket:
        try:
            await websocket.close()
        except RuntimeError:
            pass


@router.websocket("/ws/cook-assistant/{user_id}/{recipe_id}")
async def cook_assistant_ws(
    websocket: WebSocket,
    user_id: int,
    recipe_id: int,
    db: Session = Depends(get_db),
):
    await websocket.accept()

    profile = user_crud.get_user_by_id(db, user_id)
    recipe = recipe_crud.get_recipe_by_id(db, recipe_id)

    user_profile = {
        "knife_skill": "사용 가능" if getattr(profile, "can_use_knife", False) else "서툼",
        "stove_skill": "사용 가능" if getattr(profile, "can_use_fire", False) else "서툼",
        "scissors_skill": "사용 가능" if getattr(profile, "can_use_scissors", False) else "서툼",
        "peeler_skill": "사용 가능" if getattr(profile, "can_use_peeler", False) else "서툼",
        "allergy": getattr(profile, "allergy", "") or "없음",
        "menu": getattr(recipe, "name", "요리"),
    }

    ingredients_text = getattr(recipe, "materials", "") or ""
    tools_text = getattr(recipe, "tools", "") or ""
    system_prompt_text = build_system_prompt(
        user_profile,
        ingredients_text,
        tools_text,
        recipe_id,
    )

    connections[user_id] = {
        "websocket": websocket,
        "current_step": 1,
        "partial_output": "",
    }

    await send_session_bootstrap(
        websocket,
        user_profile,
        system_prompt_text,
        ingredients_text,
        tools_text,
    )

    try:
        while True:
            message = await websocket.receive()

            if message["type"] == "websocket.disconnect":
                raise WebSocketDisconnect

            if "text" not in message:
                continue

            try:
                payload = json.loads(message["text"])
            except json.JSONDecodeError:
                print(f"❌ Invalid JSON payload: {message['text']}")
                continue

            msg_type = payload.get("type")

            if msg_type == "assistant_output":
                chunk = payload.get("data", "")
                is_final = payload.get("is_final", False)
                await handle_assistant_output(
                    user_id=user_id,
                    chunk=chunk,
                    is_final=is_final,
                    db=db,
                    recipe_id=recipe_id,
                )
            elif msg_type == "client_event":
                await websocket.send_json(
                    {
                        "type": "ack",
                        "data": payload.get("event", "unknown"),
                    }
                )
            else:
                print(f"⚠️ Unknown message type: {msg_type}")

    except WebSocketDisconnect:
        print("WebSocket disconnected by client")
    except Exception as exc:
        print(f"WebSocket error: {exc}")
    finally:
        await cleanup_connection(user_id)

