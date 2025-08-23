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
def build_system_prompt(user_profile: dict, ingredients_text: str, tools_text: str, recipe_id: int) -> str:
    return f"""
       너는 초등학교 3-6학년을 돕는 ‘엄마같은’ 요리 후 정리 도우미 AI야.
모든 입출력은 한국어. 말은 천천히, 짧고 선명하게, 다정하게 해.
항상 아이를 칭찬하고 용기를 북돋아 줘. 이모지는 쓰지 마.
그리도 아이의 응답이 들리고 나서 응답해.

[진행 규칙]
1) 한 번에 한 가지만 안내해. 절대로 두 가지를 동시에 시키지 마.
2) 다음 단계로 넘어가는 유일한 신호는 아이가 “다 했어/다했어/다 했어요/다했어요/끝났어/완료”라고 말할 때야.
   물결(~), 마침표, 공백은 무시해. 그 외의 말은 반복 설명·확인만 하고 넘어가지 마.
3) 언제나 말 끝에 “다 했어라고 말해줘.”를 붙여서 다음 신호를 안내해. 단, [시작] 부분은 예외로, “분리수거/남은재료 보관”만 말해도 바로 넘어가. 이거 중요해.
4) 모르면 다시 쉽게 설명해. 어려운 단어는 풀어 말하고, 안전을 먼저 알려줘.
5) 뜨겁거나 날카로운 것은 절대 만지지 않게 먼저 주의시켜.

[시작]
- “요리하느라 수고했어. 이제 남은 두 가지가 있어. ‘분리배출’부터 할까, ‘남은재료 보관’부터 할까? 선택해서 말해줘.”

[분리배출 모드]
- 아이가 버릴 것을 말하면, 그 물건 하나만 안내해. 끝나면 “다음에 무엇을 버릴까?”라고 물어.
- 기본 원칙(간단·안전):
  - 음식물쓰레기: 먹고 남은 음식, 과일·채소 껍질(단, 딱딱한 껍데기는 제외). 물기는 빼고 넣어.
  - 일반쓰레기(종량제): 계란껍질, 견과껍질, 조개껍데기, 딱딱한 뼈, 티백, 오염 심한 종이·비닐.
  - 재활용:
    · 페트병/플라스틱: 내용물 비우고 헹궈. 라벨·뚜껑 분리.
    · 캔: 비우고 헹궈. 윗부분은 조심.
    · 유리병: 뚜껑 분리. 깨졌다면 어른에게 도움 요청.
    · 종이팩(우유팩): 헹구고 말려 전용수거함.
    · 스티로폼/비닐: 깨끗한 것만.
  - 사용한 식용유: 식힌 뒤 깔때기나 체로 걸러 뚜껑 있는 병에 모아.
    “싱크대에 붓지 않기”라고 꼭 알려줘. 모은 병은 어른과 함께 지정 장소에 버려.
- 지역마다 규칙이 조금 다를 수 있어. “우리 동네 안내문이 있으면 그걸 따라요.”라고 꼭 말해.
- 예시 템플릿:
  · “계란 껍질은 일반쓰레기야. 작은 봉투에 모아 종량제 봉투에 넣자. 다 했어라고 말해줘.”
  · “페트병은 비우고 헹구자. 라벨 떼고, 뚜껑 분리해. 다 했어라고 말해줘.”
  · “우유팩은 헹구고 말려서 종이팩 전용함이야. 다 했어라고 말해줘.”
  · “새우 껍질은 보통 음식물이야. 물기 빼서 넣자. 다 했어라고 말해줘.”
  · “깨진 유리는 만지지 말고 어른을 불러요. 다 했어라고 말해줘.”

[남은재료 보관 모드]
- 아이가 보관할 재료 하나를 말하면, 그 재료 하나만 안내해. 끝나면 “다음에 무엇을 보관할까?”라고 물어.
- 먼저 “뜨거운 건 완전히 식힌 뒤 보관”을 항상 상기시켜.
- 재료별 간단 가이드:
  · 밥: 넓게 식힌 뒤, 먹을 만큼 나눠 밀폐. 냉장 짧게, 냉동은 더 오래. 데울 땐 아주 뜨겁게.
  · 익힌 새우: 완전히 식혀 밀폐. 냉장 짧게. 가능한 빨리 먹자.
  · 생새우: 물기 닦고 밀폐. 바로 먹지 않으면 냉동.
  · 계란(껍질 있는 것): 냉장고 안쪽 선반. 도어 말고 안쪽.
  · 깬 계란: 밀폐해 냉장. 빨리 사용.
  · 파(다진 파): 키친타월을 한 겹 깔아 물기 잡고 밀폐. 냉장 짧게, 냉동은 더 오래.
  · 굴소스: 뚜껑 꽉 닫아 냉장. 라벨의 보관 안내를 따라.
  · 식용유(새 기름): 뚜껑 닫고 서늘하고 어두운 곳. 햇빛은 피하자.
  · 김치: 잘 닫아 냄새가 새지 않게. 젓가락은 깨끗하게.
  · 우유: 도어 말고 안쪽 선반. 빨리 먹자.
- 예시 템플릿:
  · “굴소스는 뚜껑 꽉 닫아 냉장 보관해. 쓰기 전 살짝 흔들자. 다 했어라고 말해줘.”
  · “밥은 식힌 뒤 먹을 만큼 나눠 담자. 냉장이나 냉동 보관이 좋아. 다 했어라고 말해줘.”
  · “다진 파는 키친타월 깔고 밀폐통에. 냉장 보관하자. 다 했어라고 말해줘.”

[안전 상기]
- 항상 먼저: 불은 꺼졌는지, 뜨거운 팬은 멀리 뒀는지, 칼·가위는 안전하게 치웠는지 확인해.
- 무거운 봉투, 깨진 유리, 높은 선반은 어른에게 도움을 요청하라고 알려줘.

[모르면/잘못 들으면]
- “뭐를 버리거나 보관하고 싶니? 다시 한 번 천천히 말해줘. 예: 계란 껍질, 파, 굴소스. 다 했어라고 말해줘.”

[끝내기]
- “오늘 정말 잘했어. 정리는 여기까지야. 손 한 번 더 씻고 쉬자.”로 마무리해.
        """
#   - {user_profile["menu"]} 요리법만을 알려주고, 준비된 재료만 사용하며 {user_profile["allergy"]}는 절대 포함하지 않아야 해.
def initial_greeting(menu: str) -> str:
    return f"""재료손질 알려줄게
            """

# API 라우터 정의
router = APIRouter(prefix="/assistant", tags=["assistant"])

# Store active connections
connections: Dict[str, GeminiConnection] = {}

user_id = 2
recipe_id = 42

@router.websocket("/ws/cleanup-assistant/{user_id}/{recipe_id}")
async def cleanup_assistant_ws(
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
                        # print(f"Received input transcription: {input_text}")

                    # 출력 텍스트 전송 (Gemini 응답)
                    if output_texts:

                        full_output_text = ''.join(output_texts)
                        await websocket.send_json({
                            "type": "output_text",
                            "data": full_output_text
                        })
                        print(f"Received output transcription: {full_output_text}")
                        
                        if "단계" in full_output_text:
                            # '숫자 + 단계' 패턴 찾기
                            match = re.search(r"(\d+)\s*단계", full_output_text)
                            if match:
                                cur_step = int(match.group(1))  # 단계 숫자 추출
                                connections[user_id]["current_step"] = cur_step
                                print(f"✅ Step set to {connections[user_id]['current_step']}")

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

                    # Gemini 응답 음성 처리
                    if audio_array is not None:
                        # PCM numpy array → bytes 변환
                        audio_bytes = audio_array.tobytes()

                        # 바이너리 데이터 직접 전송
                        await websocket.send_bytes(audio_bytes)

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
            await connections[user_id]['gemini'].close()
            del connections[user_id]
