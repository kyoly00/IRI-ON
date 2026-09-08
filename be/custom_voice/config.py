"""Custom cascade runtime의 환경 변수와 기본값.

모든 설정을 한 객체로 모아 런타임 코드가 ``os.getenv``에 흩어지지 않게 한다.
값은 세션이 시작될 때 읽으므로 테스트에서는 환경 변수만 바꿔 주입할 수 있다.
"""

from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class CustomVoiceSettings:
    """Custom cascade 한 세션이 사용할 모델/오디오/턴 설정."""

    # 브라우저에서 보내는 입력 PCM은 16 kHz, mono, signed 16-bit little-endian이다.
    input_sample_rate: int = 16_000
    input_frame_ms: int = 30

    # OpenAI 일반 TTS의 raw PCM 출력은 24 kHz signed 16-bit little-endian이다.
    output_sample_rate: int = 24_000

    # 다섯 프레임(150 ms) 연속 음성이면 발화를 시작하고, 이 시간만큼 침묵하면 턴을 닫는다.
    # 짧은 클릭/스피커 누설음이 진행 중인 TTS를 즉시 취소하지 않도록 시작 조건을 둔다.
    speech_start_frames: int = 5
    endpoint_silence_ms: int = 720
    minimum_speech_ms: int = 180
    maximum_speech_ms: int = 20_000

    # 에너지 VAD는 주변 소음의 이동 평균보다 이 배수 이상인 프레임을 음성으로 본다.
    vad_noise_multiplier: float = 2.8
    vad_min_rms: float = 850.0

    # endpoint까지 모은 발화 전체의 정규화 RMS가 이보다 작으면 STT에 보내지 않는다.
    # 에너지 VAD를 간신히 통과한 지속 잡음과 무음 기반 STT hallucination을 이중 차단한다.
    minimum_utterance_rms: float = 0.025

    # Realtime 모델이 아닌 독립 모델 세 개를 명시적으로 사용한다.
    stt_model: str = "gpt-4o-mini-transcribe"
    llm_model: str = "gpt-4.1-mini"
    tts_model: str = "gpt-4o-mini-tts-2025-12-15"
    tts_voice: str = "alloy"

    # 외부 API의 일시적 정지로 WebSocket 전체가 무한 대기하지 않게 제한한다.
    provider_timeout_seconds: float = 45.0

    @classmethod
    def from_env(cls) -> "CustomVoiceSettings":
        """``CUSTOM_VOICE_*`` 환경 변수를 읽어 타입이 보장된 설정을 만든다."""

        return cls(
            input_sample_rate=int(os.getenv("CUSTOM_VOICE_INPUT_RATE", "16000")),
            output_sample_rate=int(os.getenv("CUSTOM_VOICE_OUTPUT_RATE", "24000")),
            endpoint_silence_ms=int(os.getenv("CUSTOM_VOICE_ENDPOINT_MS", "720")),
            speech_start_frames=int(os.getenv("CUSTOM_VOICE_SPEECH_START_FRAMES", "5")),
            vad_noise_multiplier=float(os.getenv("CUSTOM_VOICE_VAD_MULTIPLIER", "2.8")),
            vad_min_rms=float(os.getenv("CUSTOM_VOICE_VAD_MIN_RMS", "850")),
            minimum_utterance_rms=float(os.getenv("CUSTOM_VOICE_MIN_UTTERANCE_RMS", "0.025")),
            stt_model=os.getenv("CUSTOM_VOICE_STT_MODEL", "gpt-4o-mini-transcribe"),
            llm_model=os.getenv("CUSTOM_VOICE_LLM_MODEL", "gpt-4.1-mini"),
            tts_model=os.getenv("CUSTOM_VOICE_TTS_MODEL", "gpt-4o-mini-tts-2025-12-15"),
            tts_voice=os.getenv("CUSTOM_VOICE_TTS_VOICE", "alloy"),
            provider_timeout_seconds=float(os.getenv("CUSTOM_VOICE_PROVIDER_TIMEOUT", "45")),
        )
