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
    transport_frame_ms: int = 20

    # OpenAI 일반 TTS의 raw PCM 출력은 24 kHz signed 16-bit little-endian이다.
    output_sample_rate: int = 24_000

    # 세 프레임(약 96 ms) 연속 음성이면 발화를 시작하고, 이 시간만큼 침묵하면 턴을 닫는다.
    # 짧은 클릭/스피커 누설음이 진행 중인 TTS를 즉시 취소하지 않도록 시작 조건을 둔다.
    speech_start_frames: int = 3
    endpoint_silence_ms: int = 720
    # VAD는 음성 존재만 판정하고, 실제 turn 종료는 EndpointCoordinator가 결정한다.
    endpoint_candidate_silence_ms: int = 280
    endpoint_fallback_silence_ms: int = 720
    endpoint_hard_silence_ms: int = 1_100
    minimum_speech_ms: int = 180
    maximum_speech_ms: int = 20_000

    # 에너지 VAD는 주변 소음의 이동 평균보다 이 배수 이상인 프레임을 음성으로 본다.
    vad_noise_multiplier: float = 2.8
    vad_min_rms: float = 850.0

    # VAD backend: silero | marblenet | energy. ``vad_mode``는 기존 배포 호환 alias다.
    vad_mode: str = "silero"
    vad_backend: str = "silero"
    # Browser NS가 켜진 16 kHz capture의 실제 음성 확률을 기준으로 한 시작 threshold다.
    # 3개 연속 frame 조건을 함께 쓰므로 0.25는 단일 충격음보다 지속 발화에 민감하다.
    vad_threshold: float = 0.25
    vad_debug_logging: bool = False
    vad_model_path: str | None = None
    marblenet_model: str = "nvidia/frame_vad_multilingual_marblenet_v2.0"
    marblenet_context_ms: int = 1000
    marblenet_inference_interval_ms: int = 100

    # endpoint까지 모은 발화 전체의 정규화 RMS가 이보다 작으면 STT에 보내지 않는다.
    # 에너지 VAD를 간신히 통과한 지속 잡음과 무음 기반 STT hallucination을 이중 차단한다.
    minimum_utterance_rms: float = 0.012

    # browser/none은 기존 16 kHz transport를 유지한다. Deep NS는 48 kHz에서 먼저
    # 처리한 뒤 서버의 anti-alias resampler를 거쳐 VAD/STT용 16 kHz가 된다.
    noise_suppression: str = "browser"
    deep_noise_sample_rate: int = 48_000
    rnnoise_library: str | None = None
    deepfilternet_model: str | None = None

    # Realtime 모델이 아닌 독립 모델들을 명시적으로 사용한다.
    stt_model: str = "gpt-4o-mini-transcribe"
    stt_backend: str = "openai"
    faster_whisper_model: str = "large-v3-turbo"
    faster_whisper_device: str = "auto"
    faster_whisper_compute_type: str = "default"
    partial_stt_interval_ms: int = 600
    partial_stt_min_audio_ms: int = 1200
    audio_receive_queue_frames: int = 200
    barge_in_confirmation_ms: int = 200
    llm_model: str = "gpt-5.4-nano"
    router_model: str = "gpt-5-nano"
    router_timeout_seconds: float = 2.0
    navigation_review_timeout_seconds: float = 2.0
    navigation_review_join_timeout_ms: int = 250
    llm_default_max_tokens: int = 140
    llm_instruction_max_tokens: int = 240
    llm_detailed_max_tokens: int = 360
    tts_model: str = "gpt-4o-mini-tts-2025-12-15"
    tts_voice: str = "alloy"
    tts_instructions: str = "자연스러운 한국어 대화체로, 문장 사이 호흡과 음량을 일정하게 유지해 말해 주세요."

    # TTS 문장 분할은 글자 수로 즉시 자르지 않고 의미 경계와 대기 시간을 함께 본다.
    tts_preferred_min_chars: int = 24
    tts_target_chars: int = 64
    tts_maximum_chars: int = 180
    tts_maximum_chunk_latency_ms: int = 550
    tts_first_min_chars: int = 12
    tts_first_chunk_latency_ms: int = 380
    tts_max_inflight_requests: int = 2

    # 선택적 NVIDIA speaker pipeline. 모델 설치/초기화 실패 시 세션은 speaker=unknown으로 계속된다.
    diarization_backend: str = "none"
    sortformer_model: str = "nvidia/diar_streaming_sortformer_4spk-v2.1"
    sortformer_activity_threshold: float = 0.5
    speaker_identification_backend: str = "none"
    titanet_model: str = "titanet_large"
    speaker_embedding_dir: str | None = None
    speaker_similarity_threshold: float | None = None
    separation_backend: str = "none"

    # 외부 API의 일시적 정지로 WebSocket 전체가 무한 대기하지 않게 제한한다.
    provider_timeout_seconds: float = 45.0

    @property
    def transport_sample_rate(self) -> int:
        """브라우저가 WebSocket으로 보내야 하는 PCM sample rate."""

        if self.noise_suppression in {"rnnoise", "deepfilternet"}:
            return self.deep_noise_sample_rate
        return self.input_sample_rate

    @property
    def browser_audio_constraints(self) -> dict[str, bool]:
        """Browser NS와 deep NS가 중복 적용되지 않는 capture 설정."""

        return {
            "echo_cancellation": self.noise_suppression != "none",
            "noise_suppression": self.noise_suppression == "browser",
            "auto_gain_control": self.noise_suppression != "none",
        }

    @classmethod
    def from_env(cls) -> "CustomVoiceSettings":
        """``CUSTOM_VOICE_*`` 환경 변수를 읽어 타입이 보장된 설정을 만든다."""

        noise_suppression = os.getenv("CUSTOM_VOICE_NOISE_SUPPRESSION", "browser").strip().lower()
        if noise_suppression not in {"none", "browser", "rnnoise", "deepfilternet"}:
            raise ValueError(
                "CUSTOM_VOICE_NOISE_SUPPRESSION must be one of: none, browser, rnnoise, deepfilternet"
            )
        vad_backend = os.getenv(
            "CUSTOM_VOICE_VAD_BACKEND",
            os.getenv("CUSTOM_VOICE_VAD_MODE", "silero"),
        ).strip().lower()
        if vad_backend not in {"silero", "marblenet", "energy"}:
            raise ValueError("CUSTOM_VOICE_VAD_BACKEND must be one of: silero, marblenet, energy")
        stt_backend = os.getenv("CUSTOM_VOICE_STT_BACKEND", "openai").strip().lower()
        if stt_backend not in {"openai", "faster_whisper"}:
            raise ValueError("CUSTOM_VOICE_STT_BACKEND must be one of: openai, faster_whisper")
        diarization_backend = os.getenv("CUSTOM_VOICE_DIARIZATION_BACKEND", "none").strip().lower()
        if diarization_backend not in {"none", "sortformer"}:
            raise ValueError("CUSTOM_VOICE_DIARIZATION_BACKEND must be one of: none, sortformer")
        speaker_identification_backend = os.getenv(
            "CUSTOM_VOICE_SPEAKER_IDENTIFICATION_BACKEND", "none"
        ).strip().lower()
        if speaker_identification_backend not in {"none", "titanet"}:
            raise ValueError(
                "CUSTOM_VOICE_SPEAKER_IDENTIFICATION_BACKEND must be one of: none, titanet"
            )
        return cls(
            input_sample_rate=int(os.getenv("CUSTOM_VOICE_INPUT_RATE", "16000")),
            input_frame_ms=int(os.getenv("CUSTOM_VOICE_VAD_FRAME_MS", "30")),
            transport_frame_ms=int(os.getenv("CUSTOM_VOICE_FRAME_MS", "20")),
            output_sample_rate=int(os.getenv("CUSTOM_VOICE_OUTPUT_RATE", "24000")),
            endpoint_silence_ms=int(os.getenv("CUSTOM_VOICE_ENDPOINT_MS", "720")),
            endpoint_candidate_silence_ms=int(os.getenv("CUSTOM_VOICE_ENDPOINT_CANDIDATE_MS", "280")),
            endpoint_fallback_silence_ms=int(
                os.getenv(
                    "CUSTOM_VOICE_ENDPOINT_FALLBACK_MS",
                    os.getenv("CUSTOM_VOICE_ENDPOINT_MS", "720"),
                )
            ),
            endpoint_hard_silence_ms=int(os.getenv("CUSTOM_VOICE_ENDPOINT_HARD_MS", "1100")),
            speech_start_frames=int(os.getenv("CUSTOM_VOICE_SPEECH_START_FRAMES", "3")),
            vad_mode=vad_backend,
            vad_backend=vad_backend,
            vad_threshold=float(os.getenv("CUSTOM_VOICE_VAD_THRESHOLD", "0.25")),
            vad_debug_logging=os.getenv("CUSTOM_VOICE_VAD_DEBUG", "0").strip().lower()
            in {"1", "true", "yes", "on"},
            vad_model_path=os.getenv("CUSTOM_VOICE_VAD_MODEL_PATH") or None,
            marblenet_model=os.getenv(
                "CUSTOM_VOICE_MARBLENET_MODEL",
                "nvidia/frame_vad_multilingual_marblenet_v2.0",
            ),
            marblenet_context_ms=int(os.getenv("CUSTOM_VOICE_MARBLENET_CONTEXT_MS", "1000")),
            marblenet_inference_interval_ms=int(
                os.getenv("CUSTOM_VOICE_MARBLENET_INTERVAL_MS", "100")
            ),
            vad_noise_multiplier=float(os.getenv("CUSTOM_VOICE_VAD_MULTIPLIER", "2.8")),
            vad_min_rms=float(os.getenv("CUSTOM_VOICE_VAD_MIN_RMS", "850")),
            minimum_utterance_rms=float(os.getenv("CUSTOM_VOICE_MIN_UTTERANCE_RMS", "0.012")),
            noise_suppression=noise_suppression,
            deep_noise_sample_rate=int(os.getenv("CUSTOM_VOICE_DEEP_NS_RATE", "48000")),
            rnnoise_library=os.getenv("CUSTOM_VOICE_RNNOISE_LIBRARY") or None,
            deepfilternet_model=os.getenv("CUSTOM_VOICE_DEEPFILTERNET_MODEL") or None,
            stt_model=os.getenv("CUSTOM_VOICE_STT_MODEL", "gpt-4o-mini-transcribe"),
            stt_backend=stt_backend,
            faster_whisper_model=os.getenv("CUSTOM_VOICE_FASTER_WHISPER_MODEL", "large-v3-turbo"),
            faster_whisper_device=os.getenv("CUSTOM_VOICE_FASTER_WHISPER_DEVICE", "auto"),
            faster_whisper_compute_type=os.getenv("CUSTOM_VOICE_FASTER_WHISPER_COMPUTE_TYPE", "default"),
            partial_stt_interval_ms=int(os.getenv("CUSTOM_VOICE_PARTIAL_STT_INTERVAL_MS", "600")),
            partial_stt_min_audio_ms=int(os.getenv("CUSTOM_VOICE_PARTIAL_STT_MIN_AUDIO_MS", "1200")),
            audio_receive_queue_frames=int(os.getenv("CUSTOM_VOICE_AUDIO_QUEUE_FRAMES", "200")),
            barge_in_confirmation_ms=int(os.getenv("CUSTOM_VOICE_BARGE_IN_CONFIRMATION_MS", "200")),
            llm_model=os.getenv("CUSTOM_VOICE_LLM_MODEL", "gpt-4.1-mini"),
            router_model=os.getenv("CUSTOM_VOICE_ROUTER_MODEL", "gpt-5-nano"),
            router_timeout_seconds=float(os.getenv("CUSTOM_VOICE_ROUTER_TIMEOUT", "2.0")),
            navigation_review_timeout_seconds=float(
                os.getenv("CUSTOM_VOICE_NAVIGATION_REVIEW_TIMEOUT", "2.0")
            ),
            navigation_review_join_timeout_ms=int(
                os.getenv("CUSTOM_VOICE_NAVIGATION_REVIEW_JOIN_MS", "250")
            ),
            llm_default_max_tokens=int(os.getenv("CUSTOM_VOICE_LLM_DEFAULT_MAX_TOKENS", "140")),
            llm_instruction_max_tokens=int(os.getenv("CUSTOM_VOICE_LLM_INSTRUCTION_MAX_TOKENS", "240")),
            llm_detailed_max_tokens=int(os.getenv("CUSTOM_VOICE_LLM_DETAILED_MAX_TOKENS", "360")),
            tts_model=os.getenv("CUSTOM_VOICE_TTS_MODEL", "gpt-4o-mini-tts-2025-12-15"),
            tts_voice=os.getenv("CUSTOM_VOICE_TTS_VOICE", "alloy"),
            tts_instructions=os.getenv(
                "CUSTOM_VOICE_TTS_INSTRUCTIONS",
                "자연스러운 한국어 대화체로, 문장 사이 호흡과 음량을 일정하게 유지해 말해 주세요.",
            ),
            tts_preferred_min_chars=int(os.getenv("CUSTOM_VOICE_TTS_MIN_CHARS", "24")),
            tts_target_chars=int(os.getenv("CUSTOM_VOICE_TTS_TARGET_CHARS", "64")),
            tts_maximum_chars=int(os.getenv("CUSTOM_VOICE_TTS_MAX_CHARS", "180")),
            tts_maximum_chunk_latency_ms=int(os.getenv("CUSTOM_VOICE_TTS_MAX_LATENCY_MS", "550")),
            tts_first_min_chars=int(os.getenv("CUSTOM_VOICE_TTS_FIRST_MIN_CHARS", "12")),
            tts_first_chunk_latency_ms=int(os.getenv("CUSTOM_VOICE_TTS_FIRST_LATENCY_MS", "380")),
            tts_max_inflight_requests=int(os.getenv("CUSTOM_VOICE_TTS_MAX_INFLIGHT", "2")),
            diarization_backend=diarization_backend,
            sortformer_model=os.getenv(
                "CUSTOM_VOICE_SORTFORMER_MODEL",
                "nvidia/diar_streaming_sortformer_4spk-v2.1",
            ),
            sortformer_activity_threshold=float(
                os.getenv("CUSTOM_VOICE_SORTFORMER_ACTIVITY_THRESHOLD", "0.5")
            ),
            speaker_identification_backend=speaker_identification_backend,
            titanet_model=os.getenv("CUSTOM_VOICE_TITANET_MODEL", "titanet_large"),
            speaker_embedding_dir=os.getenv("CUSTOM_VOICE_SPEAKER_EMBEDDING_DIR") or None,
            speaker_similarity_threshold=(
                float(os.environ["CUSTOM_VOICE_SPEAKER_SIMILARITY_THRESHOLD"])
                if os.getenv("CUSTOM_VOICE_SPEAKER_SIMILARITY_THRESHOLD")
                else None
            ),
            separation_backend=os.getenv("CUSTOM_VOICE_SEPARATION_BACKEND", "none").strip().lower(),
            provider_timeout_seconds=float(os.getenv("CUSTOM_VOICE_PROVIDER_TIMEOUT", "45")),
        )
