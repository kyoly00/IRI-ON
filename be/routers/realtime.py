import os
import json
import base64
import re
from typing import Dict
import asyncio
from concurrent.futures import CancelledError
import re

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.orm import Session

from db.session import get_db
from crud import user_crud, recipe_crud
from services.gemini_connection import GeminiConnection


# ---------- 프롬프트 ----------
# key: (시작 단계, 끝 단계), value: 삽입할 메시지 리스트
warning_messages = {
    (4, 5): [
        "다음 단계에서는 날카로운 가위를 사용하니까 베이지 않게 조심해!"
    ],
    (5, 6): [
        "다음 단계에서는 뜨거운 불을 사용하니까 데이지않게 조심해야해!! 심호흡하고 가볼까? 후! 하!"
    ],
    (6, 7): [
        "다음은 뜨거운 프라이팬에 기름을 둘러야해! 프라이팬도, 기름도 용암처럼 뜨거우니 조심! 또 조심!"
    ],
    (17, 18): [
        "지금 프라이팬은 매우 뜨거우니 손잡이를 세게 잡고 다음 단계를 진행하자!"
    ]
}
warnings_text = "\n".join(
    f"단계 {start}와 {end} 사이에 반드시 다음 메시지를 안내: {', '.join(msgs)}"
    for (start, end), msgs in warning_messages.items()
)

# ---------- 타이머 단계 설정 ----------
timer_steps = {
    8: 70,   # 1분
    12: 130, # 2분
    16: 130  # 2분
}
timer_text = "\n".join(
    f"{step}단계에 반드시 다음 메시지를 안내: {(time-10)//60}분 동안 볶으면 돼. {(time-10)//60}분 뒤에 알려줄게!"
    for step, time in timer_steps.items()
)

def build_system_prompt(user_profile: dict, ingredients_text: str, tools_text: str, recipe_id: int) -> str:
    return f"""
        너는 아동을 위한 친절한 단계별 요리 보조 AI야. 모든 입출력은 한국어로만 해. 존댓말은 쓰지마.
        사용자는 칼 사용은 "{user_profile['knife_skill']}", 불 사용은 "{user_profile['stove_skill']}", 필러(껍질 벗기는 칼) 사용은 "{user_profile['peeler_skill']}", 가위 사용은 "{user_profile['scissors_skill']}" 수준이고,
        안전을 항상 잘 지키도록 자주 상기시켜야 해.

        사용할 재료: {ingredients_text}
        사용할 조리도구: {tools_text}
        알레르기: {user_profile['allergy']}

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

def initial_greeting(menu: str) -> str:
    return f"""안녕, 너는 나의 요리를 도와주는 셰프얌이야. 같이 새우볶음밥을 만드는 걸 도와줘야 해.
            우선 새우볶음밥을 만든다는 걸 알려주고 1단계 손씻기부터 안내해줘.
            """

# API 라우터 정의
router = APIRouter(prefix="/assistant", tags=["assistant"])

# Store active connections
connections: Dict[str, GeminiConnection] = {}

user_id = 2
recipe_id = 42

@router.websocket("/ws/cook-assistant/{user_id}/{recipe_id}")
async def cook_assistant_ws(
    websocket: WebSocket,
    user_id: int,
    recipe_id: int,
    db: Session = Depends(get_db),
):

    # 데이터베이스에서 사용자 프로필 및 레시피 정보 조회
    profile = user_crud.get_user_by_id(db, user_id)
    recipe = recipe_crud.get_recipe_by_id(db, recipe_id)

    # 사용자 프로필 데이터 정리
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
    # 시스템 프롬프트 생성
    system_prompt_text = build_system_prompt(user_profile, ingredients_text, tools_text, recipe_id)
    
    # --- GeminiConnection 초기화 및 시작 ---
    # Gemini Live API 설정을 위한 딕셔너리 생성
    gemini_config = {
        "system_prompt": system_prompt_text,
        "voice": "kore",  # 사용할 Gemini 음성 모델 이름 (유효한 모델명인지 확인 필요)
        "google_search": True,  # Google Search 도구 사용 여부
        "allow_interruptions": True  # Gemini가 말하는 중 사용자 개입 허용 여부
    }

    await websocket.accept()

    try:
        # Create new Gemini connection for this client
        gemini = GeminiConnection()
        connections[user_id] = {
            "gemini": gemini,
            "current_step": 1,  # 처음 시작은 step 1
            "current_audio_id": 0
        }

        # Wait for initial configuration
        config_data = gemini_config

        # Set the configuration
        gemini.set_config(config_data)
        
        # # 웹소켓 메시지 최대 크기 설정 (대용량 오디오/이미지 청크를 위함)
        # websocket._max_size = 4 * 1024 * 1024

        # Initialize Gemini connection
        await gemini.connect()
        print("API 연결 완료")

        # 시작 안내 메시지 전달 (텍스트 메시지)
        await gemini.send_text(initial_greeting(user_profile["menu"]))
        print("시작 안내 메시지 전송 완료")

        async def find_video():
            # DB에서 step 영상 조회
            step_video = recipe_crud.get_step_video(db, recipe_id, connections[user_id]["current_step"])
            if step_video and step_video.url:
                await websocket.send_json({
                    "type": "video",
                    "step": connections[user_id]["current_step"],
                    "data": step_video.url
                })
            else:
                await websocket.send_json({
                    "type": "video",
                    "step": connections[user_id]["current_step"],
                    "data": ""
                })
                print(f"No video found for recipe {recipe_id}, step {connections[user_id]["current_step"]}")

        async def run_timer(time):
            await asyncio.sleep(time)
            await connections[user_id]["gemini"].send_text(
                f"{(time-10)//60}분 타이머가 끝났어. "
                f"타이머가 끝났다고 말해주고, 다 했으면 '다 했어'라고 말하라고 안내해."
            )

        # 클라이언트 메시지 처리
        async def receive_from_client():
            try:
                while True:
                    # 연결 종료 확인
                    if websocket.client_state.value == 3:  # WebSocket.CLOSED
                        print("WebSocket connection closed by client")
                        return

                    message = await websocket.receive()

                    if message["type"] == "websocket.disconnect":
                        print("Received disconnect message")
                        return

                    if "text" not in message:
                        print("Received message without text, ignoring")
                        continue

                    try:
                        message_content = json.loads(message["text"])
                        msg_type = message_content["type"]

                        if msg_type == "audio":
                            await gemini.send_audio(message_content["data"])
                        elif msg_type == "image":
                            await gemini.send_image(message_content["data"])
                        elif msg_type == "text":
                            user_text = message_content["data"].strip()
                            if len(user_text) > 1 and not user_text.isdigit():
                                await gemini.send_text(user_text)
                        elif msg_type == "config":
                            # config 메시지 처리: Gemini 설정 업데이트
                            new_config = message_content.get("data", {})
                            gemini.set_config(new_config)
                            print(f"Received config update: {new_config}")
                        else:
                            print(f"Unknown message type: {msg_type}")

                    except json.JSONDecodeError as e:
                        print(f"JSON decode error: {e}")
                        continue
                    except KeyError as e:
                        print(f"Key error in message: {e}")
                        continue
                    except Exception as e:
                        print(f"Error processing client message: {str(e)}")
                        if "disconnect message" in str(e):
                            return
                        continue

            except Exception as e:
                print(f"Fatal error in receive_from_client: {str(e)}")
                return

        async def receive_from_gemini():
            token_buffer = ""
            while True:
                if websocket.client_state.value == 3:
                    return
                try:
                    msg = await gemini.receive()  # dict 형태, 토큰 단위 스트리밍
                    # input_texts = msg.get("input_transcriptions", [])
                    output_texts = msg.get("output_transcriptions", [])
                    audio_array = msg.get("audio")

                    # # 입력 텍스트 전송
                    # for input_text in input_texts:
                    #     await websocket.send_json({"type": "input_text", "data": input_text})

                    # output_texts 자체가 이번 턴에서 나온 전체 응답이라면
                    full_output = "".join(output_texts).strip()
                    if full_output:
                        await websocket.send_json({"type": "output_text", "data": full_output})

                    # 오디오 전송 시
                    if audio_array is not None:
                        connections[user_id]["current_audio_id"] += 1
                        audio_id = connections[user_id]["current_audio_id"]
                        await websocket.send_json({"type": "audio_start", "id": audio_id})
                        await websocket.send_bytes(audio_array.tobytes())
                        await websocket.send_json({"type": "audio_end", "id": audio_id})

                    # 턴 완료 시
                    if msg.get("turn_complete", False):
                        # 남은 버퍼 전송
                        if token_buffer.strip():
                            await websocket.send_json({"type": "output_text", "data": token_buffer.strip()})
                            token_buffer = ""
                        await websocket.send_json({"type": "turn_complete", "data": True})

                    # 단계 인식 및 동영상 전송
                    full_output_text = "".join(output_texts)  # 모든 토큰 합치기
                    if "단계" in full_output_text:
                            # '숫자 + 단계' 패턴 찾기
                            match = re.search(r"(\d+)\s*단계", full_output_text)
                            if match:
                                cur_step = int(match.group(1))  # 단계 숫자 추출
                                connections[user_id]["current_step"] = cur_step
                                print(f"✅ Step set to {connections[user_id]['current_step']}")
                            asyncio.create_task(find_video())
                            # 타이머 기능
                            if cur_step in timer_steps.keys():
                                asyncio.create_task(run_timer(timer_steps[cur_step]))

                except Exception as e:
                    print(f"Gemini receive error: {e}")
                    await asyncio.sleep(0.05)

        # 두 태스크(concurrent 실행)
        async with asyncio.TaskGroup() as tg:
            tg.create_task(receive_from_client())
            print("음성 입력 받음")
            tg.create_task(receive_from_gemini())
            print("Gemini 응답 받음")

    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        # Cleanup
        if user_id in connections:
            await connections[user_id]['gemini'].close()
            del connections[user_id]
            