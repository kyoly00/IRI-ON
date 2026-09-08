# Custom cascade voice runtime

이 폴더는 LiveKit SDK/패키지와 OpenAI Realtime API를 사용하지 않는 독립 음성
runtime이다. 기존 `be/routers/realtime_openAI.py`와 프런트 Realtime 훅은 그대로
보존되며, 화면의 선택 변수만 두 구현 중 하나를 가리킨다.

## 전체 흐름

```text
Browser microphone
  -> Web Audio AEC / noise suppression / AGC
  -> AudioWorklet (Float32)
  -> 직접 downsample (16 kHz, mono, PCM s16le)
  -> /custom-voice/ws WebSocket
  -> AdaptiveEnergyEndpointDetector
       | speech_start -> 진행 중 LLM/TTS 취소 + playback_stop
       ` turn_end
  -> 일반 STT HTTP + ProsodyExtractor sidecar
  -> PIIRedactor
  -> streaming Chat Completions HTTP/SSE
       | function tools -> browser assistant_event
       ` text delta -> UI + SentenceChunker
  -> 일반 TTS HTTP (24 kHz PCM)
  -> base64 audio_chunk
  -> Web Audio scheduling / speaker
  -> CustomTraceStore -> conversation_logs -> evaluate_voice_metrics.py
```

## 파일 책임

- `config.py`: 모델, sample rate, VAD/endpoint 기준 환경 변수
- `audio.py`: PCM framing, adaptive energy VAD, endpointing, prosody sidecar
- `privacy.py`: 주민번호, 전화, 이메일, 카드번호 텍스트 마스킹
- `providers.py`: 음성 SDK 대신 일반 HTTP로 호출하는 STT/LLM/TTS adapter
- `tools.py`: 허용된 function tool 검증, 실행, UI event 변환
- `tracing.py`: session/turn/speech/tool correlation과 evaluator 호환 로그
- `context.py`: 사용자/레시피 DB 정보 기반 system prompt
- `runtime.py`: full-duplex 수신, barge-in 취소, streaming fan-out orchestration
- `router.py`: session-info REST와 PCM WebSocket endpoint

프런트 counterpart는
`fe/app/src/lib/ai/speech/custom-cascade/use-voice-chat.custom.ts`이다.

## 구현 선택

프런트 `.env`에서 다음 변수 하나를 선택한다. 기본값은 기존 동작을 보존하는
`realtime`이다.

```dotenv
VITE_VOICE_IMPLEMENTATION=realtime
# VITE_VOICE_IMPLEMENTATION=custom_cascade
```

변수는 `fe/app/src/lib/ai/speech/use-voice-chat.ts`에서 두 hook 중 하나를 선택한다.
기존 Realtime 훅은 수정하거나 감싸지 않는다. Vite 환경 변수이므로 값을 바꾸면
프런트 dev server를 다시 시작해야 한다.

## 입력 오탐 방지와 진단 로그

- 기본 VAD는 150 ms 연속 발화와 raw RMS 850 이상을 요구한다.
- endpoint까지 수집한 전체 발화의 정규화 RMS가 `0.025` 미만이면 STT 호출 전에 버린다.
- STT prompt는 무음에서 prompt 자체를 transcript로 만드는 hallucination을 피하려고 보내지 않는다.
- 서버 콘솔에는 `speech started`, STT, LLM first token, TTS request/first audio,
  interruption, provider 오류와 최종 trace 경로가 session/turn ID와 함께 출력된다.
- 환경에 따라 `CUSTOM_VOICE_VAD_MIN_RMS`, `CUSTOM_VOICE_SPEECH_START_FRAMES`,
  `CUSTOM_VOICE_MIN_UTTERANCE_RMS`를 조정할 수 있다.

## 실행

기존 FastAPI 서버 외에 별도 worker는 필요 없다. Vite 개발 서버를 쓸 때는 REST는
`/api` proxy를, WebSocket은 `ws://localhost:8000`을 가리키도록 `.env.example` 값을
사용한다.

```powershell
python be/main.py
cd fe/app
npm run dev
```

필수 비밀값은 기존과 같이 `be/.env`의 `OPENAI_API_KEY`이다. 새 runtime은 Realtime
client secret이 아니라 `/audio/transcriptions`, `/chat/completions`, `/audio/speech`
일반 API만 사용한다. 선택 설정은 `be/.env.example`에 정리되어 있다.

## 평가

```powershell
python be/evaluate_voice_metrics.py --mode benchmark --architecture custom_cascade
python be/evaluate_voice_metrics.py --mode compare
python be/evaluate_voice_metrics.py --mode analyze-logs --architecture custom_cascade
```

합성 benchmark는 평가 배선 검사용이다. 실제 비교는 같은 음성 corpus를 두 구현에
재생하고 저장 로그의 STT latency, TTFT, TTFA, E2E, barge-in, tool latency를 본다.

## 의도적인 경계

- VAD/endpointing/prosody는 직접 구현되어 별도 음성 runtime SDK가 필요 없다.
- PII 필터는 STT 이후부터 LLM과 로그를 보호한다. 원본 음성까지 외부 STT에 보내면
  안 되는 배포는 `providers.py`의 `transcribe`만 로컬 STT adapter로 교체해야 한다.
- base64 PCM은 구현을 단순하고 검증 가능하게 만드는 대신 binary multiplex보다 약
  33% 전송량이 크다. 병목이 확인되면 protocol version을 올려 binary frame으로 바꾼다.
- energy VAD는 가볍고 완전 로컬이지만 학습 기반 semantic turn model보다 문장 중간의
  긴 침묵에 약하다. `AdaptiveEnergyEndpointDetector` 계약을 유지한 채 detector만 교체할
  수 있도록 runtime과 분리했다.
