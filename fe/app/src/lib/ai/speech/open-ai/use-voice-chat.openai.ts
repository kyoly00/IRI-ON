"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  DEFAULT_VOICE_TOOLS,
  MCP_TOOL_ENDPOINTS,
  ALL_REALTIME_TOOLS,
  type AssistantBridgeEvent,  // ← type 키워드 추가
  type UIMessageWithCompleted,  // ← type 키워드 추가
  type VoiceChatOptions,  // ← type 키워드 추가
  type VoiceChatSession,  // ← type 키워드 추가
} from "..";
import {
  type OpenAIRealtimeServerEvent,
  type OpenAIRealtimeSession,
} from "./openai-realtime-event";
import { api } from "../../../api";

type Content =
  | {
    type: "text";
    text: string;
  }
  | {
    type: "tool-invocation";
    name: string;
    arguments: any;
    state: "call" | "result";
    toolCallId: string;
    result?: any;
  };

const createUIPart = (content: Content) => {
  if (content.type === "tool-invocation") {
    return {
      type: `tool-${content.name}`,
      input: content.arguments,
      state: "output-available",
      toolCallId: content.toolCallId,
      output: content.result,
    };
  }

  return {
    type: "text",
    text: content.text,
  };
};

const createUIMessage = (payload: {
  id?: string;
  role: "user" | "assistant";
  content: Content;
  completed?: boolean;
}): UIMessageWithCompleted => {
  const id = payload.id ?? generateUUID();
  return {
    id,
    role: payload.role,
    parts: [createUIPart(payload.content)],
    completed: payload.completed ?? false,
  };
};

/**
 * WebRTC + MCP 툴 호출 + FastAPI 브릿지를 하나로 묶는 훅.
 * 1) FastAPI WebSocket으로 시스템 프롬프트/부가 이벤트를 수신하고
 * 2) OpenAI Realtime 세션을 만들어 WebRTC를 협상한 뒤
 * 3) 데이터 채널 이벤트를 UI 메시지로 변환한다.
 */
export function useOpenAIVoiceChat(
  props?: VoiceChatOptions,
): VoiceChatSession {
  const { model = "gpt-realtime-mini", voice = "ash" } = props || {};
  const [isUserSpeaking, setIsUserSpeaking] = useState(false);
  const [isAssistantSpeaking, setIsAssistantSpeaking] = useState(false);
  const [isActive, setIsActive] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [messages, setMessages] = useState<UIMessageWithCompleted[]>([]);
  const [sessionInfo, setSessionInfo] = useState<Record<string, any> | null>(null);
  const [initialGreetingSent, setInitialGreetingSent] = useState(false);

  const peerConnection = useRef<RTCPeerConnection | null>(null);
  const dataChannel = useRef<RTCDataChannel | null>(null);
  const audioElement = useRef<HTMLAudioElement | null>(null);
  const audioStream = useRef<MediaStream | null>(null);
  const assistantSocket = useRef<WebSocket | null>(null);
  const bridgeBuffer = useRef<string>("");
  const tracks = useRef<RTCRtpSender[]>([]);

  // 타이머 및 단계 추적을 위한 ref 추가
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const currentStepRef = useRef<number>(1);

  // 대화 로깅을 위한 세션 ID ref
  const conversationLogSessionId = useRef<string | null>(null);

  // 대화 로깅 API 호출 함수들
  const startConversationLog = useCallback(async (systemPrompt?: string) => {
    const sessionId = generateUUID();
    conversationLogSessionId.current = sessionId;

    try {
      await fetch(api("/assistant/conversation-log/start"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          user_id: props?.userId,
          recipe_id: props?.recipeId,
          system_prompt: systemPrompt,
        }),
      });
      console.log("📝 [ConversationLog] 세션 시작:", sessionId);
    } catch (err) {
      console.error("❌ [ConversationLog] 세션 시작 실패:", err);
    }

    return sessionId;
  }, [props?.userId, props?.recipeId]);

  const logConversationEntry = useCallback(async (
    role: string,
    content: string,
    metadata?: Record<string, any>
  ) => {
    if (!conversationLogSessionId.current) return;

    try {
      await fetch(api("/assistant/conversation-log/entry"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: conversationLogSessionId.current,
          role,
          content,
          metadata,
        }),
      });
    } catch (err) {
      console.error("❌ [ConversationLog] 로그 기록 실패:", err);
    }
  }, []);

  const logToolCall = useCallback(async (
    toolName: string,
    args: Record<string, any>,
    callId: string
  ) => {
    if (!conversationLogSessionId.current) return;

    try {
      await fetch(api("/assistant/conversation-log/tool-call"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: conversationLogSessionId.current,
          tool_name: toolName,
          arguments: args,
          call_id: callId,
        }),
      });
    } catch (err) {
      console.error("❌ [ConversationLog] 도구 호출 로그 실패:", err);
    }
  }, []);

  const logToolResult = useCallback(async (
    toolName: string,
    result: any,
    callId: string
  ) => {
    if (!conversationLogSessionId.current) return;

    try {
      await fetch(api("/assistant/conversation-log/tool-result"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: conversationLogSessionId.current,
          tool_name: toolName,
          result,
          call_id: callId,
        }),
      });
    } catch (err) {
      console.error("❌ [ConversationLog] 도구 결과 로그 실패:", err);
    }
  }, []);

  // 누적 토큰 사용량 추적
  const totalTokenUsage = useRef<{
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
    input_text_tokens: number;
    input_audio_tokens: number;
    output_text_tokens: number;
    output_audio_tokens: number;
  }>({
    input_tokens: 0,
    output_tokens: 0,
    total_tokens: 0,
    input_text_tokens: 0,
    input_audio_tokens: 0,
    output_text_tokens: 0,
    output_audio_tokens: 0,
  });

  // 토큰 사용량 업데이트
  const updateTokenUsage = useCallback((usage: {
    input_tokens?: number;
    output_tokens?: number;
    total_tokens?: number;
    input_token_details?: { text_tokens?: number; audio_tokens?: number };
    output_token_details?: { text_tokens?: number; audio_tokens?: number };
  }) => {
    if (!usage) return;

    totalTokenUsage.current = {
      input_tokens: totalTokenUsage.current.input_tokens + (usage.input_tokens || 0),
      output_tokens: totalTokenUsage.current.output_tokens + (usage.output_tokens || 0),
      total_tokens: totalTokenUsage.current.total_tokens + (usage.total_tokens || 0),
      input_text_tokens: totalTokenUsage.current.input_text_tokens + (usage.input_token_details?.text_tokens || 0),
      input_audio_tokens: totalTokenUsage.current.input_audio_tokens + (usage.input_token_details?.audio_tokens || 0),
      output_text_tokens: totalTokenUsage.current.output_text_tokens + (usage.output_token_details?.text_tokens || 0),
      output_audio_tokens: totalTokenUsage.current.output_audio_tokens + (usage.output_token_details?.audio_tokens || 0),
    };

    console.log("💰 [Token Usage] 업데이트:", {
      this_response: usage,
      cumulative: totalTokenUsage.current,
    });
  }, []);

  const endConversationLog = useCallback(async () => {
    if (!conversationLogSessionId.current) return;

    try {
      await fetch(api("/assistant/conversation-log/end"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: conversationLogSessionId.current,
          token_usage: totalTokenUsage.current,
        }),
      });
      console.log("📝 [ConversationLog] 세션 종료:", conversationLogSessionId.current);
      console.log("📊 [Token Usage] 최종 사용량:", totalTokenUsage.current);

      // 토큰 사용량 초기화
      totalTokenUsage.current = {
        input_tokens: 0,
        output_tokens: 0,
        total_tokens: 0,
        input_text_tokens: 0,
        input_audio_tokens: 0,
        output_text_tokens: 0,
        output_audio_tokens: 0,
      };
      conversationLogSessionId.current = null;
    } catch (err) {
      console.error("❌ [ConversationLog] 세션 종료 실패:", err);
    }
  }, []);


  const startListening = useCallback(async () => {
    try {
      if (!audioStream.current) {
        audioStream.current = await navigator.mediaDevices.getUserMedia({
          audio: true,
        });
      }
      if (tracks.current.length) {
        const micTrack = audioStream.current.getAudioTracks()[0];
        tracks.current.forEach((sender) => {
          sender.replaceTrack(micTrack);
        });
      }
      setIsListening(true);
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    }
  }, []);

  const stopListening = useCallback(async () => {
    try {
      if (audioStream.current) {
        audioStream.current.getTracks().forEach((track) => track.stop());
        audioStream.current = null;
      }
      if (tracks.current.length) {
        const placeholderTrack = createEmptyAudioTrack();
        tracks.current.forEach((sender) => {
          sender.replaceTrack(placeholderTrack);
        });
      }
      setIsListening(false);
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    }
  }, []);

  // 세션 정보 조회 (컴포넌트 마운트 시)
  const loadSessionInfo = useCallback(async (): Promise<any> => {
    if (sessionInfo) return; // 이미 로드된 경우 스킵

    const userId = props?.userId ?? 2;
    const recipeId = props?.recipeId ?? 42;

    try {
      // api() 함수 사용으로 통일
      const response = await fetch(api(`/assistant/session-info/${userId}/${recipeId}`), {
        credentials: 'include',
      });
      if (!response.ok) {
        throw new Error("Failed to fetch session info");
      }
      const data = await response.json();
      setSessionInfo(data);
      return data;
    } catch (err) {
      console.error("Failed to load session info:", err);
      setError(err instanceof Error ? err : new Error(String(err)));
      throw err;
    }
  }, [props?.userId, props?.recipeId, sessionInfo]);

  // 컴포넌트 마운트 시 세션 정보 로드
  useEffect(() => {
    if (props?.userId && props?.recipeId && !sessionInfo) {
      loadSessionInfo();
    }
  }, [props?.userId, props?.recipeId, sessionInfo, loadSessionInfo]);

  // Step 2. FastAPI REST 엔드포인트에서 OpenAI Realtime 에페메럴 세션을 발급받는다.
  const createSession = useCallback(async (): Promise<OpenAIRealtimeSession> => {
    // 세션 정보가 없으면 먼저 로드 (await로 대기)
    // 1) 항상 sessionInfo를 로딩/확보
    let info = sessionInfo;
    if (!info) {
      info = await loadSessionInfo();  // 여기서 반환값 사용
    }

    // MCP 서버 설정 구성
    const mcpServers = buildMCPServersConfig();

    const response = await fetch(api("/assistant/openai-realtime/session"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model,
        voice,
        instructions: props?.instructions ?? info.system_prompt ?? "",
        tools: ALL_REALTIME_TOOLS,
      }),
    });

    if (!response.ok) {
      throw new Error(await response.text());
    }

    const session = (await response.json()) as OpenAIRealtimeSession;
    if ((session as any).error) {
      throw new Error((session as any).error.message);
    }
    return session;
  }, [model, voice, props?.instructions, sessionInfo, loadSessionInfo]);

  const updateUIMessage = useCallback(
    (
      id: string,
      action:
        | Partial<UIMessageWithCompleted>
        | ((message: UIMessageWithCompleted) => Partial<UIMessageWithCompleted>),
    ) => {
      setMessages((prev) => {
        const target = prev.find((m) => m.id === id);
        if (!target) return prev;
        const next = typeof action === "function" ? action(target) : action;
        if (!next) return prev;
        return prev.map((message) =>
          message.id === id ? { ...message, ...next } : message,
        );
      });
    },
    [],
  );

  // 브라우저 → FastAPI로 텍스트 델타를 전달해 로컬 부가 로직을 유지한다.
  const broadcastAssistantOutput = useCallback(
    (payload: { text: string; isFinal: boolean }) => {
      const socket = assistantSocket.current;
      if (!socket || socket.readyState !== WebSocket.OPEN) {
        console.warn("⚠️ [broadcastAssistantOutput] WebSocket not ready", {
          socket: !!socket,
          readyState: socket?.readyState,
        });
        return;
      }
      console.log("📤 [broadcastAssistantOutput]", {
        text: payload.text,
        isFinal: payload.isFinal,
        textLength: payload.text.length,
      });
      socket.send(
        JSON.stringify({
          type: "assistant_output",
          data: payload.text,
          is_final: payload.isFinal,
        }),
      );
    },
    [],
  );


  // stop 함수를 먼저 정의하고, clientFunctionCall에서 사용  
  const stopRef = useRef<(() => Promise<void>) | null>(null);

  // 통화를 종료하면서 WebRTC/오디오 리소스를 해제한다.
  const stop = useCallback(async () => {
    try {
      // 대화 로그 세션 종료
      await endConversationLog();

      if (dataChannel.current) {
        dataChannel.current.close();
        dataChannel.current = null;
      }
      if (peerConnection.current) {
        peerConnection.current.close();
        peerConnection.current = null;
      }
      tracks.current = [];
      stopListening();
      setIsActive(false);
      setIsListening(false);
      setIsLoading(false);
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    }
  }, [stopListening, endConversationLog]);

  // stop을 ref에 저장
  useEffect(() => {
    stopRef.current = stop;
  }, [stop]);


  // OpenAI → 클라이언트 MCP 호출을 수행하고 그 결과를 다시 데이터 채널로 전송
  // MCP 도구 ID 파싱 함수 (HTML 파일 참고)
  const extractMCPToolId = (toolId: string) => {
    const [serverName, ...toolName] = toolId.split("_");
    return { serverName, toolName: toolName.join("_") };
  };

  // LLM에게 텍스트 메시지를 전송하는 함수
  const sendTextToLLM = useCallback((text: string, isSystemMessage: boolean = false) => {
    if (!dataChannel.current || dataChannel.current.readyState !== "open") {
      console.warn("⚠️ [sendTextToLLM] Data channel not ready");
      return;
    }

    const itemId = generateUUID();

    // 시스템 메시지인 경우 (초기 인사 등) - 사용자 입력 없이 응답 생성만 요청
    if (isSystemMessage) {
      console.log("🎤 [sendTextToLLM] Triggering initial response from LLM");
      const responseEvent = {
        type: "response.create",
        response: {
          instructions: text,
        },
      };
      dataChannel.current.send(JSON.stringify(responseEvent));
      return;
    }

    // 1. 일반 사용자 메시지 - 먼저 메시지 아이템 생성
    const createEvent = {
      type: "conversation.item.create",
      item: {
        type: "message",
        role: "user",
        content: [
          {
            type: "input_text",
            text: text,
          },
        ],
      },
    };

    console.log("📤 [sendTextToLLM] Sending message to LLM:", text);
    dataChannel.current.send(JSON.stringify(createEvent));

    // 2. 응답 생성을 요청 (이게 없으면 LLM이 응답하지 않음)
    const responseEvent = {
      type: "response.create",
    };

    // 약간의 지연 후 response.create 전송 (메시지가 처리될 시간을 줌)
    setTimeout(() => {
      console.log("📤 [sendTextToLLM] Requesting response from LLM");
      dataChannel.current?.send(JSON.stringify(responseEvent));
    }, 100);
  }, []);

  // 타이머 시작 함수
  const startTimer = useCallback((step: number, duration: number) => {
    // 기존 타이머가 있으면 취소
    if (timerRef.current) {
      clearTimeout(timerRef.current);
    }

    currentStepRef.current = step;

    console.log(`⏰ [Timer] 시작: Step ${step}, ${duration}초`);

    // 타이머 완료 시 LLM에 메시지 전송
    timerRef.current = setTimeout(() => {
      const timerMessage = `타이머가 끝났어. ${step}단계가 완료되었으니 다음 단계로 진행할 수 있어. 사용자에게 "다 했어"라고 말하라고 안내해줘.`;

      console.log(`⏰ [Timer] 완료: Step ${step}`);
      sendTextToLLM(timerMessage);

      // 타이머 완료 이벤트 전송 (선택사항)
      props?.onAssistantEvent?.({
        type: "timer_complete",
        step: step,
        time: duration,
        message: timerMessage,
      });

      timerRef.current = null;
    }, duration * 1000);
  }, [sendTextToLLM, props?.onAssistantEvent]);

  // OpenAI → 클라이언트 MCP 호출을 수행하고 그 결과를 다시 데이터 채널로 전송
  const clientFunctionCall = useCallback(
    async ({
      callId,
      toolName,
      args,
      id,
    }: {
      callId: string;
      toolName: string;
      args: string;
      id: string;
    }) => {
      console.log("🔧 [MCP Tool Call]", { toolName, callId, args });
      let toolResult: any = "success";
      setIsListening(false);
      const toolArgs = args ? JSON.parse(args) : {};

      // 도구 호출 로그 기록
      await logToolCall(toolName, toolArgs, callId);

      const builtInTool = DEFAULT_VOICE_TOOLS.find(
        (tool) => tool.name === toolName,
      );

      try {
        if (builtInTool) {
          console.log("✅ [Built-in Tool]", toolName);
          switch (toolName) {
            case "changeBrowserTheme":
              document.documentElement.dataset.theme = toolArgs?.theme ?? "light";
              break;
            case "endConversation":
              await stop();
              setMessages([]);
              break;
            default:
              break;
          }
        } else {
          // MCP 도구 호출 - HTML 파일의 callMcpTool 방식 참고
          const toolId = extractMCPToolId(toolName);

          // MCP 서버 URL이 설정되어 있는 경우 (props 또는 환경변수에서 가져올 수 있음)
          const mcpServerUrl = props?.mcpServerUrl;

          if (mcpServerUrl) {
            // HTML 파일의 callMcpTool 방식과 동일하게 호출
            const response = await fetch(mcpServerUrl, {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
              },
              body: JSON.stringify({
                serverName: toolId.serverName,
                toolName: toolId.toolName,
                arguments: toolArgs,
              }),
            });

            if (!response.ok) {
              throw new Error(`MCP Server Error: ${response.status} ${response.statusText}`);
            }

            toolResult = await response.json();
          } else {
            // 기존 방식: 엔드포인트를 통한 호출
            const endpoint = MCP_TOOL_ENDPOINTS.find(
              (tool) => tool.name === toolName || tool.id?.endsWith(toolName),
            );

            if (!endpoint) {
              console.error("❌ [MCP Tool] Unknown tool:", toolName);
              toolResult = {
                error: `Unknown tool: ${toolName}`,
              };
            } else {
              console.log("📍 [MCP Tool] Calling endpoint:", endpoint.endpoint);
              const url = endpoint.endpoint.replace("{toolName}", toolName);
              const fullUrl = api(url);
              console.log("📡 [MCP Tool] Full URL:", fullUrl);

              // send_video_url인 경우 최근 assistant 텍스트와 recipe_id 추가
              let requestBody = { ...toolArgs };
              if (toolName === "send_video_url") {
                if (recentAssistantTextRef.current) {
                  requestBody.text = recentAssistantTextRef.current;
                  console.log("📺 [Video] Assistant 텍스트 포함:", recentAssistantTextRef.current.substring(0, 50) + "...");
                }
                // recipe_id 추가
                if (props?.recipeId) {
                  requestBody.recipe_id = props.recipeId;
                  console.log("📺 [Video] Recipe ID 추가:", props.recipeId);
                }
              }

              const response = await fetch(fullUrl, {
                method: endpoint.method ?? "POST",
                headers: {
                  "Content-Type": "application/json",
                },
                body: JSON.stringify(requestBody),
              });
              if (!response.ok) {
                console.error("❌ [MCP Tool] Response error:", response.status, response.statusText);
                toolResult = {
                  error: `HTTP ${response.status}: ${response.statusText}`,
                };
              } else {
                toolResult = await response.json();
                console.log("✅ [MCP Tool] Result:", toolResult);

                // start_timer인 경우 클라이언트에서 타이머 시작
                if (toolName === "start_timer" && toolResult.success) {
                  const step = toolResult.step;
                  const duration = toolResult.duration;
                  startTimer(step, duration);
                }

                // send_video_url인 경우 비디오 이벤트 전송
                if (toolName === "send_video_url" && toolResult.success && toolResult.url) {
                  const step = toolResult.step;
                  const videoUrl = toolResult.url;
                  console.log(`🎥 [Video] 비디오 URL 수신: step=${step}, url=${videoUrl}`);
                  props?.onAssistantEvent?.({
                    type: "video",
                    step: step,
                    data: videoUrl,
                  });
                }
              }
            }
          }
        }
      } catch (err) {
        console.error("❌ [MCP Tool] Exception:", err);
        toolResult = err instanceof Error ? err.message : String(err);
      } finally {
        startListening();
      }

      // 도구 결과 로그 기록
      await logToolResult(toolName, toolResult, callId);

      const resultText = JSON.stringify(toolResult).slice(0, 15000);
      const event = {
        type: "conversation.item.create",
        previous_item_id: id,
        item: {
          type: "function_call_output",
          call_id: callId,
          output: resultText,
        },
      };

      updateUIMessage(id, (prev) => {
        const part = prev.parts.find((p) => p.type === `tool-${toolName}`);
        if (!part) return prev;
        return {
          parts: [
            {
              ...part,
              state: "output-available",
              output: toolResult,
              toolCallId: callId,
            },
          ],
        };
      });

      dataChannel.current?.send(JSON.stringify(event));
      dataChannel.current?.send(JSON.stringify({ type: "response.create" }));
    },
    [startListening, stop, updateUIMessage, props?.mcpServerUrl, props?.onAssistantEvent, startTimer, props?.recipeId, logToolCall, logToolResult],
  );

  const handleServerEvent = useCallback(
    (event: OpenAIRealtimeServerEvent) => {
      switch (event.type) {
        case "input_audio_buffer.speech_started": {
          const message = createUIMessage({
            role: "user",
            id: event.item_id,
            content: {
              type: "text",
              text: "",
            },
          });
          setIsUserSpeaking(true);
          setMessages((prev) => [...prev, message]);
          break;
        }
        case "input_audio_buffer.committed": {
          updateUIMessage(event.item_id, {
            completed: true,
          });
          break;
        }
        case "conversation.item.input_audio_transcription.completed": {
          updateUIMessage(event.item_id, {
            parts: [
              {
                type: "text",
                text: event.transcript || "...speaking",
              },
            ],
            completed: true,
          });
          // 사용자 음성 인식 결과 로그 저장
          if (event.transcript) {
            logConversationEntry("user", event.transcript);
          }
          break;
        }
        case "response.audio_transcript.delta": {
          setIsAssistantSpeaking(true);
          bridgeBuffer.current += event.delta;
          recentAssistantTextRef.current += event.delta; // 텍스트 누적
          broadcastAssistantOutput({ text: event.delta, isFinal: false });
          setMessages((prev) => {
            const existing = prev.findLast((m) => m.id === event.item_id);
            if (existing) {
              return prev.map((message) =>
                message.id === event.item_id
                  ? {
                    ...message,
                    parts: [
                      {
                        type: "text",
                        text: `${(message.parts[0] as any).text ?? ""}${event.delta}`,
                      },
                    ],
                  }
                  : message,
              );
            }
            return [
              ...prev,
              createUIMessage({
                role: "assistant",
                id: event.item_id,
                content: {
                  type: "text",
                  text: event.delta,
                },
                completed: false,
              }),
            ];
          });
          break;
        }
        case "response.audio_transcript.done": {
          const finalText = event.transcript ?? bridgeBuffer.current;
          recentAssistantTextRef.current = finalText; // 최종 텍스트 저장
          broadcastAssistantOutput({
            text: finalText,
            isFinal: true,
          });
          bridgeBuffer.current = "";
          updateUIMessage(event.item_id, (prev) => {
            const textPart = prev.parts.find((p) => p.type === "text");
            if (!textPart) return prev;
            (textPart as any).text = event.transcript || (textPart as any).text || "";
            return {
              ...prev,
              completed: true,
            };
          });
          // 어시스턴트 응답 완료 로그 저장
          if (finalText) {
            logConversationEntry("assistant", finalText, { is_final: true });
          }
          break;
        }
        case "response.function_call_arguments.done": {
          const message = createUIMessage({
            role: "assistant",
            id: event.item_id,
            content: {
              type: "tool-invocation",
              name: event.name,
              arguments: JSON.parse(event.arguments),
              state: "call",
              toolCallId: event.call_id,
            },
            completed: true,
          });
          setMessages((prev) => [...prev, message]);
          clientFunctionCall({
            callId: event.call_id,
            toolName: event.name,
            args: event.arguments,
            id: event.item_id,
          });
          break;
        }
        case "input_audio_buffer.speech_stopped":
          setIsUserSpeaking(false);
          break;
        case "output_audio_buffer.stopped":
          setIsAssistantSpeaking(false);
          break;
        case "response.done": {
          // 토큰 사용량 추적
          if (event.response?.usage) {
            updateTokenUsage(event.response.usage);
            // 토큰 사용량을 로그에 기록
            logConversationEntry("token_usage", JSON.stringify(event.response.usage), {
              response_id: event.response.id,
              status: event.response.status,
            });
          }
          break;
        }
      }
    },
    [broadcastAssistantOutput, clientFunctionCall, updateUIMessage, logConversationEntry, updateTokenUsage],
  );

  // Step 3. 브라우저 ↔ OpenAI WebRTC 협상을 시작한다.
  const start = useCallback(async () => {
    if (isActive || isLoading) return;
    setIsLoading(true);
    setError(null);
    setMessages([]);
    try {
      const session = await createSession();
      const sessionToken = session.client_secret.value;

      // 대화 로그 세션 시작 (시스템 프롬프트 포함)
      await startConversationLog(sessionInfo?.system_prompt);

      const pc = new RTCPeerConnection();
      if (!audioElement.current) {
        audioElement.current = document.createElement("audio");
      }
      audioElement.current.autoplay = true;
      pc.ontrack = (e) => {
        if (audioElement.current) {
          audioElement.current.srcObject = e.streams[0];
        }
      };
      if (!audioStream.current) {
        audioStream.current = await navigator.mediaDevices.getUserMedia({
          audio: true,
        });
      }
      tracks.current = [];
      audioStream.current.getTracks().forEach((track) => {
        const sender = pc.addTrack(track, audioStream.current!);
        if (sender) tracks.current.push(sender);
      });

      const dc = pc.createDataChannel("oai-events");
      dataChannel.current = dc;
      dc.addEventListener("message", async (e) => {
        try {
          const event = JSON.parse(e.data) as OpenAIRealtimeServerEvent;
          handleServerEvent(event);
        } catch (err) {
          console.error({ data: e.data, error: err });
        }
      });
      dc.addEventListener("open", () => {
        setIsActive(true);
        setIsListening(true);
        setIsLoading(false);

        const menuName = sessionInfo?.user_profile?.menu || "요리";
        const promptForAssistant =
          `지금부터 너는 먼저 인사하고, 자기소개하고, 손 씻으라고 안내해. `;

        // UI에는 굳이 안 찍고, 모델에게만 user 발화로 보냄
        setTimeout(() => {
          sendTextToLLM(promptForAssistant, true);  // user 역할로 전송
          setInitialGreetingSent(true);
        }, 500);
      });

      dc.addEventListener("close", () => {
        setIsActive(false);
        setIsListening(false);
        setIsLoading(false);
        setInitialGreetingSent(false);
      });
      dc.addEventListener("error", (errorEvent) => {
        setError(
          errorEvent instanceof Error
            ? errorEvent
            : new Error(String(errorEvent)),
        );
        setIsActive(false);
        setIsListening(false);
      });
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      const sdpResponse = await fetch(`https://api.openai.com/v1/realtime`, {
        method: "POST",
        body: offer.sdp,
        headers: {
          Authorization: `Bearer ${sessionToken}`,
          "Content-Type": "application/sdp",
        },
      });
      const answer: RTCSessionDescriptionInit = {
        type: "answer",
        sdp: await sdpResponse.text(),
      };
      await pc.setRemoteDescription(answer);
      peerConnection.current = pc;
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
      setIsActive(false);
      setIsListening(false);
      setIsLoading(false);
    }
  }, [createSession, handleServerEvent, isActive, isLoading, startConversationLog, sessionInfo]);


  // Step 1. FastAPI WebSocket 연결: 시스템 프롬프트·타이머 이벤트·영상 URL 수신
  useEffect(() => {
    return () => {
      // stop이 함수인지 확인하고 호출
      if (typeof stop === 'function') {
        stop().catch((err) => {
          console.warn('Error during cleanup stop:', err);
        });
      }
      // assistantSocket 관련 코드 제거
    };
  }, [stop]);

  // WebSocket 관련 useEffect 제거
  // useEffect(() => {
  //   if (!props?.assistantWsUrl) return;
  //   ...
  // }, [props?.assistantWsUrl, props?.onAssistantEvent]);
  // 이 부분 전체 제거

  function createEmptyAudioTrack(): MediaStreamTrack {
    const audioContext = new AudioContext();
    const destination = audioContext.createMediaStreamDestination();
    return destination.stream.getAudioTracks()[0];
  }

  // MCP 서버 설정 타입 추가
  type MCPServerConfig = {
    [serverName: string]: {
      command: string;
      args: string[];
    };
  };

  // MCP 서버 설정을 직접 구성하는 함수
  // UseOpenAIVoiceChat 훅이 “음성 Realtime 세션 전체를 관리하는 최상위 엔트리 포인트”라서, 음성 세션 + MCP 서버 묶음을 한 번에 구성할 수 있도록 하기 위해 훅 내부에 구성 함수를 추가
  const buildMCPServersConfig = (): MCPServerConfig => {
    // HTML 파일의 형태를 참고하여 MCP 서버 설정 구성
    return {
      "microsoft-playwright-mcp": {
        command: "npx",
        args: ["@playwright/mcp@latest"]
      },
      // 필요에 따라 추가 MCP 서버 설정
      // "chef-tools": {
      //   command: "node",
      //   args: ["./path/to/chef-tools-mcp"]
      // }
    };
  };

  // assistant의 최근 출력 텍스트를 저장하는 ref 추가
  const recentAssistantTextRef = useRef<string>("");

  // handleAssistantText에서 텍스트 저장
  const handleAssistantText = useCallback((text: string, isFinal: boolean, recipeId: number) => {
    if (isFinal) {
      recentAssistantTextRef.current = text;
    } else {
      recentAssistantTextRef.current += text;
    }
  }, []);

  // cleanup에서 타이머 정리
  useEffect(() => {
    return () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }
    };
  }, []);

  return {
    isActive,
    isUserSpeaking,
    isAssistantSpeaking,
    isListening,
    isLoading,
    error,
    messages,
    sessionInfo,
    start,
    stop,
    startListening,
    stopListening,
  };
}

function generateUUID(): string {
  return crypto.randomUUID();
}
