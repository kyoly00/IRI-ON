import openai
import requests
import sounddevice as sd
import soundfile as sf
import os
import io
import re
import torch
import threading
import json
import wave
import math
import numpy as np
from tqdm import tqdm
import time
import queue
import webrtcvad  # VAD 라이브러리 추가
from collections import deque  # 큐 대신 덱(Deque) 사용
from dotenv import load_dotenv


load_dotenv()


# ---- 터미널 실행 경로 설정 ----
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# ---- 환경 변수 입력 ----
# OpenAI API 키 (Whisper STT 용)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# SKT AI API 키 (LLM ax4 용)
SKT_AX_API_KEY = os.getenv("SKT_AX_API_KEY")
SK_APP_KEY = os.getenv("SKT_APP_KEY")


# --- VAD 설정 ---
vad = webrtcvad.Vad(3)  # VAD 모드 설정 (0: 관용적, 1: 보통, 2: 공격적, 3: 가장 공격적)
# 오디오 프레임 설정
SAMPLE_RATE = 16000
CHUNK_DURATION_MS = 30  # 30ms 프레임
CHUNK_SIZE = int(SAMPLE_RATE * CHUNK_DURATION_MS / 1000)


# --- 성능 지표 측정용 전역 변수 ---
metrics = {
    "structure": "(i) STT–LLM–TTS 직렬",
    "ttft_ms": None,
    "turn_latencies_ms": [],
    "task_parallel_latency_s": [],  # 현재 구조에서는 사용 안 함
    "vad_enabled": True,
    "task_parallel": False,
    "expected_ux_score": 3.2,
    "first_response_done": False,
}


def print_metrics_summary():
    print("\n========== Metrics Summary ==========")
    print(f"구조: {metrics['structure']}")
    print(f"VAD 여부: {'있음' if metrics['vad_enabled'] else '없음'}")
    print(f"Task 병렬 처리 여부: {'있음' if metrics['task_parallel'] else '없음'}")
    print(f"예상 UX 만족도(5점): {metrics['expected_ux_score']}")
    if metrics["ttft_ms"] is not None:
        print(f"첫 응답까지의 시간 (TTFT, ms): {metrics['ttft_ms']:.1f}")
    if metrics["turn_latencies_ms"]:
        avg_turn = sum(metrics["turn_latencies_ms"]) / len(metrics["turn_latencies_ms"])
        print(f"대화 중 응답 시간 평균 (턴 전환, ms): {avg_turn:.1f}")
    if metrics["task_parallel_latency_s"]:
        avg_task = sum(metrics["task_parallel_latency_s"]) / len(metrics["task_parallel_latency_s"])
        print(f"Task 병행 시 응답 시간 평균 (s): {avg_task:.2f}")
    else:
        print("Task 병행 시 응답 시간 (s): 0.0 (Task Queue 미사용)")
    print("====================================\n")


# --- 사용자 정보 (필요 시 변경) ---
user_profile = {
    "age": 13,
    "ingredients": ["김치", "소시지", "달걀"],
    "knife_skill": "사용 가능",
    "stove_skill": "서툼",
    "allergy": "갑각류",
    "menu": "김치볶음밥",
}


# OpenAI 클라이언트 초기화 
openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)  # STT 및 LLM(GPT)용 통합 클라이언트


# --- 시스템 프롬프트 ---
initial_prompt = f"""
너는 아동을 위한 친절하고 단계별로 진행하는 요리 보조 AI야.
사용자는 {user_profile["age"]}살이며, 칼 사용은 "{user_profile["knife_skill"]}", 불 사용은 "{user_profile["stove_skill"]}" 수준이야.
아직 서툴기 때문에 항상 안전을 자주 상기시켜 줘야 해.

이용할 재료: {", ".join(user_profile['ingredients'])}
알레르기: {user_profile["allergy"]}

답변할 때 지켜야 할 규칙:
- {user_profile["menu"]} 요리 방법을 알려주는데, 준비된 재료만 사용하며 {user_profile["allergy"]}는 절대 포함하지 않는다.
- 부모님이 없는 상황에서 스스로 요리할 수 있도록, 요리 각 단계를 매우 쉽고 단순하고 구체적으로 설명한다.
- 칼질, 불 사용 방법 등 처음 배우는 아동 기준으로 아주 천천히 알려준다.
- 각 단계에서 사용하는 조리기구에 대한 안전 주의 문구를 포함한다.
- 한 번에 한 단계만 알려주고, 사용자가 "다 했어요"라고 말하기 전까지 다음 단계로 넘어가지 않는다.
- 모른다고 하거나 어렵다고 하면 더 쉽게 다시 설명한다.
- 항상 안심하고 즐겁게 요리할 수 있도록 응원한다.
- 모든 답변은 50자 이내로 생성한다.

이제 이 점을 유의하며, {user_profile["menu"]} 요리를 보조할거야.
처음 응답은 '안녕, 나는 너의 요리를 도와주는 셰프얌이야. 같이 {user_profile["menu"]}를 만들어보자. 첫번째로 할 일은'으로 시작하고, 요리 재료랑 재료 준비하라고 말해줘야 돼.
"""


system_prompt_for_ongoing_chat = f"""
너는 아동을 위한 친절하고 단계별로 진행하는 요리 보조 AI야.
사용자는 {user_profile["age"]}살이며, 칼 사용은 "{user_profile["knife_skill"]}", 불 사용은 "{user_profile["stove_skill"]}" 수준이야.
아직 서툴기 때문에 항상 안전을 자주 상기시켜 줘야 해.

이용할 재료: {", ".join(user_profile['ingredients'])}
알레르기: {user_profile["allergy"]}

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


# --- 대화 기록 (메모리) 초기화 ---
messages = [{"role": "system", "content": initial_prompt}]


# --- 실시간 오디오 처리 관련 전역 변수 ---
turn_queue = queue.Queue()  # 완성된 사용자 발화를 저장하는 큐
stt_queue = queue.Queue()   # Whisper 통신용 큐
stop_tts_event = threading.Event()  # TTS 재생 중단 이벤트
tts_playing = False         # TTS 재생 상태

frame_buffer = bytearray()
speech_buffer = bytearray()
is_recording_active = False

def record_callback(indata, frames, time, status):
    """sounddevice의 실시간 오디오 입력 콜백 함수. 데이터를 버퍼에 누적합니다."""
    if status:
        pass # 짧은 버퍼 오버플로우는 무시
    if is_recording_active:
        frame_buffer.extend(bytes(indata))

def send_to_whisper_api(pcm_chunk):
    """PCM 바이트를 WAV 형태로 메모리에서 변환 후 OpenAI API로 전송"""
    global openai_client
    stt_start_time = time.perf_counter()
    print("⏳ [STT 요청 시작] OpenAI Whisper API로 전체 음성 전송 중...", end=" ", flush=True)

    wav_io = io.BytesIO()
    with wave.open(wav_io, 'wb') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(pcm_chunk)
    wav_io.seek(0)
    wav_io.name = "chunk.wav"

    try:
        response = openai_client.audio.transcriptions.create(
            model="whisper-1",
            file=wav_io,
            language="ko",
            prompt="요리, 부엌, 레시피 관련 내용"  # 잡음 오인식 방지를 위한 프롬프트
        )
        stt_end_time = time.perf_counter()
        stt_latency = stt_end_time - stt_start_time
        text = response.text.strip()
        if text:
            print(f"-> ✅ 완료 ({stt_latency:.2f}초 소요) [인식 결과: '{text}']")
            return text
        else:
            print(f"-> ❌ 결과 없음 ({stt_latency:.2f}초 소요)")
    except Exception as e:
        print(f"\n❌ [STT API 에러] {e}")
    return ""

def process_audio_stream():
    """백그라운드에서 오디오 버퍼를 소비하며 발화 종료 시 한 번에 STT 수행"""
    global frame_buffer, speech_buffer, turn_detector, is_recording_active, tts_playing

    frame_bytes_size = turn_detector.frame_size
    pre_buffer = deque(maxlen=turn_detector.min_speech_frames + 5)

    while True:
        if not is_recording_active:
            time.sleep(0.1)
            continue

        if len(frame_buffer) >= frame_bytes_size:
            frame = bytes(frame_buffer[:frame_bytes_size])
            del frame_buffer[:frame_bytes_size]

            state = turn_detector.process_frame(frame)

            if not turn_detector.is_talking:
                pre_buffer.append(frame)

            # 말하기 도중일 때 누적 (전체 발화를 모음)
            if turn_detector.is_talking:
                if state == "start":
                    if tts_playing:
                        print("\n🛑 사용자 발화 감지: TTS 재생 중단!")
                        stop_tts_event.set()
                    
                    # VAD가 감지되기 직전(min_speech_frames)의 잘린 오디오 복구
                    for p_frame in pre_buffer:
                        speech_buffer.extend(p_frame)
                    pre_buffer.clear()
                    
                speech_buffer.extend(frame)

            # 턴 종료됨
            if state == "stop":
                print("⏳ [STT 정리] 발화 종료 -> 통신 큐로 전달 완료")
                if len(speech_buffer) > 0:
                    chunk = bytes(speech_buffer)
                    speech_buffer.clear()
                    
                    # API 호출을 별도 워커(worker) 스레드가 처리하도록 큐에 넣음
                    stt_queue.put(chunk)
                    
        else:
            time.sleep(0.01)

def stt_worker():
    """별도의 스레드에서 API 통신만 전담하여 VAD 버퍼 처리를 방해하지 않음"""
    while True:
        chunk = stt_queue.get()
        if chunk is None:
            break
        
        stt_total_start = time.perf_counter()
        full_text = send_to_whisper_api(chunk)
        stt_latency = time.perf_counter() - stt_total_start

        if full_text:
            print(f"✅ [전체 텍스트 변환 완료] ({stt_latency:.2f}초 소요)\n  -> 최종 텍스트: '{full_text}'")
            turn_queue.put(full_text)
        else:
            print("⚠️ [STT 결과 없음]")



# --- LLM 대화 + 시간 측정 ---
def chat_with_ai():
    global messages, metrics, openai_client
    try:
        print("⏳ [LLM 요청 시작] OpenAI GPT-4o-mini 모델에 대화 전송 중...", flush=True)
        start = time.perf_counter()
        completion = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
        )
        end = time.perf_counter()
        latency_ms = (end - start) * 1000.0
        
        print(f"✅ [LLM 응답 완료] ({latency_ms/1000.0:.2f}초 소요)")

        if not metrics["first_response_done"]:
            metrics["ttft_ms"] = latency_ms
            metrics["first_response_done"] = True
        else:
            metrics["turn_latencies_ms"].append(latency_ms)

        ai_msg = completion.choices[0].message.content
        return ai_msg
    except Exception as e:
        print(f"❌ [LLM 호출 예외 발생] {e}")
        return "AI 응답 중 문제가 발생했습니다."


# --- TTS의 짧은 길이 문제로 문장 단위로 분리 ---
def split_text_by_sentence(text, max_len=800):
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks = []
    current_chunk = ""

    for sentence in sentences:
        if len(current_chunk) + len(sentence) + 1 <= max_len:
            current_chunk += (sentence + " ")
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = sentence + " "
    if current_chunk:
        chunks.append(current_chunk.strip())
    return chunks


# --- 텍스트 → 음성(TTS) ---
def tts_skt(text):
    global tts_playing
    
    url = "https://apis.openapi.sk.com/axtts/tts"
    headers = {
        "accept": "audio/wav",
        "content-type": "application/json",
        "appKey": SK_APP_KEY,
    }

    text_chunks = split_text_by_sentence(text, max_len=800)
    
    tts_playing = True
    stop_tts_event.clear()

    for idx, chunk in enumerate(text_chunks, 1):
        if stop_tts_event.is_set():
            print("🔊 [TTS 재생 강제 종료]")
            break

        payload = {
            "model": "axtts-2-6",
            "voice": "jiyoung",
            "text": chunk,
            "speed": "0.9",
            "sr": 22050,
            "sformat": "wav",
        }

        print(f"⏳ [TTS 요청 시작] SKT axtts-2-6 API로 텍스트 분할 전송 중... (청크 {idx}/{len(text_chunks)})", end=" ", flush=True)
        tts_start = time.perf_counter()
        response = requests.post(url, json=payload, headers=headers)
        tts_end = time.perf_counter()
        tts_latency = tts_end - tts_start

        if response.status_code == 200:
            print(f"-> ✅ 응답 완료 ({tts_latency:.2f}초 소요). 오디오 재생 시작.")
            audio_bytes = io.BytesIO(response.content)
            data, samplerate = sf.read(audio_bytes, dtype="float32")
            sd.play(data, samplerate)
            
            # sd.wait() 대신 논블로킹 감시 -> VAD 인터럽트 발생 시 즉각 중지
            try:
                while sd.get_stream() is not None and sd.get_stream().active:
                    if stop_tts_event.is_set():
                        sd.stop()
                        break
                    time.sleep(0.05)
            except Exception:
                sd.wait() # 스트림 상태 못 가져올 경우 폴백
        else:
            print(f"-> ❌ [TTS 오류] {response.status_code} ({tts_latency:.2f}초 소요)")
            break
            
    tts_playing = False
    print("🔊 [전체 TTS 재생 완료]")


# ======== turndetect.py 스타일 턴 감지기 연동 ========
class TurnDetector:
    def __init__(self, sample_rate=16000, frame_ms=30, max_silence_ms=800, min_speech_ms=200, energy_threshold=400):
        self.sample_rate = sample_rate
        self.frame_size = int(sample_rate * frame_ms / 1000) * 2
        self.vad = webrtcvad.Vad(3)
        self.silence_limit = max_silence_ms // frame_ms
        self.min_speech_frames = min_speech_ms // frame_ms
        self.energy_threshold = energy_threshold  # RMS 에너지 기반 잡음 필터 강화
        self.reset()

    def get_rms(self, frame):
        # 16비트 오디오 데이터의 RMS(Root Mean Square) 계산
        samples = np.frombuffer(frame, dtype=np.int16)
        if len(samples) == 0:
            return 0
        rms = np.sqrt(np.mean(samples.astype(np.float32)**2))
        return rms

    def reset(self):
        self.speech_frames = 0
        self.sil_frames = 0
        self.is_talking = False
        self.log_counter = 0  # 로그를 위한 카운터

    def process_frame(self, frame):
        rms = self.get_rms(frame)
        try:
            is_speech_vad = self.vad.is_speech(frame, self.sample_rate)
        except Exception:
            is_speech_vad = False

        # 요리 중 발생하는 일정 데시벨 이하의 작은 소음은 발화로 취급 안 함
        is_speech = is_speech_vad and (rms >= self.energy_threshold)

        # 상태 현황 실시간 모니터링 출력 (약 0.9초마다 1번씩 출력)
        self.log_counter += 1
        if self.is_recording_log_enabled() and self.log_counter % 30 == 0:
            print(f"💡 [오디오 진단] RMS: {rms:.1f} (기준:{self.energy_threshold}) | VAD 판독: {'발화O' if is_speech_vad else '침묵X'} | 최종 판단: {'발화O' if is_speech else '침묵X'} | 누적 침묵 프레임: {self.sil_frames}/{self.silence_limit}")

        if is_speech:
            self.speech_frames += 1
            self.sil_frames = 0
            if not self.is_talking and self.speech_frames >= self.min_speech_frames:
                self.is_talking = True
                print("\n👂 [사용자 말씀 시작] - 듣고 있습니다...")
                return "start"
        else:
            if self.is_talking:
                self.sil_frames += 1
                if self.sil_frames >= self.silence_limit:
                    self.is_talking = False
                    self.speech_frames = 0
                    self.sil_frames = 0
                    print("✅ [사용자 말씀 종료] - 처리를 시작합니다.")
                    return "stop"
            else:
                # 발화 중이 아닐 때 침묵 프레임이 들어오면 누적된 발화 프레임 초기화 (산발적 소음 무시)
                self.speech_frames = 0
        return None

    def is_recording_log_enabled(self):
        # 스트림이 활성화된 상태에서만 로그 띄우기
        global is_recording_active
        return is_recording_active


# --- 메인 루프 ---
if __name__ == "__main__":
    print("🤖 아동용 요리 보조 AI가 준비되었습니다! 오늘의 요리를 시작할게요!")

    try:
        # 첫 번째 호출 (TTFT 측정 포함)
        ai_response = chat_with_ai()
        print(f"🤖 AI: {ai_response}")
        tts_skt(ai_response)

        # 여유로운 침묵 대기(1500ms) 및 현실적인 에너지 임계값(50) 설정
        turn_detector = TurnDetector(sample_rate=SAMPLE_RATE, max_silence_ms=1500, energy_threshold=50)
        
        # 첫 번째 응답 후, system_prompt를 일반 버전으로 변경하고 대화 기록 누적
        messages = [{"role": "system", "content": system_prompt_for_ongoing_chat}]
        messages.append({"role": "assistant", "content": ai_response})

        # STT API 통신 전용 스레드 (VAD 블로킹 방지)
        stt_worker_thread = threading.Thread(target=stt_worker, daemon=True)
        stt_worker_thread.start()

        # STT 백그라운드 스레드 시작 (VAD 루프)
        stt_thread = threading.Thread(target=process_audio_stream, daemon=True)
        stt_thread.start()

        # 오디오 스트림(마이크) 켜기
        is_recording_active = True
        stream = sd.RawInputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", callback=record_callback)
        stream.start()

        print("🎙️ 실시간 녹음 중입니다. 언제든 말씀하세요...")

        while True:
            # 사용자의 발화가 완료될 때까지 대기
            user_input = turn_queue.get() 
            print(f"👦 사용자: {user_input}")

            if not user_input or user_input.isspace():
                continue

            # 종료 키워드
            if any(word in user_input.lower() for word in ["종료", "끝내기", "그만"]):
                 print("👋 요리를 마무리합니다. 수고했어요!")
                 break

            messages.append({"role": "user", "content": user_input})
            
            # 사용자 발화에 의해 이전에 진행되던 작업이 있다면 초기화 (TTS는 이미 VAD에서 중지됨)
            
            ai_response = chat_with_ai()
            messages.append({"role": "assistant", "content": ai_response})

            print(f"🤖 AI: {ai_response}")
            tts_skt(ai_response)
            
            print("🎙️ 실시간 녹음 중입니다. 말씀하세요...")

    except KeyboardInterrupt:
        print("\n사용자에 의해 종료되었습니다.")
    finally:
        if 'stream' in locals() and stream.active:
            stream.stop()
            stream.close()
        # 루프를 빠져나가거나 예외가 발생해도 metrics 출력
        print_metrics_summary()
