import os
import json
import base64
import re
from typing import Dict
import asyncio
from concurrent.futures import CancelledError

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.orm import Session

from db.session import get_db
from crud import user_crud, recipe_crud
from services.gemini_connection import GeminiConnection


# ---------- 프롬프트 ----------
def build_system_prompt(user_profile: dict, ingredients_text: str, recipe_id: int) -> str:
    return f"""
        너는 아동을 위한 친절하고 단계별 요리 보조 AI야. 모든 입출력은 한국어로만 해.
        사용자는 칼 사용은 "{user_profile['knife_skill']}", 불 사용은 "{user_profile['stove_skill']}" 수준이고,
        안전을 항상 잘 지키도록 자주 상기시켜야 해.

        사용할 재료: {ingredients_text}
        알레르기: {user_profile['allergy']}

        다음 레시피 단계를 반드시 지켜서 안내해:
            1. 손을 깨끗이 씻습니다.
            2. 조리도구를 식탁 위에 준비합니다.
            3. 밥, 새우, 계란, 파를 식탁 위에 준비합니다.
            4. 굴소스, 소금, 후추를 식탁 위에 준비합니다.
            5. 파를 잘게 썰어 준비합니다.
            6. 가스레인지 불을 켜고 프라이팬을 올립니다.
            7. 프라이팬에 기름을 두릅니다.
            8. 파를 넣고 볶아 향을 냅니다.
            9. 새우를 넣고 색이 변할 때까지 볶습니다.
            10. 계란을 넣고 스크램블합니다.
            11. 밥을 넣고 골고루 섞으며 볶습니다.
            12. 주걱으로 밥을 눌러가며 고슬하게 볶습니다.
            13. 굴소스를 넣고 볶습니다.
            14. 소금을 조금 넣고 볶습니다.
            15. 후추를 두 번 뿌리고 볶습니다.
            16. 가스레인지 불을 끕니다.
            17. 완성된 볶음밥을 그릇에 담아 마무리합니다.

        요리 안내 규칙:
        - {user_profile["menu"]} 요리법만을 알려주고, 준비된 재료만 사용하며 {user_profile["allergy"]}는 절대 포함하지 않아야 해.
        - 부모님이 없는 상황임을 고려해, 어린 아동이 스스로 안전하게 조리할 수 있도록
        각 단계를 아주 쉽고 단순하며 구체적으로, 천천히 설명해줘.
        - 각 단계에서 사용하는 조리기구와 위험 요소에 대해 반드시 안전 주의 문구를 포함해야 해.
        - 한 번에 한 단계씩만 안내하고, 사용자가 반드시 "다 했어"라고 말하기 전까지 다음 단계로 넘어가지 마.
        - 어려워하거나 모른다고 하면 더 쉽게 다시 설명해줘.
        - 항상 사용자를 응원하고 격려하는 말을 잊지 마.
        - 모든 답변은 최대 50자 이내로 간결하게 작성해줘.
        """

def initial_greeting(menu: str) -> str:
    return f"안녕, 너는 나의 요리를 도와주는 셰프얌이야. 같이 새우볶음밥을 만드는 걸 도와줘야 해. 우선 1단계 손씻기부터 안내해줘"

# API 라우터 정의
router = APIRouter(prefix="/assistant", tags=["assistant"])

# Store active connections
connections: Dict[str, GeminiConnection] = {}

user_id = 1
recipe_id = 1

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
        "allergy": getattr(profile, "allergy", "") or "없음",
        "menu": getattr(recipe, "name", "요리"),
    }
    ingredients_text = getattr(recipe, "materials", "") or ""
    # 시스템 프롬프트 생성
    system_prompt_text = build_system_prompt(user_profile, ingredients_text, recipe_id)
    
    # --- GeminiConnection 초기화 및 시작 ---
    # Gemini Live API 설정을 위한 딕셔너리 생성
    gemini_config = {
        "system_prompt": system_prompt_text,
        "voice": "Orus",  # 사용할 Gemini 음성 모델 이름 (유효한 모델명인지 확인 필요)
        "google_search": True,  # Google Search 도구 사용 여부
        "allow_interruptions": True  # Gemini가 말하는 중 사용자 개입 허용 여부
    }

    await websocket.accept()

    try:
        # Create new Gemini connection for this client
        gemini = GeminiConnection()
        connections[user_id] = gemini
        
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
                            # noise, 빈 문자열, 기타 잡음 무시
                            def is_meaningful(text: str) -> bool:
                                text = text.strip()
                                noise_strings = {"<noise>", "noise", "…", "...", ".", "", " "}

                                # 사전 단순 필터링
                                if text.lower() in noise_strings:
                                    return False

                                # 너무 짧거나 숫자만 입력 제외
                                if len(text) <= 1:
                                    return False
                                if text.isdigit():
                                    return False

                                # 온점 등 특수문자만 있으면 제외
                                if re.fullmatch(r"[.]{1,}", text):
                                    return False

                                # 한글 자음, 모음 단독만 있는 경우 제외 (초성중성종성만 있으면)
                                if re.fullmatch(r"[ㄱ-ㅎㅏ-ㅣ]+", text):
                                    return False

                                # 한 글자가 반복되는 단순 노이즈(예: ㅋㅋㅋ, ㅎㅎㅎ) 걸러내기
                                if re.fullmatch(r"(.)\1{2,}", text):
                                    return False

                                # 의미 있다고 판단되면 True 반환
                                return True
                            if not is_meaningful(user_text):
                                print(f"Ignoring noise or meaningless input: '{user_text}'")
                            else:
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


        # Gemini 응답 처리
        async def receive_from_gemini():
            try:
                while True:
                    if websocket.client_state.value == 3:  # WebSocket.CLOSED
                        print("WebSocket closed, stopping Gemini receiver")
                        return

                    # GeminiConnection에서 응답 받기 (dict 형태)
                    msg = await gemini.receive()

                    input_texts = msg.get("input_transcriptions", [])
                    output_texts = msg.get("output_transcriptions", [])
                    audio_array = msg.get("audio", None)

                    # 입력 텍스트 전송 (예: 음성 인식 결과)
                    for input_text in input_texts:
                        await websocket.send_json({
                            "type": "input_text",
                            "data": input_text
                        })
                        print(f"Received input transcription: {input_text}")

                    # 출력 텍스트 전송 (Gemini 응답)
                    if output_texts:
                        full_output_text = ''.join(output_texts)
                        await websocket.send_json({
                            "type": "output_text",
                            "data": full_output_text
                        })
                        print(f"Received output transcription: {full_output_text}")

                    # Gemini 응답 음성 처리
                    if audio_array is not None:
                        # PCM numpy array → base64 인코딩 후 전송
                        import base64
                        audio_bytes = audio_array.tobytes()
                        audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")

                        await websocket.send_json({
                            "type": "audio",
                            "data": audio_base64
                        })

                    # 턴이 끝났다는 신호
                    if msg.get("turn_complete", False):
                        await websocket.send_json({
                            "type": "turn_complete",
                            "data": True
                        })

            except Exception as e:
                print(f"Error receiving from Gemini: {e}")


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
            await connections[user_id].close()
            del connections[user_id]