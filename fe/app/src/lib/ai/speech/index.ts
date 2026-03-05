import toolsConfig from "./open-ai/mcp-tools.config.json" with { type: "json" };

/**
 * UI에서 표시할 메시지 조각. OpenAI delta → Text 또는 MCP 툴 호출 UI로 구성된다.
 */
export type UIMessagePart =
  | {
    type: "text";
    text: string;
  }
  | {
    type: string;
    [key: string]: any;
  };

export type UIMessageWithCompleted = {
  id: string;
  role: "user" | "assistant";
  parts: UIMessagePart[];
  completed: boolean;
};

/**
 * FastAPI 브릿지(WebSocket)를 통해 왕복하는 이벤트 타입.
 *  - session_info  : 시스템 프롬프트/재료/타이머 설정 전달
 *  - video/timer   : 로컬 부가 기능 (영상 URL, 타이머 완료)
 *  - step_detected : N 단계 진입 안내
 */
export type AssistantBridgeEvent =
  | {
    type: "session_info";
    data: Record<string, unknown>;
  }
  | {
    type: "video";
    step: number;
    data: string;
  }
  | {
    type: "timer_complete";
    step: number;
    time: number;
    message: string;
  }
  | {
    type: "step_detected";
    step: number;
  }
  | {
    // catch-all (ACK 등)
    type: string;
    [key: string]: any;
  };


export interface VoiceChatSession {
  isActive: boolean;
  isListening: boolean;
  isUserSpeaking: boolean;
  isAssistantSpeaking: boolean;
  isLoading: boolean;
  messages: UIMessageWithCompleted[];
  error: Error | null;
  sessionInfo: Record<string, any> | null;
  start: () => Promise<void>;
  stop: () => Promise<void>;
  startListening: () => Promise<void>;
  stopListening: () => Promise<void>;
}

const OUTSOURCING_TOOLS = [
  {
    type: "mcp",
    server_label: "playwright",
    server_url: "http://localhost:8931/mcp",  // playwright mcp가 로컬 stdio라 `npx @playwright/mcp@latest --port 8931`로 서버 먼저 띄우기
    require_approval: "never",
  },
  {
    type: "mcp",
    server_label: "tavily-remote-mcp",
    server_url: "https://mcp.tavily.com/mcp",
    authorization: "Bearer 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",
    require_approval: "never",
  },
];

export type VoiceChatOptions = {
  model?: string;
  voice?: string;
  assistantWsUrl?: string; // 선택사항 (더 이상 필수 아님)
  instructions?: string;
  onAssistantEvent?: (event: AssistantBridgeEvent) => void;
  mcpServerUrl?: string;
  userId?: number; // 추가: 사용자 ID
  recipeId?: number; // 추가: 레시피 ID
};

export type VoiceChatHook = (props?: {
  [key: string]: any;
}) => VoiceChatSession;

export const DEFAULT_VOICE_TOOLS = toolsConfig.defaultVoiceTools;
export const MCP_TOOLS = toolsConfig.mcpTools ?? [];
export const MCP_TOOL_ENDPOINTS = toolsConfig.mcpToolEndpoints ?? [];

/**
 * OpenAI Realtime API에 전달할 모든 툴 통합
 */
export const ALL_REALTIME_TOOLS = [
  ...DEFAULT_VOICE_TOOLS,
  ...OUTSOURCING_TOOLS,
  ...MCP_TOOLS,
];