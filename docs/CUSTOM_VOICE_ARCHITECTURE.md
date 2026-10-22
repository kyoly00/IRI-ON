# Custom Voice 개선 이력과 최종 아키텍처

## 1. 문서 목적

이 문서는 IRI-ON의 `custom-cascade` 음성 대화 기능이 처음 어떤 구조였고, 실제 사용 중
어떤 문제가 발생했으며, 이를 해결하기 위해 무엇을 변경했는지를 정리한다. 현재 코드의
동작, 설정, 실패 시 fallback, 측정 방법까지 포함한다.

이 문서에서 말하는 "완성"은 요청된 구조가 코드와 프로토콜에 반영되었다는 뜻이다.
실제 사용자 환경의 끊김률, 음성 인식률, 화자 분리 정확도는 별도의 마이크·네트워크·GPU·
음성 데이터 측정 없이 확정하지 않는다.

---

## 2. 기존 custom-voice 구조

기존 custom-voice는 독립적인 STT, LLM, TTS 서비스를 WebSocket 세션에서 직렬로 연결한
cascade 구조였다.

```text
Browser microphone
  → browser AEC/NS/AGC
  → PCM WebSocket
  → server noise suppression
  → VAD
  → 완성된 발화 버퍼
  → 원격 STT
  → LLM token stream
  → 글자 수 중심 SentenceChunker
  → TTS 요청 1
  → TTS 요청 2
  → ...
  → WebSocket PCM
  → browser AudioBufferSource 재생
```

핵심 특징은 다음과 같았다.

- STT는 발화 종료 후 한 번 호출되는 final-only 방식이었다.
- VAD의 `speech_start`가 발생하면 진행 중인 응답을 즉시 중단했다.
- LLM 토큰을 짧은 텍스트로 모은 뒤 각 텍스트를 별개의 TTS 요청으로 보냈다.
- TTS 요청은 앞 요청의 스트림이 끝난 다음에야 다음 요청을 시작했다.
- 브라우저는 서버에서 받은 PCM마다 `AudioBufferSourceNode`를 만들어 재생했다.
- 입력 capture용 AudioContext와 출력 재생 컨텍스트가 분리되지 않았다.
- 서버와 브라우저 사이에는 응답 세대나 오디오 순번을 검증하는 식별자가 부족했다.

### 텍스트 분할 방식의 변화

저장소 초기 기준은 첫 조각 최소 6자, 이후 14자, 최대 100자였다. 문제 조사 과정에서
첫 24자, 이후 32자, 최대 160자로 완화했지만, 각 조각이 여전히 독립된 TTS 요청이라는
근본 구조는 바뀌지 않았다.

따라서 24자/32자 자체만이 원인은 아니었다. 더 큰 원인은 다음 요청을 이전 요청 완료 후
시작하는 직렬 합성과, 독립 요청마다 TTS 모델의 문맥과 운율이 다시 시작되는 점이었다.

---

## 3. 확인된 문제

### 3.1 TTS 청크 경계의 끊김

한 문장이 여러 TTS 요청으로 나뉠 수 있었다. 요청마다 합성 모델의 음향 상태가 새로
시작되므로 다음 현상이 발생할 수 있었다.

- 문장 중간의 억양과 호흡이 초기화됨
- 조각 사이 음량과 음색이 달라짐
- 앞 요청 종료와 다음 요청 첫 오디오 사이에 API 준비 시간만큼 공백 발생
- 두 PCM 경계의 마지막/첫 sample 값이 달라 클릭 노이즈 발생
- 조각 앞뒤에 생성된 무음이 누적됨

기존 분할기는 일부 문장부호를 확인했지만, 짧은 지연과 글자 수를 우선하기 때문에 의미
단위 보존을 충분히 보장하지 못했다.

### 3.2 LLM stream과 TTS의 직렬 연결

LLM 토큰은 스트리밍됐지만 TTS worker는 큐에서 하나를 꺼내 전체 합성을 끝낸 다음 다음
텍스트를 처리했다. 첫 TTS가 재생되는 동안 두 번째 TTS를 미리 준비하지 못해 합성 요청
사이의 latency가 그대로 청취 공백이 됐다.

### 3.3 브라우저 출력 재생

서버 오디오는 24 kHz PCM이지만 capture를 위해 만든 16 kHz AudioContext가 출력에도
사용될 수 있었다. 브라우저 재샘플링이 추가되고 입력 처리와 출력 재생의 lifecycle이
결합됐다.

고정 150ms 수준의 시작 버퍼는 네트워크가 안정적일 때 불필요한 지연을 만들고, 반대로
jitter가 큰 환경에서는 underrun을 막지 못할 수 있었다. 실제 underrun 횟수와 재생 대기
시간도 서버 trace에 남지 않았다.

### 3.4 취소와 늦게 도착한 오디오

사용자가 끼어들었을 때 현재 task와 브라우저 큐는 중단했지만, 이미 네트워크에 있거나
늦게 완료된 이전 응답 청크를 새 응답과 확실히 구별할 correlation key가 부족했다.

### 3.5 잡음과 turn-taking

VAD의 `speech_start`를 실제 질문 시작과 동일하게 취급했다. 식기 충격음, 잔향, AI 자신의
스피커 누설음, 짧은 맞장구도 응답을 취소할 수 있었다. 반대로 VAD의 `turn_end`는 음향적
침묵일 뿐, 사용자가 의미상 발화를 끝냈다는 보장은 없었다.

### 3.6 STT 처리

- 원격 STT final 결과만 존재했다.
- 긴 발화 중간 결과가 없었다.
- partial과 final의 권한 차이가 없었다.
- STT 추론과 실시간 오디오 수신을 분리하는 명시적인 bounded worker가 없었다.
- 화자 활동과 STT segment timestamp를 결합하는 경로가 없었다.

### 3.7 응답 보류/재개 명령

초기 응답 제어는 문구 중심으로 판단했기 때문에 "내가 끝날 때까지 답하지 마" 이후의
잡음, 옆 사람 대화, 재개 요청을 이전 대화 문맥과 함께 판별하기 어려웠다. 해제 문구를
STT가 잘못 인식하면 바로 응답을 재개할 위험도 있었다.

---

## 4. 개선 후 전체 구조

```text
Browser
 ├─ microphone capture AudioContext
 │   ├─ AEC
 │   ├─ browser NS/AGC (설정에 따라)
 │   └─ AudioWorklet → PCM16LE WebSocket
 │
 └─ playback AudioContext
     └─ ordered audio queue + adaptive jitter buffer

Server session
 ├─ bounded audio receive queue
 │   └─ NoiseSuppressionEngine → anti-alias resampler → 16 kHz mono PCM
 │
 ├─ primary VAD: Silero | optional MarbleNet
 │   ├─ pre-roll / speech buffer / endpoint
 │   └─ RMS는 진단 및 final low-energy gate에만 사용
 │
 ├─ STT: remote provider | faster-whisper
 │   ├─ mutable partial transcript
 │   ├─ final transcript
 │   ├─ no-speech / hallucination / duplicate filtering
 │   └─ local failure → remote provider fallback
 │
 ├─ optional speaker path
 │   ├─ Streaming Sortformer state worker
 │   └─ TitaNet consented identity matching
 │
 ├─ KoreanTurnDetector
 │   ├─ pause/end 판단 인터페이스
 │   ├─ backchannel 판별
 │   └─ explicit interrupt 판별
 │
 ├─ sLLM CommandRouter + ResponseGate
 │   └─ 현재 transcript + HOLD 상태 + 최근 대화 + 조리 단계
 │
 ├─ LLM token stream
 │   └─ TTSChunkScheduler
 │       ├─ 문장 종료
 │       ├─ 구두점
 │       ├─ 한국어 구문
 │       ├─ 최대 latency 대체 경계
 │       └─ 최대 길이 안전 분할
 │
 └─ ordered TTS prefetch worker
     ├─ 제한된 병렬 합성
     ├─ segment 순서 고정
     ├─ PCM 경계 검사/선택적 crossfade
     └─ response_id + generation_id + sequence_number
```

---

## 5. 영역별 변경 내용

### 5.1 잡음 처리

잡음 제거 구현은 `NoiseSuppressionEngine` 인터페이스 뒤로 분리했다.

지원 모드는 다음과 같다.

| 모드 | 입력 경로 | 브라우저 처리 | 서버 처리 |
|---|---|---|---|
| `none` | 16 kHz | 비활성 | passthrough |
| `browser` | 16 kHz | AEC + NS + AGC | passthrough |
| `rnnoise` | 48 kHz transport | AEC + AGC | RNNoise 후 16 kHz 변환 |
| `deepfilternet` | 48 kHz transport | AEC + AGC | DeepFilterNet 후 16 kHz 변환 |

Deep NS와 브라우저 NS는 중복 적용하지 않는다. AEC는 AI 자신의 TTS가 마이크로 다시
유입되는 문제를 줄이기 위해 우선 브라우저/장치 기능을 사용한다. RMS는 MarbleNet 또는
Silero 확률을 대체하지 않으며, 진단 로그와 낮은 에너지 발화의 STT 차단에 사용한다.

### 5.2 VAD

`CUSTOM_VOICE_VAD_BACKEND`로 다음을 선택한다.

- `silero`: 기본값
- `marblenet`: 선택적 NVIDIA frame VAD
- `energy`: ML VAD가 없을 때의 fallback

MarbleNet은 20ms frame speech probability와 rolling context를 사용한다. 무거운 NeMo 모델
초기화는 `session_ready` 이후 background task에서 실행한다. 준비 전에는 Silero로 음성을
받기 때문에 모델 다운로드가 WebSocket handshake를 막지 않는다.

Silero ONNX 경로도 각 512-sample frame 앞에 공식 wrapper와 같은 64-sample streaming
context와 RNN state를 유지한다. 이 context가 없으면 모델은 호출되더라도 연속 음성의
확률이 낮아질 수 있다.

선택한 NVIDIA multilingual MarbleNet checkpoint는 공식 지원 언어에 한국어를 명시하지
않으므로 기본 VAD로 승격하지 않았다. 동일 WAV 비교는
`be/scripts/evaluate_vad_backends.py`로 수행한다.

### 5.3 STT

`CUSTOM_VOICE_STT_BACKEND`는 `openai` 또는 `faster_whisper`다. 기존 원격 provider를
제거하지 않았다.

faster-whisper 경로는 다음을 수행한다.

- 16 kHz mono PCM float 변환
- word timestamp 활성화
- VAD가 이미 적용된 입력이므로 내부 VAD 중복 비활성화
- no-speech와 hallucination silence 설정 적용
- partial은 작은 beam, final은 더 큰 beam 사용
- 겹치는 중복 segment 억제
- asyncio 수신 loop를 막지 않도록 worker thread에서 추론
- 로컬 모델 로드 또는 GPU 추론 실패 시 원격 STT로 강등

partial transcript는 `final: false`, `mutable: true`로 전달된다. UI 표시와 빠른 명시적
중단 판단에는 사용할 수 있지만 조리 명령이나 LLM 응답 실행 권한은 없다. 명령 실행은
final transcript와 Command Router를 통과한 뒤에만 가능하다.

### 5.4 Turn-taking

세션 상태는 다음 단계를 표현할 수 있게 확장했다.

```text
IDLE/CONNECTING
  → LISTENING
  → USER_SPEAKING
  → USER_PAUSED
  → WAITING_STT
  → THINKING
  → ASSISTANT_SPEAKING
  → LISTENING

ASSISTANT_SPEAKING
  → INTERRUPTING
  → USER_SPEAKING / WAITING_STT
```

현재 faster-whisper가 NeMo EOU/EOB token을 출력한다고 가정하지 않는다. 대신
`KoreanTurnDetector` 인터페이스를 분리해 이후 EOU-capable ASR로 교체할 수 있게 했다.

### 5.5 Barge-in

새 동작은 다음과 같다.

1. AI 발화 중 VAD가 사용자 음성 후보를 감지한다.
2. 브라우저는 `user_speech_started`만으로 즉시 재생을 폐기하지 않는다.
3. 기본 400ms 동안 연속 음성이 유지되면 실제 barge-in으로 확정한다.
4. 서버 응답 generation을 무효화하고 LLM/TTS task를 취소한다.
5. 서버가 `playback_stop`을 보낸다.
6. 브라우저는 예약/재생 중 source를 모두 중단하고 큐를 비운다.
7. 이후 도착한 이전 generation 청크는 폐기한다.
8. 사용자 final STT를 처리하고 새 응답을 시작한다.

faster-whisper partial에서 "잠깐", "멈춰", "그만", "다시 설명해" 같은 명시적 제어
문구가 확인되면 debounce 종료를 기다리지 않고 중단할 수 있다. "음", "네", "맞아요"
같은 짧은 발화는 backchannel로 분리해 항상 새 응답을 만들지 않는다.

### 5.6 Command Router와 Response Gate

라우터는 현재 문장만 보지 않고 다음 문맥을 sLLM에 전달한다.

- 현재 `NORMAL`/`HOLD` 모드
- 재개 확인 대기 여부
- 최근 user/assistant 대화
- 현재 레시피와 조리 단계
- 현재 final transcript

분류 결과는 `conversation`, `side_talk`, `noise`, `hold`, `release`,
`confirm_release` 중 하나다. confidence가 기준보다 낮거나 라우터가 실패하면 fail-closed로
응답하지 않는다.

HOLD 상태에서 한 번의 불확실한 해제 인식만으로 재개하지 않는다. `release` 판정 후 별도의
`confirm_release`를 통과해야 Response Gate가 다시 열린다.

### 5.7 TTSChunkScheduler

현재 기본값은 다음과 같다.

| 설정 | 기본값 | 의미 |
|---|---:|---|
| preferred minimum | 24자 | 너무 작은 요청을 피하기 위한 선호값 |
| target | 64자 | latency가 허용할 때 찾는 자연스러운 목표 범위 |
| maximum | 180자 | 긴 문장의 절대 안전 한도 |
| maximum latency | 550ms | LLM token 대기가 길어질 때 대체 경계를 내보내는 한도 |
| max inflight | 2 | 동시에 준비할 TTS 요청 수 |

24자와 64자는 강제 절단 위치가 아니다. scheduler의 경계 우선순위는 다음과 같다.

1. 문장 종료
2. 쉼표 등 구두점
3. 한국어 연결 어미 기반 구문 경계
4. latency 초과 시 가까운 공백
5. 최대 길이의 공백 또는 hard split

TTS API가 별도 요청 사이의 음향 상태 continuation을 제공한다고 가정하지 않는다. 독립
요청이 필요한 상황에서 요청 수를 줄이고, 다음 요청 합성을 선행해 네트워크/API 공백을
현재 재생 시간 뒤로 숨기는 방식이다.

### 5.8 PCM 경계 처리

각 독립 합성 경계에서 다음을 측정한다.

- 마지막 sample과 첫 sample의 정규화 jump
- 앞뒤 50ms RMS 차이(dB)
- 앞 조각 trailing silence
- 뒤 조각 leading silence

경계의 짧은 무음을 제거하고 jump가 기준 이상일 때에만 5ms crossfade를 적용한다. 모든
경계를 무조건 fade하면 자음 attack과 발음 선명도를 훼손할 수 있으므로 선택적으로만
처리한다. 최종 응답 끝에는 필요한 경우 짧은 fade-out을 적용한다.

### 5.9 TTS 선행 합성과 순서 보장

텍스트 segment의 합성 요청은 제한적으로 동시에 시작할 수 있지만 전송 worker는 항상
`segment_index` 순서로만 PCM을 꺼낸다. 각 PCM event에는 다음 정보가 포함된다.

- `response_id`
- `generation_id`
- `sequence_number`
- `segment_index`
- `segment_chunk_index`
- `sample_rate=24000`
- `channels=1`
- `pcm_format=s16le`

서버의 WebSocket send lock과 브라우저의 sequence 검사로 생성 순서와 재생 순서를 함께
보장한다.

### 5.10 브라우저 연속 재생과 jitter buffer

capture와 playback AudioContext를 분리했다. 서버 PCM의 실제 24 kHz sample rate로
AudioBuffer를 만들고, 각 `AudioBufferSourceNode`의 `startAt`을 이전 버퍼 종료 시각에
정확히 맞춘다.

기본 adaptive jitter는 300ms에서 시작하고 250~500ms 범위에서 arrival deviation과
underrun 발생을 반영한다. underrun이 생기면 다음 응답의 최소 버퍼를 올리고, 끊김 없는
응답이 이어질 때만 천천히 낮춘다.
고정 150ms 비교 빌드는 다음 환경 변수로 실행한다.

```text
VITE_CUSTOM_VOICE_FIXED_JITTER_MS=150
```

브라우저는 일정 간격으로 다음 측정값을 서버 trace에 보낸다.

- queued milliseconds
- scheduled wait
- estimated jitter
- target jitter
- underrun count
- adaptive/fixed mode

### 5.11 응답 세대와 늦은 청크 폐기

한 assistant 응답마다 새 `response_id`와 `generation_id`가 발급된다. 오디오는 0부터
증가하는 `sequence_number`를 가진다.

브라우저는 현재 response/generation과 일치하지 않거나 예상 sequence가 아닌 청크를
재생하지 않는다. barge-in, HOLD, 새 응답 시작 시 이전 generation이 무효화되므로 취소된
TTS API 응답이 늦게 도착해도 다시 재생되지 않는다.

### 5.12 Speaker diarization과 identification

두 기능을 분리했다.

- Streaming Sortformer: 세션 안에서 `speaker_0`~`speaker_3` 활동을 추적하는 diarization
- TitaNet: 등록된 사용자의 embedding과 cosine similarity를 계산하는 identification

Sortformer는 파일을 저장한 뒤 일괄 `diarize()`하는 방식이 아니다. 16 kHz audio chunk를
비동기 queue로 받아 `forward_streaming_step`을 호출하고 speaker cache, FIFO, permutation
상태를 세션 동안 유지한다. 재연결 시 상태는 초기화하며 `speaker_0`은 영구 사용자 ID가
아니다.

TitaNet은 등록 디렉터리와 embedding이 존재할 때만 모델을 로드한다. 모든 사용자에게
임의의 similarity threshold를 적용하지 않는다. 설정된 threshold가 없거나 검증되지 않은
경우 `unknown_speaker`를 반환한다.

VAD와 diarization은 중첩된 두 음성 파형을 물리적으로 분리하지 않는다. speech separation은
현재 기본 경로에 포함하지 않았고, 필요한 경우에만 overlap detection 이후 별도 worker에서
실험해야 한다.

---

## 6. WebSocket 주요 이벤트

| 방향 | 이벤트 | 역할 |
|---|---|---|
| Server → Browser | `session_ready` | sample rate, NS, 요청/활성 backend 전달 |
| Server → Browser | `audio_input_ready` | 서버가 실제 PCM을 받기 시작했음을 알림 |
| Server → Browser | `user_speech_started` | VAD speech candidate 시작 |
| Server → Browser | `user_speech_ended` | VAD endpoint 도달 |
| Server → Browser | `user_transcript` | mutable partial 또는 final STT |
| Server → Browser | `response_started` | response/generation 초기화 |
| Server → Browser | `assistant_delta` | LLM text delta |
| Server → Browser | `audio_chunk` | 순번과 포맷이 포함된 PCM |
| Server → Browser | `playback_stop` | generation 무효화와 재생 큐 폐기 |
| Server → Browser | `assistant_done` | 응답 완료 |
| Browser → Server | `playback_metrics` | jitter, queue, underrun 측정 |
| Browser → Server | `playback_progress` | barge-in 전 실제 청취 위치 보고 |

`playback_progress`는 사용자가 실제로 듣지 못한 assistant 문장을 history에서 잘라내는
state rollback에도 사용한다.

---

## 7. 실패 및 fallback 정책

| 실패 | 동작 |
|---|---|
| MarbleNet 설치/초기화 실패 | Silero 유지 |
| Silero 모델/ONNX 실패 | energy detector 사용 |
| faster-whisper 로드/OOM 실패 | 기존 원격 STT로 강등 |
| Sortformer 실패 | 화자 정보를 `unknown_speaker`로 유지 |
| TitaNet 미설치/등록 없음/threshold 없음 | identity를 `unknown_speaker`로 유지 |
| Response Gate router 실패/낮은 confidence | 응답 상태 변경 명령만 fail-closed |
| 단계 이동 reviewer 실패/시간 초과 | 이동 side effect만 차단하고 LLM이 확인 질문 |
| noise suppression 실패 | 오류 event를 보내고 손상된 audio path 중단 |
| TTS 실패 | 오류 event를 보내고 해당 turn 종료 |
| audio receive queue overflow | 오래 기다리게 하지 않고 frame drop 수를 trace에 기록 |

---

## 8. 주요 설정

```text
# Noise/VAD
CUSTOM_VOICE_NOISE_SUPPRESSION=none|browser|rnnoise|deepfilternet
CUSTOM_VOICE_VAD_BACKEND=silero|marblenet|energy
CUSTOM_VOICE_VAD_THRESHOLD=0.25
CUSTOM_VOICE_VAD_DEBUG=1  # frame별 Silero 확률/RMS/context/state 진단
CUSTOM_VOICE_ENDPOINT_CANDIDATE_MS=280
CUSTOM_VOICE_ENDPOINT_FALLBACK_MS=720
CUSTOM_VOICE_ENDPOINT_HARD_MS=1100

# STT
CUSTOM_VOICE_STT_BACKEND=openai|faster_whisper
CUSTOM_VOICE_FASTER_WHISPER_MODEL=large-v3-turbo
CUSTOM_VOICE_PARTIAL_STT_INTERVAL_MS=600
CUSTOM_VOICE_PARTIAL_STT_MIN_AUDIO_MS=1200
# semantic 280ms endpoint는 faster_whisper partial 사용 시 활성화된다.
# openai STT에서는 720ms silence fallback을 사용한다.

# Turn/Barge-in
CUSTOM_VOICE_BARGE_IN_CONFIRMATION_MS=200
CUSTOM_VOICE_AUDIO_QUEUE_FRAMES=200

# LLM / Router / navigation review
CUSTOM_VOICE_LLM_MODEL=gpt-5.4-nano
CUSTOM_VOICE_ROUTER_MODEL=gpt-5-nano
CUSTOM_VOICE_ROUTER_TIMEOUT=2.0
CUSTOM_VOICE_NAVIGATION_REVIEW_TIMEOUT=2.0
CUSTOM_VOICE_NAVIGATION_REVIEW_JOIN_MS=250

# TTS
CUSTOM_VOICE_TTS_FIRST_MIN_CHARS=12
CUSTOM_VOICE_TTS_FIRST_LATENCY_MS=380
CUSTOM_VOICE_TTS_MIN_CHARS=24
CUSTOM_VOICE_TTS_TARGET_CHARS=64
CUSTOM_VOICE_TTS_MAX_CHARS=180
CUSTOM_VOICE_TTS_MAX_LATENCY_MS=550
CUSTOM_VOICE_TTS_MAX_INFLIGHT=2

# Speaker
CUSTOM_VOICE_DIARIZATION_BACKEND=none|sortformer
CUSTOM_VOICE_SPEAKER_IDENTIFICATION_BACKEND=none|titanet
CUSTOM_VOICE_SPEAKER_EMBEDDING_DIR=<consented embedding directory>
CUSTOM_VOICE_SPEAKER_SIMILARITY_THRESHOLD=<calibrated value>
```

NeMo와 faster-whisper 선택 의존성은 루트의 `voice-local-requirements.in`에 분리되어 있다.

---

## 9. 관측과 검증

### 9.1 자동 회귀 테스트

`tests/test_tts_pipeline.py`는 다음을 검증한다.

- 문장 경계 우선 분할
- latency 초과 시 공백 기반 대체 경계
- 최대 길이 안전 분할
- 최대 길이 뒤 문장부호가 safety limit를 우회하지 않는지 확인
- 큰 PCM jump 감지와 선택적 crossfade

기존 custom-voice 테스트는 noise engine 계약, VAD, response gate, TTS 오류 전파,
playback rollback과 text→LLM→TTS 통합 경로를 검증한다.

단계 이동 reviewer는 main LLM의 function tool로 노출하지 않는다. 단계 관련 후보 발화에서만
독립적인 소형 모델 요청을 main LLM과 동시에 시작한다. 명시적인 “다음/이전 단계” 요청은
로컬 검증으로 즉시 통과시키며, 문맥형 완료 발화는 두 모델의 action이 일치할 때만 UI 이동을
허용한다. main LLM이 이동을 제안하지 않으면 reviewer 결과도 side effect를 만들지 않는다.

승인된 단계 이동은 `pending_navigation`과 `navigation_id`를 UI event보다 먼저 기록한다.
브라우저 `step_changed`가 도착하면 같은 id와 목표 단계를 확인해 `confirmed`로 전환하고,
짧은 대기 안에 확인되지 않으면 tool result를 `pending`으로 유지한다. 따라서 UI가 늦어도
현재 화면 단계를 미리 바꾸지 않으며, 다음 LLM은 pending/confirmed 상태를 구분한다.

명시적인 영상 제어 발화는 Response Gate보다 먼저 처리하고 main LLM에는 영상 제어 schema만
제공한다. 따라서 “영상 멈춰”가 답변 보류로 오인되거나 타이머·단계 도구로 잘못 선택될 가능성을
줄이면서도, 실행 후 음성 답변 자체는 고정 템플릿이 아닌 LLM 문맥을 유지한다.

세션 로그의 `perceived_server_ttfa_ms`, `endpoint_latency_ms`,
`llm_first_token_latency_ms`를 함께 봐야 한다. 기존 `ttfa_ms`만으로는 실제 발화 뒤 endpoint
대기와 LLM/TTS 지연을 분리할 수 없다. 외부 API용 HTTP client는 세션 간 keep-alive pool을
공유하며 애플리케이션 종료 시 한 번 닫는다.

### 9.2 실제 TTS 비교

동일한 문장, voice, 장치, 네트워크 조건으로 변경 전/후 WAV와 event log를 수집한다.
manifest를 만든 뒤 다음을 실행한다.

```powershell
python -m be.scripts.evaluate_tts_continuity manifest.json
```

도구는 입력 artifact에 존재하는 값만 사용해 다음을 출력한다.

- 경계 sample jump
- 경계 전후 RMS 차이
- 경계 주변 무음
- sequence 오류
- underrun
- playback scheduling wait

실제 capture 없이 성공률이나 개선율을 생성하지 않는다.

### 9.3 VAD 비교

같은 16 kHz mono PCM16 WAV를 두 detector에 입력한다.

```powershell
python -m be.scripts.evaluate_vad_backends sample.wav
```

출력의 실제 detector class를 확인해야 한다. NeMo가 없으면 MarbleNet 요청이 Silero로
fallback될 수 있으므로 class가 같다면 MarbleNet 비교 결과로 보고하면 안 된다.

---

## 10. 관련 파일

| 파일 | 책임 |
|---|---|
| `be/custom_voice/runtime.py` | 세션, 수신 worker, turn, STT/LLM/TTS orchestration, 취소 |
| `be/custom_voice/config.py` | backend 및 latency 설정 |
| `be/custom_voice/noise_engine.py` | 잡음 제거 인터페이스와 공통 audio frame |
| `be/custom_voice/noise_suppression.py` | browser/pass-through, RNNoise, DeepFilterNet adapter |
| `be/custom_voice/silero_vad.py` | VAD 선택과 Silero/energy fallback |
| `be/custom_voice/nemo_vad.py` | MarbleNet rolling frame VAD |
| `be/custom_voice/stt_engine.py` | 원격/faster-whisper STT와 graceful degradation |
| `be/custom_voice/speaker_pipeline.py` | streaming Sortformer와 TitaNet |
| `be/custom_voice/dialogue_control.py` | Command Router, Response Gate, TurnDetector |
| `be/custom_voice/tts_pipeline.py` | 의미 기반 scheduler와 PCM 경계 처리 |
| `be/custom_voice/providers.py` | STT/LLM/router/TTS provider 호출 |
| `fe/app/src/lib/ai/speech/custom-cascade/use-voice-chat.custom.ts` | capture, WebSocket, 연속 재생, jitter, stale drop |
| `be/scripts/evaluate_tts_continuity.py` | TTS artifact 비교 |
| `be/scripts/evaluate_vad_backends.py` | 동일 입력 VAD 비교 |

---

## 11. 현재 남은 한계

- NeMo 모델을 실제 운영 GPU에서 부하·지연 측정하지 않았다.
- MarbleNet 선택 checkpoint의 한국어 성능은 별도 corpus로 검증해야 한다.
- faster-whisper partial은 진정한 token-by-token streaming decoder가 아니라 rolling audio
  snapshot 재추론이다.
- 독립 TTS 요청 간 모델 내부 운율 상태는 이어지지 않는다. 현재 구현은 의미 단위 확대,
  선행 합성, 경계 후처리로 영향을 줄이는 구조다.
- Web Audio queue는 연속 예약 방식이며 AudioWorklet 기반 output ring buffer로 전면 교체한
  것은 아니다. 현재 방식의 underrun 측정 결과가 부족할 때만 전환을 검토한다.
- Sortformer/TitaNet 임계값과 화자 매핑 정확도는 실제 동의 기반 사용자 음성으로 보정해야
  한다.
- overlap speech separation은 구현하지 않았다. 실제 동시 발화 요구와 GPU 예산을 확인한
  뒤 선택적으로 추가해야 한다.
- ChatGPT Voice와 같은 체감 품질은 architecture만으로 보장되지 않는다. 실제 기기에서
  endpoint latency, STT WER, TTS boundary artifact, barge-in false accept/reject를 반복 측정하고
  설정을 보정해야 한다.
