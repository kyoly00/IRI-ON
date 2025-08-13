import base64
import io
import json
import re
import os
import requests
from dotenv import load_dotenv
import openai

load_dotenv(dotenv_path="./.env")

# ---------- 외부 API 클라이언트 ----------
client = openai.OpenAI(
    base_url="https://guest-api.sktax.chat/v1",
    api_key=os.getenv("OPENAI_API_KEY")
)

NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")
SK_APP_KEY = os.getenv("SK_APP_KEY")

# ---------- 프롬프트 ----------
def build_system_prompt(user_profile: dict, ingredients_text: str) -> str:
    return f"""
너는 아동을 위한 친절하고 단계별로 진행하는 요리 보조 AI야.
사용자는 칼 사용은 "{user_profile['knife_skill']}", 불 사용은 "{user_profile['stove_skill']}" 수준이야.
아직 서툴기 때문에 항상 안전을 자주 상기시켜 줘야 해.

이용할 재료: {ingredients_text}
알레르기: {user_profile['allergy']}

답변할 때 지켜야 할 규칙:
- {user_profile["menu"]} 요리 방법을 알려주는데, 준비된 재료만 사용하며 {user_profile["allergy"]}는 절대 포함하지 않는다.
- 부모님이 없는 상황에서 스스로 요리할 수 있도록, 요리 각 단계를 매우 쉽고 단순하고 구체적으로 설명한다.
- 칼질, 불 사용 방법 등 처음 배우는 아동 기준으로 아주 천천히 알려준다.
- 각 단계에서 사용하는 조리기구에 대한 안전 주의 문구를 포함한다.
- 한 번에 한 단계만 알려주고, 사용자가 "다 했어요"라고 말하기 전까지 다음 단계로 넘어가지 않는다.
- 모른다고 하거나 어렵다고 하면 더 쉽게 다시 설명한다.
- 항상 안심하고 즐겁게 요리할 수 있도록 응원한다.
- 모든 답변은 50자 이내로 생성한다.
"""

def initial_greeting(menu: str) -> str:
    return f"안녕, 나는 너의 요리를 도와주는 셰프얌이야. 같이 {menu}를 만들어보자. 첫번째로 할 일은 재료를 꺼내 준비해보자!"

# ---------- STT / TTS ----------
def stt_clova_from_bytes(wav_bytes: bytes) -> str:
    url = "https://naveropenapi.apigw.ntruss.com/recog/v1/stt?lang=Kor"
    headers = {
        "X-NCP-APIGW-API-KEY-ID": NAVER_CLIENT_ID,
        "X-NCP-APIGW-API-KEY": NAVER_CLIENT_SECRET,
        "Content-Type": "application/octet-stream",
    }
    resp = requests.post(url, data=wav_bytes, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    return data.get("text", "")

def split_text_by_sentence(text: str, max_len: int = 800):
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    chunks, cur = [], ""
    for s in sentences:
        if len(cur) + len(s) + 1 <= max_len:
            cur += s + " "
        else:
            if cur:
                chunks.append(cur.strip())
            cur = s + " "
    if cur:
        chunks.append(cur.strip())
    return chunks

def tts_skt_to_wav_bytes(text: str) -> bytes:
    """긴 문장은 청크로 나눠 순차 재생용 오디오를 이어붙이기보단 개별로 내려보내자.
       여기서는 단일 응답만 생성(필요시 청크 루프)."""
    url = "https://apis.openapi.sk.com/axtts/tts"
    headers = {
        "accept": "audio/wav",
        "content-type": "application/json",
        "appKey": SK_APP_KEY
    }
    payload = {
        "model": "axtts-2-6",
        "voice": "jiyoung",
        "text": text,
        "speed": "0.8",
        "sr": 22050,
        "sformat": "wav"
    }
    r = requests.post(url, json=payload, headers=headers)
    r.raise_for_status()
    if "audio/wav" not in r.headers.get("Content-Type", ""):
        raise RuntimeError(f"TTS 응답 형식 오류: {r.status_code} {r.text}")
    return r.content

# ---------- LLM ----------
def call_llm_ax4(messages):
    resp = client.chat.completions.create(
        model="ax4",
        messages=messages
    )
    return resp.choices[0].message.content

def is_proceed(text: str) -> bool:
    keywords = ["완료", "다 했어", "다했어", "다 했어요"]
    return any(word in text.lower() for word in keywords)

def process_user_input(text: str, messages: list) -> str:
    messages.append({"role": "user", "content": text})
    if is_proceed(text):
        ai_response = call_llm_ax4(messages)
    else:
        # 완료 키워드 없으면 재진술 유도 멘트 생성용 호출 (필요시 별도 처리 가능)
        ai_response = call_llm_ax4(messages)
    messages.append({"role": "assistant", "content": ai_response})
    return ai_response
