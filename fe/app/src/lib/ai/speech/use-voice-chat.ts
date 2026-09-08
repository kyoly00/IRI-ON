import { useCustomCascadeVoiceChat } from "./custom-cascade/use-voice-chat.custom.js";
import { useOpenAIVoiceChat } from "./open-ai/use-voice-chat.openai.js";


/**
 * 음성 runtime 선택 변수.
 * - realtime: 기존 OpenAI Realtime WebRTC 구현
 * - custom_cascade: 새 PCM WebSocket + STT/LLM/TTS 분리 구현
 */
export const VOICE_IMPLEMENTATION = (
  import.meta.env.VITE_VOICE_IMPLEMENTATION ?? "realtime"
).toLowerCase();

// 빌드 시 고정되는 함수 alias라 React hook을 조건부 호출하지 않는다.
export const useVoiceChat = VOICE_IMPLEMENTATION === "custom_cascade"
  ? useCustomCascadeVoiceChat
  : useOpenAIVoiceChat;
