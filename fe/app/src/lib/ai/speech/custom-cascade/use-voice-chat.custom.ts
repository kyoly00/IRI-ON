"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type {
  UIMessageWithCompleted,
  VoiceChatOptions,
  VoiceChatSession,
} from "../index.js";
import { api, ws } from "../../../api.js";


/** Custom cascade WebSocket에서 브라우저로 보내는 protocol v1 event. */
type CustomVoiceEvent = {
  type: string;
  [key: string]: any;
};


/** 상대 URL도 WebSocket 생성자가 받을 수 있는 절대 ws/wss URL로 변환한다. */
function absoluteWebSocketUrl(path: string): string {
  const configured = ws(path);
  if (configured.startsWith("ws://") || configured.startsWith("wss://")) return configured;
  if (configured.startsWith("http://")) return configured.replace(/^http:/, "ws:");
  if (configured.startsWith("https://")) return configured.replace(/^https:/, "wss:");
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}${configured.startsWith("/") ? configured : `/${configured}`}`;
}


/** AudioWorklet block 사이의 fractional phase를 보존하는 16 kHz PCM resampler. */
class PCM16Downsampler {
  private readonly ratio: number;
  private position = 0;

  constructor(sourceRate: number, targetRate = 16_000) {
    this.ratio = sourceRate / targetRate;
  }

  push(input: Float32Array): ArrayBuffer {
    const samples: number[] = [];
    // position이 이전 128-sample block의 나머지를 기억해 장시간 sample-rate drift를 막는다.
    while (this.position < input.length) {
      const clamped = Math.max(-1, Math.min(1, input[Math.floor(this.position)] || 0));
      samples.push(clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff);
      this.position += this.ratio;
    }
    this.position -= input.length;
    return Int16Array.from(samples).buffer;
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
  const [isActive, setIsActive] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const [isUserSpeaking, setIsUserSpeaking] = useState(false);
  const [isAssistantSpeaking, setIsAssistantSpeaking] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [messages, setMessages] = useState<UIMessageWithCompleted[]>([]);
  const [error, setError] = useState<Error | null>(null);
  const [sessionInfo, setSessionInfo] = useState<Record<string, any> | null>(null);

  const socketRef = useRef<WebSocket | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const workletNodeRef = useRef<AudioWorkletNode | null>(null);
  const silentGainRef = useRef<GainNode | null>(null);
  const playbackSourcesRef = useRef<Set<AudioBufferSourceNode>>(new Set());
  const nextPlaybackTimeRef = useRef(0);
  const currentUserMessageIdRef = useRef<string | null>(null);
  const currentAssistantMessageIdRef = useRef<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const stopRef = useRef<() => Promise<void>>(async () => undefined);

  const userId = props?.userId ?? 2;
  const recipeId = props?.recipeId ?? 42;

  /** 조리 화면이 시작 버튼을 누르기 전에 새 backend route와 recipe 문맥을 검증한다. */
  useEffect(() => {
    let cancelled = false;
    setSessionInfo(null);
    fetch(api(`/custom-voice/session-info/${userId}/${recipeId}`), { credentials: "include" })
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
  }, [userId, recipeId]);

  /** 진행/예약된 모든 TTS source를 즉시 멈춰 barge-in 지연을 최소화한다. */
  const stopPlayback = useCallback(() => {
    playbackSourcesRef.current.forEach((source) => {
      try {
        source.stop();
      } catch {
        // 이미 자연 종료된 source의 InvalidStateError는 cleanup 과정에서 무시한다.
      }
    });
    playbackSourcesRef.current.clear();
    nextPlaybackTimeRef.current = audioContextRef.current?.currentTime ?? 0;
    setIsAssistantSpeaking(false);
  }, []);

  /** 서버가 보낸 raw PCM을 AudioBufferSource로 이어 붙여 gap 없는 재생 queue를 만든다. */
  const enqueuePlayback = useCallback((event: CustomVoiceEvent) => {
    const context = audioContextRef.current;
    if (!context || !event.audio) return;
    const samples = decodePCM16(event.audio);
    const sampleRate = Number(event.sample_rate) || 24_000;
    const buffer = context.createBuffer(1, samples.length, sampleRate);
    // getChannelData().set은 SharedArrayBuffer 가능성까지 포함한 typed-array 타입과 호환된다.
    buffer.getChannelData(0).set(samples);
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(context.destination);

    // 네트워크 jitter를 흡수할 작은 30 ms 선행 여유만 둔다.
    const startAt = Math.max(context.currentTime + 0.03, nextPlaybackTimeRef.current);
    nextPlaybackTimeRef.current = startAt + buffer.duration;
    playbackSourcesRef.current.add(source);
    setIsAssistantSpeaking(true);
    source.onended = () => {
      playbackSourcesRef.current.delete(source);
      if (playbackSourcesRef.current.size === 0) setIsAssistantSpeaking(false);
    };
    source.start(startAt);
  }, []);

  /** 서버 event를 기존 화면의 message/event 상태 계약으로 변환한다. */
  const handleServerEvent = useCallback((event: CustomVoiceEvent) => {
    switch (event.type) {
      case "session_ready":
        setIsActive(true);
        setIsListening(true);
        setIsLoading(false);
        socketRef.current?.send(JSON.stringify({ type: "generate_greeting" }));
        break;
      case "user_speech_started": {
        const id = crypto.randomUUID();
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
        setMessages((previous) => previous.map((message) => (
          message.id === id
            ? { ...message, parts: [{ type: "text", text: event.text || "" }], completed: true }
            : message
        )));
        currentUserMessageIdRef.current = null;
        break;
      }
      case "assistant_delta": {
        let id = currentAssistantMessageIdRef.current;
        if (!id) {
          id = crypto.randomUUID();
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
      case "playback_stop":
        stopPlayback();
        currentAssistantMessageIdRef.current = null;
        break;
      case "assistant_event": {
        const assistantEvent = event.event || {};
        if (assistantEvent.type === "theme") {
          document.documentElement.dataset.theme = assistantEvent.theme || "light";
        }
        if (assistantEvent.type === "open_url" && assistantEvent.url) {
          window.open(assistantEvent.url, "_blank", "noopener,noreferrer");
        }
        if (assistantEvent.type === "end_conversation") {
          void stopRef.current();
        }
        if (assistantEvent.type === "timer_start") {
          if (timerRef.current) clearTimeout(timerRef.current);
          timerRef.current = setTimeout(() => {
            socketRef.current?.send(JSON.stringify({
              type: "timer_complete",
              message: assistantEvent.message || `${assistantEvent.step}단계 타이머가 끝났어.`,
            }));
            props?.onAssistantEvent?.({
              type: "timer_complete",
              step: assistantEvent.step,
              time: assistantEvent.time,
              message: assistantEvent.message,
            });
          }, Number(assistantEvent.time) * 1000);
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
  }, [enqueuePlayback, props, stopPlayback]);

  /** 브라우저 내장 AudioWorklet으로 microphone Float32 frame을 main thread에 전달한다. */
  const prepareAudioCapture = useCallback(async () => {
    const mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
    const context = new AudioContext();
    await context.resume();
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
    const downsampler = new PCM16Downsampler(context.sampleRate);
    const silentGain = context.createGain();
    silentGain.gain.value = 0;
    source.connect(worklet);
    worklet.connect(silentGain);
    silentGain.connect(context.destination);
    worklet.port.onmessage = (message: MessageEvent<Float32Array>) => {
      const socket = socketRef.current;
      if (socket?.readyState === WebSocket.OPEN) {
        socket.send(downsampler.push(message.data));
      }
    };

    mediaStreamRef.current = mediaStream;
    audioContextRef.current = context;
    workletNodeRef.current = worklet;
    silentGainRef.current = silentGain;
  }, []);

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
      await prepareAudioCapture();
      const sessionId = crypto.randomUUID();
      const socket = new WebSocket(
        absoluteWebSocketUrl(`/custom-voice/ws/${userId}/${recipeId}?session_id=${encodeURIComponent(sessionId)}`),
      );
      socket.binaryType = "arraybuffer";
      socketRef.current = socket;
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
      socket.onclose = () => {
        console.info("[CustomVoice] WebSocket closed");
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
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = null;
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

  return {
    isActive,
    isListening,
    isUserSpeaking,
    isAssistantSpeaking,
    isLoading,
    messages,
    error,
    sessionInfo,
    start,
    stop,
    startListening,
    stopListening,
  };
}
