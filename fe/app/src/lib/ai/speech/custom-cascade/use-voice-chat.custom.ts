"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type {
  UIMessageWithCompleted,
  VoiceChatOptions,
  VoiceChatSession,
} from "../index.js";
import { api, ws } from "../../../api.js";
import { requestMicrophone } from "../microphone.js";


/** Custom cascade WebSocket에서 브라우저로 보내는 protocol v1 event. */
type CustomVoiceEvent = {
  type: string;
  [key: string]: any;
};

type PlaybackChunk = {
  source: AudioBufferSourceNode;
  startAt: number;
  duration: number;
  samples: Float32Array;
  sampleRate: number;
};

type PausedPlaybackChunk = Pick<PlaybackChunk, "samples" | "sampleRate">;


/** 상대 URL도 WebSocket 생성자가 받을 수 있는 절대 ws/wss URL로 변환한다. */
/**
 * 브라우저가 Crypto.randomUUID를 제공하면 그대로 사용하고, 없으면 UUID v4를 만든다.
 * 일부 모바일 브라우저와 HTTP 개발 환경에서는 crypto 객체가 있어도 randomUUID만 빠져 있다.
 * getRandomValues도 없는 매우 오래된 환경의 난수는 trace/UI 식별에만 사용하며 인증에는 쓰지 않는다.
 */
function createBrowserUUID(): string {
  const webCrypto = globalThis.crypto;

  const bytes = new Uint8Array(16);
  if (typeof webCrypto?.getRandomValues === "function") {
    webCrypto.getRandomValues(bytes);
  } else {
    for (let index = 0; index < bytes.length; index += 1) {
      bytes[index] = Math.floor(Math.random() * 256);
    }
  }

  // UUID v4 version/variant bit를 설정해 backend의 UUID parser와 호환한다.
  bytes[6] = ((bytes[6] ?? 0) & 0x0f) | 0x40;
  bytes[8] = ((bytes[8] ?? 0) & 0x3f) | 0x80;
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}


function absoluteWebSocketUrl(path: string): string {
  const configured = ws(path);
  if (configured.startsWith("ws://") || configured.startsWith("wss://")) return configured;
  if (configured.startsWith("http://")) return configured.replace(/^http:/, "ws:");
  if (configured.startsWith("https://")) return configured.replace(/^https:/, "wss:");
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}${configured.startsWith("/") ? configured : `/${configured}`}`;
}


/** WebSocket path의 user id를 JWT 서명 검증 결과와 일치시키기 위해 sub만 읽는다. */
function readJwtUserId(token: string | null): number | null {
  if (!token) return null;
  try {
    const encoded = token.split(".")[1];
    if (!encoded) return null;
    const normalized = encoded.replace(/-/g, "+").replace(/_/g, "/");
    const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "=");
    const subject = JSON.parse(window.atob(padded))?.sub;
    const value = Number(subject);
    return Number.isSafeInteger(value) && value > 0 ? value : null;
  } catch {
    return null;
  }
}


/**
 * AudioContext가 요청 sample-rate를 제공하지 못할 때 사용하는 streaming windowed-sinc resampler.
 * downsampling 시 cutoff를 target Nyquist 아래로 제한해 단순 sample skip의 aliasing을 피한다.
 */
class StreamingSincResampler {
  private readonly ratio: number;
  private readonly cutoff: number;
  private readonly halfWidth = 16;
  private buffer = new Float32Array(16);
  private position = 16;

  constructor(private readonly sourceRate: number, private readonly targetRate: number) {
    this.ratio = sourceRate / targetRate;
    this.cutoff = Math.min(1, targetRate / sourceRate) * 0.92;
  }

  push(input: Float32Array): Float32Array {
    if (this.sourceRate === this.targetRate) return input;
    const combined = new Float32Array(this.buffer.length + input.length);
    combined.set(this.buffer);
    combined.set(input, this.buffer.length);
    const output: number[] = [];
    while (this.position + this.halfWidth < combined.length) {
      let weighted = 0;
      let weightSum = 0;
      const left = Math.floor(this.position) - this.halfWidth + 1;
      const right = Math.floor(this.position) + this.halfWidth;
      for (let index = left; index <= right; index += 1) {
        if (index < 0 || index >= combined.length) continue;
        const distance = this.position - index;
        const x = Math.PI * distance * this.cutoff;
        const sinc = Math.abs(x) < 1e-8 ? 1 : Math.sin(x) / x;
        const window = 0.5 + 0.5 * Math.cos(Math.PI * distance / this.halfWidth);
        const weight = this.cutoff * sinc * window;
        weighted += combined[index]! * weight;
        weightSum += weight;
      }
      output.push(weightSum ? weighted / weightSum : 0);
      this.position += this.ratio;
    }
    const discard = Math.max(0, Math.floor(this.position) - this.halfWidth);
    this.buffer = combined.slice(discard);
    this.position -= discard;
    return Float32Array.from(output);
  }
}


/** Resampled audio를 정확한 20 ms PCM16 WebSocket frame으로 묶는 ring buffer. */
class PCM16FrameEncoder {
  private readonly resampler: StreamingSincResampler;
  private readonly frameSamples: number;
  private pending: number[] = [];

  constructor(sourceRate: number, targetRate: number, frameMs: number) {
    this.resampler = new StreamingSincResampler(sourceRate, targetRate);
    this.frameSamples = Math.round(targetRate * frameMs / 1000);
  }

  push(input: Float32Array): ArrayBuffer[] {
    this.pending.push(...this.resampler.push(input));
    const frames: ArrayBuffer[] = [];
    while (this.pending.length >= this.frameSamples) {
      const values = this.pending.splice(0, this.frameSamples);
      const pcm = new Int16Array(this.frameSamples);
      values.forEach((value, index) => {
        const clamped = Math.max(-1, Math.min(1, value || 0));
        pcm[index] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
      });
      frames.push(pcm.buffer);
    }
    return frames;
  }
}


/** base64 signed 16-bit PCM을 Web Audio용 float sample로 복원한다. */
function decodePCM16(base64Audio: string): Float32Array {
  const binary = window.atob(base64Audio);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  const view = new DataView(bytes.buffer);
  const output = new Float32Array(Math.floor(bytes.length / 2));
  for (let index = 0; index < output.length; index += 1) {
    output[index] = view.getInt16(index * 2, true) / 32768;
  }
  return output;
}


/**
 * 브라우저 PCM ↔ FastAPI custom cascade를 연결하는 독립 음성 훅.
 * 기존 OpenAI Realtime 훅과 같은 VoiceChatSession 계약을 반환해 화면 교체를 최소화한다.
 */
export function useCustomCascadeVoiceChat(props?: VoiceChatOptions): VoiceChatSession {
  // 0/미설정은 adaptive mode다. 실제 trace에서 150 ms 고정 버퍼가 모든 응답 초반에
  // 한 번씩 underrun을 냈으므로 첫 재생은 300 ms에서 시작하고 관측 jitter로 조정한다.
  const configuredFixedJitterMs = Number(import.meta.env.VITE_CUSTOM_VOICE_FIXED_JITTER_MS || 0);
  const adaptiveJitter = !(configuredFixedJitterMs > 0);
  const [isActive, setIsActive] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const [isUserSpeaking, setIsUserSpeaking] = useState(false);
  const [isAssistantSpeaking, setIsAssistantSpeaking] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [isResponseHeld, setIsResponseHeld] = useState(false);
  const [messages, setMessages] = useState<UIMessageWithCompleted[]>([]);
  const [error, setError] = useState<Error | null>(null);
  const [sessionInfo, setSessionInfo] = useState<Record<string, any> | null>(null);
  const [authenticatedUserId, setAuthenticatedUserId] = useState<number | null>(null);
  const [authenticationResolved, setAuthenticationResolved] = useState(false);

  const socketRef = useRef<WebSocket | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const playbackAudioContextRef = useRef<AudioContext | null>(null);
  const workletNodeRef = useRef<AudioWorkletNode | null>(null);
  const silentGainRef = useRef<GainNode | null>(null);
  const playbackSourcesRef = useRef<Set<AudioBufferSourceNode>>(new Set());
  const playbackChunksRef = useRef<PlaybackChunk[]>([]);
  const pausedPlaybackRef = useRef<PausedPlaybackChunk[]>([]);
  const softPausedPlaybackRef = useRef(false);
  const softPausePlayedMsRef = useRef(0);
  const nextPlaybackTimeRef = useRef(0);
  const activeResponseIdRef = useRef<string | null>(null);
  const activeGenerationIdRef = useRef<number>(-1);
  const expectedAudioSequenceRef = useRef(0);
  const targetJitterSecondsRef = useRef(
    adaptiveJitter ? 0.30 : Math.min(0.5, Math.max(0.02, configuredFixedJitterMs / 1000)),
  );
  const adaptiveJitterFloorSecondsRef = useRef(0.30);
  const lastAudioArrivalMsRef = useRef<number | null>(null);
  const jitterMsRef = useRef(0);
  const underrunCountRef = useRef(0);
  const captureMetricsRef = useRef({ samples: 0, sumSquares: 0, peak: 0, blocks: 0 });
  const currentUserMessageIdRef = useRef<string | null>(null);
  const currentAssistantMessageIdRef = useRef<string | null>(null);
  const timerRefs = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());
  const pendingNavigationIdRef = useRef<string | null>(null);
  const stopRef = useRef<() => Promise<void>>(async () => undefined);

  const messagesRef = useRef<UIMessageWithCompleted[]>([]);
  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  const propsRef = useRef(props);
  useEffect(() => {
    propsRef.current = props;
  }, [props]);

  useEffect(() => {
    const tokenUserId = readJwtUserId(localStorage.getItem("access_token"));
    setAuthenticatedUserId(tokenUserId);
    setAuthenticationResolved(true);
  }, []);

  const userId = authenticatedUserId ?? props?.userId ?? 0;
  const recipeId = props?.recipeId ?? 42;

  /** AI 도구 이동과 사용자의 수동 이동 모두 실제 UI 적용 결과를 서버에 확인시킨다. */
  useEffect(() => {
    const socket = socketRef.current;
    if (!isActive || socket?.readyState !== WebSocket.OPEN) return;
    socket.send(JSON.stringify({
      type: "step_changed",
      current_step: props?.currentStep ?? 0,
      step_text: props?.stepContext?.text ?? "",
      navigation_id: pendingNavigationIdRef.current,
      source: "cooking_ui",
    }));
    pendingNavigationIdRef.current = null;
  }, [isActive, props?.currentStep, props?.stepContext?.text]);

  /** 조리 화면이 시작 버튼을 누르기 전에 새 backend route와 recipe 문맥을 검증한다. */
  useEffect(() => {
    if (!authenticationResolved) return undefined;
    if (!authenticatedUserId) {
      setSessionInfo(null);
      setError(new Error("로그인 토큰에서 사용자 정보를 확인할 수 없습니다. 다시 로그인해 주세요."));
      return undefined;
    }
    let cancelled = false;
    setSessionInfo(null);
    fetch(api(`/custom-voice/session-info/${userId}/${recipeId}`))
      .then(async (response) => {
        if (!response.ok) throw new Error(await response.text());
        return response.json();
      })
      .then((data) => {
        if (!cancelled) setSessionInfo(data);
      })
      .catch((reason) => {
        if (!cancelled) setError(reason instanceof Error ? reason : new Error(String(reason)));
      });
    return () => {
      cancelled = true;
    };
  }, [authenticatedUserId, authenticationResolved, userId, recipeId]);

  /** 진행/예약된 모든 TTS source를 즉시 멈추고 실제 청취 시간을 역송신하여 State Rollback을 수행한다. */
  const stopPlayback = useCallback(() => {
    const context = playbackAudioContextRef.current;
    const now = context?.currentTime ?? 0;

    let totalPlayedSec = 0;
    for (const chunk of playbackChunksRef.current) {
      if (now > chunk.startAt) {
        const played = Math.min(chunk.duration, now - chunk.startAt);
        totalPlayedSec += Math.max(0, played);
      }
    }
    const playedMs = Math.round(totalPlayedSec * 1000) + softPausePlayedMsRef.current;

    playbackSourcesRef.current.forEach((source) => {
      try {
        source.stop();
      } catch {
        // 이미 자연 종료된 source의 InvalidStateError는 cleanup 과정에서 무시한다.
      }
    });
    playbackSourcesRef.current.clear();
    playbackChunksRef.current = [];
    pausedPlaybackRef.current = [];
    softPausedPlaybackRef.current = false;
    softPausePlayedMsRef.current = 0;
    nextPlaybackTimeRef.current = now;
    setIsAssistantSpeaking(false);

    if (playedMs > 0 && socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(
        JSON.stringify({
          type: "playback_progress",
          played_duration_ms: playedMs,
          interrupted: true,
        })
      );
    }
  }, []);

  /** Barge-in 후보에서는 남은 PCM을 보존한 채 재생만 일시 정지한다. */
  const softPausePlayback = useCallback(() => {
    if (softPausedPlaybackRef.current) return;
    const context = playbackAudioContextRef.current;
    const now = context?.currentTime ?? 0;
    const remaining: PausedPlaybackChunk[] = [];
    let playedSeconds = 0;
    for (const chunk of playbackChunksRef.current) {
      const elapsed = Math.max(0, now - chunk.startAt);
      const consumed = Math.min(chunk.duration, elapsed);
      playedSeconds += consumed;
      const offset = Math.min(chunk.samples.length, Math.max(0, Math.floor(consumed * chunk.sampleRate)));
      if (offset < chunk.samples.length) {
        remaining.push({ samples: chunk.samples.slice(offset), sampleRate: chunk.sampleRate });
      }
      try { chunk.source.stop(); } catch { /* already ended */ }
    }
    playbackSourcesRef.current.clear();
    playbackChunksRef.current = [];
    pausedPlaybackRef.current = remaining;
    softPausePlayedMsRef.current += Math.round(playedSeconds * 1000);
    nextPlaybackTimeRef.current = now;
    softPausedPlaybackRef.current = true;
    setIsAssistantSpeaking(false);
  }, []);

  /** 짧은 VAD 오탐이면 보존한 PCM을 새 AudioBufferSource로 다시 예약한다. */
  const resumeSoftPausedPlayback = useCallback(() => {
    const context = playbackAudioContextRef.current;
    if (!context || !softPausedPlaybackRef.current) return;
    const pending = pausedPlaybackRef.current;
    pausedPlaybackRef.current = [];
    softPausedPlaybackRef.current = false;
    softPausePlayedMsRef.current = 0;
    let startAt = context.currentTime + targetJitterSecondsRef.current;
    for (const chunk of pending) {
      const buffer = context.createBuffer(1, chunk.samples.length, chunk.sampleRate);
      buffer.getChannelData(0).set(chunk.samples);
      const source = context.createBufferSource();
      source.buffer = buffer;
      source.connect(context.destination);
      const record: PlaybackChunk = { source, startAt, duration: buffer.duration, samples: chunk.samples, sampleRate: chunk.sampleRate };
      playbackSourcesRef.current.add(source);
      playbackChunksRef.current.push(record);
      source.onended = () => {
        playbackSourcesRef.current.delete(source);
        if (playbackSourcesRef.current.size === 0) {
          setIsAssistantSpeaking(false);
          playbackChunksRef.current = [];
        }
      };
      source.start(startAt);
      startAt += buffer.duration;
    }
    nextPlaybackTimeRef.current = startAt;
    setIsAssistantSpeaking(pending.length > 0);
  }, []);

  /** 서버가 보낸 raw PCM을 AudioBufferSource로 이어 붙여 gap 없는 재생 queue를 만든다. */
  const enqueuePlayback = useCallback((event: CustomVoiceEvent) => {
    const context = playbackAudioContextRef.current;
    if (!context || !event.audio) return;
    if (
      event.response_id !== activeResponseIdRef.current
      || Number(event.generation_id) !== activeGenerationIdRef.current
    ) {
      console.info("[CustomVoice] stale audio chunk dropped", {
        responseId: event.response_id,
        generationId: event.generation_id,
        sequence: event.sequence_number,
      });
      return;
    }
    const sequence = Number(event.sequence_number);
    if (!Number.isSafeInteger(sequence) || sequence !== expectedAudioSequenceRef.current) {
      console.warn("[CustomVoice] out-of-order audio chunk dropped", {
        expected: expectedAudioSequenceRef.current,
        received: sequence,
      });
      return;
    }
    expectedAudioSequenceRef.current += 1;

    const arrivalMs = performance.now();
    const previousArrival = lastAudioArrivalMsRef.current;
    if (previousArrival !== null) {
      const arrivalGap = arrivalMs - previousArrival;
      const expectedGap = Number(event.duration_ms) || 0;
      const deviation = Math.abs(arrivalGap - expectedGap);
      jitterMsRef.current = jitterMsRef.current * 0.85 + deviation * 0.15;
      if (adaptiveJitter) {
        // provider의 첫 PCM burst 뒤 공백까지 흡수하도록 250 ms 아래로 내리지 않는다.
        // 안정적인 구간에서는 jitter 관측치에 맞춰 줄고, underrun 시에는 아래에서 즉시 증가한다.
        targetJitterSecondsRef.current = Math.min(
          0.5,
          Math.max(
            adaptiveJitterFloorSecondsRef.current,
            (200 + jitterMsRef.current * 3) / 1000,
          ),
        );
      }
    }
    lastAudioArrivalMsRef.current = arrivalMs;

    const samples = decodePCM16(event.audio);
    const sampleRate = Number(event.sample_rate) || 24_000;
    if (softPausedPlaybackRef.current) {
      pausedPlaybackRef.current.push({ samples, sampleRate });
      return;
    }
    const buffer = context.createBuffer(1, samples.length, sampleRate);
    // getChannelData().set은 SharedArrayBuffer 가능성까지 포함한 typed-array 타입과 호환된다.
    buffer.getChannelData(0).set(samples);
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(context.destination);

    // 50 ms 안팎의 PCM 조각이 네트워크에서 늦게 도착해도 재생 사이에 무음 틈이
    // 생기지 않도록 첫/underrun 조각만 150 ms 버퍼링하고, 대기열이 있으면 정확히 이어 붙인다.
    const queuedSeconds = Math.max(0, nextPlaybackTimeRef.current - context.currentTime);
    const hasQueuedAudio = queuedSeconds > 0;
    if (!hasQueuedAudio && sequence > 0) {
      underrunCountRef.current += 1;
      if (adaptiveJitter) {
        adaptiveJitterFloorSecondsRef.current = Math.min(
          0.5,
          adaptiveJitterFloorSecondsRef.current + 0.06,
        );
        targetJitterSecondsRef.current = Math.max(
          targetJitterSecondsRef.current,
          adaptiveJitterFloorSecondsRef.current,
        );
      }
      console.warn("[CustomVoice] playback buffer underrun", {
        sequence,
        underruns: underrunCountRef.current,
        targetJitterMs: Math.round(targetJitterSecondsRef.current * 1000),
      });
    }
    const startAt = hasQueuedAudio
      ? nextPlaybackTimeRef.current
      : context.currentTime + targetJitterSecondsRef.current;
    nextPlaybackTimeRef.current = startAt + buffer.duration;
    playbackSourcesRef.current.add(source);
    playbackChunksRef.current.push({ source, startAt, duration: buffer.duration, samples, sampleRate });
    setIsAssistantSpeaking(true);
    source.onended = () => {
      playbackSourcesRef.current.delete(source);
      if (playbackSourcesRef.current.size === 0) {
        setIsAssistantSpeaking(false);
        playbackChunksRef.current = [];
        if (socketRef.current?.readyState === WebSocket.OPEN) {
          socketRef.current.send(JSON.stringify({
            type: "playback_finished",
            response_id: event.response_id,
            generation_id: event.generation_id,
          }));
        }
      }
    };
    source.start(startAt);

    if (sequence === 0 || sequence % 20 === 0) {
      socketRef.current?.send(JSON.stringify({
        type: "playback_metrics",
        response_id: event.response_id,
        generation_id: event.generation_id,
        sequence_number: sequence,
        queued_ms: Math.round(queuedSeconds * 1000),
        scheduled_wait_ms: Math.round((startAt - context.currentTime) * 1000),
        jitter_ms: Math.round(jitterMsRef.current),
        target_jitter_ms: Math.round(targetJitterSecondsRef.current * 1000),
        jitter_mode: adaptiveJitter ? "adaptive" : "fixed",
        underruns: underrunCountRef.current,
        browser_received_at_ms: Date.now(),
        scheduled_playback_at_ms: Date.now() + Math.round((startAt - context.currentTime) * 1000),
      }));
    }
  }, [adaptiveJitter]);

  /** 서버 event를 기존 화면의 message/event 상태 계약으로 변환한다. */
  const handleServerEvent = useCallback((event: CustomVoiceEvent) => {
    switch (event.type) {
      case "session_ready": {
        setIsActive(true);
        setIsListening(true);
        setIsLoading(false);
        const currentStep = propsRef.current?.currentStep ?? 0;
        const stepText = propsRef.current?.stepContext?.text ?? "";
        const recentHistory = messagesRef.current.slice(-6).map((m) => ({
          role: m.role,
          text: (m.parts[0] as any)?.text || "",
        })).filter((m) => m.text);

        socketRef.current?.send(JSON.stringify({
          type: "resume_session",
          current_step: currentStep,
          step_text: stepText,
          history: recentHistory,
        }));
        const context = audioContextRef.current;
        const track = mediaStreamRef.current?.getAudioTracks()[0];
        console.info("[CustomVoice] audio capture ready", {
          contextState: context?.state,
          contextSampleRate: context?.sampleRate,
          trackEnabled: track?.enabled,
          trackMuted: track?.muted,
          trackSettings: track?.getSettings(),
        });
        break;
      }
      case "response_started":
        if (
          adaptiveJitter
          && activeResponseIdRef.current
          && underrunCountRef.current === 0
        ) {
          // 끊김 없는 응답이 이어지면 체감 지연을 천천히 되돌리되 250 ms 아래로 내리지 않는다.
          adaptiveJitterFloorSecondsRef.current = Math.max(
            0.25,
            adaptiveJitterFloorSecondsRef.current - 0.01,
          );
        }
        stopPlayback();
        activeResponseIdRef.current = String(event.response_id || "");
        activeGenerationIdRef.current = Number(event.generation_id);
        expectedAudioSequenceRef.current = 0;
        lastAudioArrivalMsRef.current = null;
        jitterMsRef.current = 0;
        underrunCountRef.current = 0;
        if (adaptiveJitter) {
          targetJitterSecondsRef.current = adaptiveJitterFloorSecondsRef.current;
        }
        break;
      case "user_speech_started": {
        // VAD 시작만으로는 스피커 잔향도 잡힐 수 있다. 서버가 추가 음성 확인 뒤
        // playback_stop을 보낼 때만 실제 재생 큐를 비운다.
        const id = createBrowserUUID();
        currentUserMessageIdRef.current = id;
        setIsUserSpeaking(true);
        setMessages((previous) => [
          ...previous,
          { id, role: "user", parts: [{ type: "text", text: "" }], completed: false },
        ]);
        break;
      }
      case "user_speech_ended":
        setIsUserSpeaking(false);
        break;
      case "user_transcript": {
        const id = currentUserMessageIdRef.current;
        if (!id) break;
        const isFinal = event.final !== false;
        setMessages((previous) => previous.map((message) => (
          message.id === id
            ? { ...message, parts: [{ type: "text", text: event.text || "" }], completed: isFinal }
            : message
        )));
        if (isFinal) currentUserMessageIdRef.current = null;
        break;
      }
      case "assistant_delta": {
        let id = currentAssistantMessageIdRef.current;
        if (!id) {
          id = createBrowserUUID();
          currentAssistantMessageIdRef.current = id;
          const newMessage: UIMessageWithCompleted = {
            id,
            role: "assistant",
            parts: [{ type: "text", text: event.text || "" }],
            completed: false,
          };
          setMessages((previous) => [...previous, newMessage]);
        } else {
          setMessages((previous) => previous.map((message) => (
            message.id === id
              ? {
                ...message,
                parts: [{ type: "text", text: `${(message.parts[0] as any)?.text || ""}${event.text || ""}` }],
              }
              : message
          )));
        }
        break;
      }
      case "assistant_done": {
        const id = currentAssistantMessageIdRef.current;
        if (id) {
          setMessages((previous) => previous.map((message) => (
            message.id === id ? { ...message, completed: true } : message
          )));
        }
        currentAssistantMessageIdRef.current = null;
        break;
      }
      case "audio_chunk":
        enqueuePlayback(event);
        break;
      case "audio_input_ready":
        console.info("[CustomVoice] server received microphone audio", event);
        break;
      case "playback_stop":
        stopPlayback();
        activeResponseIdRef.current = null;
        activeGenerationIdRef.current = Math.max(
          activeGenerationIdRef.current,
          Number(event.generation_id) || activeGenerationIdRef.current,
        );
        currentAssistantMessageIdRef.current = null;
        break;
      case "response_hold_started":
        stopPlayback();
        setIsResponseHeld(true);
        setIsAssistantSpeaking(false);
        propsRef.current?.onAssistantEvent?.({ type: "response_hold_started" });
        break;
      case "release_confirmation_required":
        propsRef.current?.onAssistantEvent?.({
          type: "release_confirmation_required",
          message: event.message,
        });
        break;
      case "response_hold_released":
        setIsResponseHeld(false);
        propsRef.current?.onAssistantEvent?.({ type: "response_hold_released" });
        break;
      case "response_suppressed":
        propsRef.current?.onAssistantEvent?.({ type: "response_suppressed", reason: event.reason });
        break;
      case "assistant_event": {
        const assistantEvent = event.event || {};
        if (assistantEvent.type === "theme") {
          document.documentElement.dataset.theme = assistantEvent.theme || "light";
        }
        if (assistantEvent.type === "end_conversation") {
          void stopRef.current();
        }
        if (assistantEvent.type === "timer_start") {
          const timerId = String(assistantEvent.timer_id || `${assistantEvent.step}:${Date.now()}`);
          const timer = setTimeout(() => {
            timerRefs.current.delete(timerId);
            socketRef.current?.send(JSON.stringify({
              type: "timer_complete",
              timer_id: timerId,
              step: assistantEvent.step,
              duration: assistantEvent.time,
              label: assistantEvent.label,
              message: assistantEvent.message || `${assistantEvent.step}단계 타이머가 끝났어.`,
            }));
            props?.onAssistantEvent?.({
              type: "timer_complete",
              timer_id: timerId,
              step: assistantEvent.step,
              time: assistantEvent.time,
              label: assistantEvent.label,
              message: assistantEvent.message,
            });
          }, Number(assistantEvent.time) * 1000);
          timerRefs.current.set(timerId, timer);
        }
        if (assistantEvent.type === "navigate_step") {
          pendingNavigationIdRef.current = String(assistantEvent.navigation_id || "") || null;
        }
        props?.onAssistantEvent?.(assistantEvent);
        break;
      }
      case "error":
        // 서버 콘솔과 브라우저 DevTools 양쪽에서 같은 provider 오류를 확인할 수 있게 남긴다.
        console.error("[CustomVoice] server error", event);
        setError(new Error(event.message || "Custom voice pipeline error"));
        setIsLoading(false);
        break;
      default:
        break;
    }
  }, [adaptiveJitter, enqueuePlayback, props, resumeSoftPausedPlayback, softPausePlayback, stopPlayback]);

  /** 브라우저 내장 AudioWorklet으로 microphone Float32 frame을 main thread에 전달한다. */
  const prepareAudioCapture = useCallback(async () => {
    if (!sessionInfo) throw new Error("Custom voice session configuration is not loaded yet");
    // localhost 이외의 HTTP origin에서는 브라우저가 mediaDevices 자체를 노출하지 않는다.
    // 원래 TypeError 대신 해결 방법이 포함된 오류를 표시하고 권한 요청 전에 중단한다.
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      throw new Error(
        `마이크 사용에는 secure context가 필요합니다. 모바일 Chrome의 ` +
        `chrome://flags/#unsafely-treat-insecure-origin-as-secure에 ${window.location.origin}을 ` +
        `정확히 등록하고 Chrome을 다시 시작하거나 HTTPS로 접속해 주세요.`,
      );
    }
    const noiseMode = String(sessionInfo.noise_suppression || "browser");
    const constraints = sessionInfo.browser_audio_constraints || {};
    const targetSampleRate = Number(sessionInfo.input_sample_rate) || (
      noiseMode === "rnnoise" || noiseMode === "deepfilternet" ? 48_000 : 16_000
    );
    const frameMs = Number(sessionInfo.input_frame_ms) || 20;
    const mediaStream = await requestMicrophone({
      audio: {
        channelCount: 1,
        // Deep NS와 browser NS를 겹치지 않는다. Deep mode는 AEC만 browser에 남긴다.
        echoCancellation: Boolean(constraints.echo_cancellation ?? noiseMode !== "none"),
        noiseSuppression: Boolean(constraints.noise_suppression ?? noiseMode === "browser"),
        autoGainControl: Boolean(constraints.auto_gain_control ?? noiseMode !== "none"),
        sampleRate: targetSampleRate,
      },
    });
    const context = new AudioContext({ sampleRate: targetSampleRate });
    await context.resume();
    const playbackContext = new AudioContext();
    await playbackContext.resume();
    captureMetricsRef.current = { samples: 0, sumSquares: 0, peak: 0, blocks: 0 };
    const workletSource = `
      class CustomPCMProcessor extends AudioWorkletProcessor {
        process(inputs) {
          const channel = inputs[0] && inputs[0][0];
          if (channel) {
            const copy = new Float32Array(channel);
            this.port.postMessage(copy, [copy.buffer]);
          }
          return true;
        }
      }
      registerProcessor("custom-pcm-processor", CustomPCMProcessor);
    `;
    const moduleUrl = URL.createObjectURL(new Blob([workletSource], { type: "text/javascript" }));
    try {
      await context.audioWorklet.addModule(moduleUrl);
    } finally {
      URL.revokeObjectURL(moduleUrl);
    }

    const source = context.createMediaStreamSource(mediaStream);
    const worklet = new AudioWorkletNode(context, "custom-pcm-processor");
    const frameEncoder = new PCM16FrameEncoder(context.sampleRate, targetSampleRate, frameMs);
    const silentGain = context.createGain();
    silentGain.gain.value = 0;
    source.connect(worklet);
    worklet.connect(silentGain);
    silentGain.connect(context.destination);
    worklet.port.onmessage = (message: MessageEvent<Float32Array>) => {
      const socket = socketRef.current;
      if (socket?.readyState === WebSocket.OPEN) {
        const values = message.data;
        let sumSquares = 0;
        let peak = 0;
        for (let index = 0; index < values.length; index += 1) {
          const value = values[index] || 0;
          sumSquares += value * value;
          peak = Math.max(peak, Math.abs(value));
        }
        const metrics = captureMetricsRef.current;
        metrics.samples += values.length;
        metrics.sumSquares += sumSquares;
        metrics.peak = Math.max(metrics.peak, peak);
        metrics.blocks += 1;
        // 약 1초마다 capture 원본의 수치만 보낸다. 음성 PCM 자체는 기록하지 않는다.
        if (metrics.blocks >= Math.max(1, Math.ceil(context.sampleRate / Math.max(1, values.length)))) {
          socket.send(JSON.stringify({
            type: "capture_metrics",
            context_sample_rate: context.sampleRate,
            target_sample_rate: targetSampleRate,
            samples: metrics.samples,
            rms: Math.sqrt(metrics.sumSquares / Math.max(1, metrics.samples)),
            peak: metrics.peak,
            track_settings: mediaStream.getAudioTracks()[0]?.getSettings() || {},
          }));
          captureMetricsRef.current = { samples: 0, sumSquares: 0, peak: 0, blocks: 0 };
        }
        frameEncoder.push(message.data).forEach((frame) => socket.send(frame));
      }
    };

    mediaStreamRef.current = mediaStream;
    audioContextRef.current = context;
    playbackAudioContextRef.current = playbackContext;
    workletNodeRef.current = worklet;
    silentGainRef.current = silentGain;
  }, [sessionInfo]);

  /** microphone track을 유지한 채 mute를 토글해 빠르게 듣기를 재개한다. */
  const startListening = useCallback(async () => {
    mediaStreamRef.current?.getAudioTracks().forEach((track) => { track.enabled = true; });
    setIsListening(true);
  }, []);

  const stopListening = useCallback(async () => {
    mediaStreamRef.current?.getAudioTracks().forEach((track) => { track.enabled = false; });
    setIsListening(false);
  }, []);

  /** 사용자 클릭 한 번에서 audio 권한과 WebSocket을 함께 시작한다. */
  const start = useCallback(async () => {
    if (isActive || isLoading) return;
    setIsLoading(true);
    setError(null);
    setMessages([]);
    try {
      const token = localStorage.getItem("access_token");
      const tokenUserId = readJwtUserId(token);
      if (!token || !tokenUserId) {
        throw new Error("로그인 토큰이 없거나 만료 형식입니다. 다시 로그인해 주세요.");
      }
      if (tokenUserId !== userId) {
        throw new Error("로그인 사용자와 음성 세션 사용자가 일치하지 않습니다.");
      }
      await prepareAudioCapture();
      const sessionId = createBrowserUUID();
      const socket = new WebSocket(
        absoluteWebSocketUrl(`/custom-voice/ws/${userId}/${recipeId}?session_id=${encodeURIComponent(sessionId)}`),
      );
      socket.binaryType = "arraybuffer";
      socketRef.current = socket;
      socket.onopen = () => {
        socket.send(JSON.stringify({ type: "auth", token }));
      };
      socket.onmessage = (message) => {
        try {
          handleServerEvent(JSON.parse(String(message.data)));
        } catch (reason) {
          setError(reason instanceof Error ? reason : new Error(String(reason)));
        }
      };
      socket.onerror = () => {
        console.error("[CustomVoice] WebSocket connection error");
        setError(new Error("Custom voice WebSocket connection failed"));
        setIsLoading(false);
        // handshake 실패로 onclose만 발생해도 microphone이 남지 않도록 전체 cleanup을 시작한다.
        void stopRef.current();
      };
      socket.onclose = (event) => {
        console.info("[CustomVoice] WebSocket closed", {
          code: event.code,
          reason: event.reason,
          wasClean: event.wasClean,
        });
        if (event.code !== 1000 && event.code !== 1005) {
          setError(new Error(
            `Custom voice 연결이 종료되었습니다 (${event.code})${event.reason ? `: ${event.reason}` : ""}`,
          ));
        }
        setIsActive(false);
        setIsListening(false);
        setIsUserSpeaking(false);
        setIsLoading(false);
        // 서버 주도 종료/네트워크 실패에서도 microphone과 AudioContext를 회수한다.
        void stopRef.current();
      };
    } catch (reason) {
      setError(reason instanceof Error ? reason : new Error(String(reason)));
      setIsLoading(false);
      await stopRef.current();
    }
  }, [handleServerEvent, isActive, isLoading, prepareAudioCapture, recipeId, userId]);

  /** 모든 browser media 자원을 해제하고 서버에는 trace 저장 기회를 준다. */
  const stop = useCallback(async () => {
    const socket = socketRef.current;
    if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "stop" }));
    socket?.close();
    socketRef.current = null;
    for (const timer of timerRefs.current.values()) clearTimeout(timer);
    timerRefs.current.clear();
    pendingNavigationIdRef.current = null;
    stopPlayback();
    workletNodeRef.current?.disconnect();
    silentGainRef.current?.disconnect();
    workletNodeRef.current = null;
    silentGainRef.current = null;
    mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
    mediaStreamRef.current = null;
    const context = audioContextRef.current;
    audioContextRef.current = null;
    if (context && context.state !== "closed") await context.close();
    const playbackContext = playbackAudioContextRef.current;
    playbackAudioContextRef.current = null;
    if (playbackContext && playbackContext.state !== "closed") await playbackContext.close();
    setIsActive(false);
    setIsListening(false);
    setIsUserSpeaking(false);
    setIsLoading(false);
  }, [stopPlayback]);

  useEffect(() => {
    stopRef.current = stop;
  }, [stop]);

  // 화면 unmount에서는 비동기 완료를 기다릴 수 없으므로 cleanup을 시작만 한다.
  useEffect(() => () => {
    void stopRef.current();
  }, []);

  const holdResponses = useCallback(() => {
    socketRef.current?.send(JSON.stringify({ type: "response_hold" }));
  }, []);

  const releaseResponses = useCallback(() => {
    socketRef.current?.send(JSON.stringify({ type: "response_release" }));
  }, []);

  return {
    isActive,
    isListening,
    isUserSpeaking,
    isAssistantSpeaking,
    isLoading,
    isResponseHeld,
    messages,
    error,
    sessionInfo,
    start,
    stop,
    startListening,
    stopListening,
    holdResponses,
    releaseResponses,
  };
}
