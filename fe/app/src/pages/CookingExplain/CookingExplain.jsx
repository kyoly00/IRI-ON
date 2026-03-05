import React, { useState, useRef, useMemo, useCallback } from "react";
import YouTube from "react-youtube";
import { FaPlay, FaStop } from "react-icons/fa";
import topLogo from "../../assets/top_logo.png";
import CookingIcon from "../../assets/cookingexplain.png";
import { ws } from "../../lib/api";
import { useOpenAIVoiceChat } from "../../lib/ai/speech/open-ai/use-voice-chat.openai";
import "./CookingExplain.css";

/* ===== 1) 단계별 유튜브 하드코딩 목록 ===== */
const steps = [
  { step: 1, url: "https://youtu.be/x-J0U3svqZU" },
  { step: 2, url: "https://youtu.be/cwIo1ieglgo" },
  { step: 3, url: "https://youtu.be/odD06ItB7Rk" },
  { step: 4, url: "https://youtu.be/jNH9IzAgnwU" },
  { step: 5, url: "https://youtu.be/aUSBS7VdfXk" },
  { step: 6, url: "https://youtu.be/ahPBHBw62vo" },
  { step: 7, url: "https://youtu.be/AhfnZKMuZzM" },
  { step: 8, url: "https://youtu.be/4ih3XWJOJ4o" },
  { step: 9, url: "https://youtu.be/UhX3TCmqPUU" },
  { step: 10, url: "https://youtu.be/8QCO6QuQH74" },
  { step: 11, url: "https://youtu.be/jd6PlSQ5jSo" },
  { step: 12, url: "https://youtu.be/3BMkcroT1Kg" },
  { step: 13, url: "https://youtu.be/jBQ-4fFq9XI" },
  { step: 14, url: "https://youtu.be/ZugD66Ga2pw" },
  { step: 15, url: "https://youtu.be/XXZWKvkm6Jw" },
  { step: 16, url: "https://youtu.be/RbCpZU89eM8" },
  { step: 17, url: "https://youtu.be/xJSoEW3iKHI" },
  { step: 18, url: "https://youtu.be/Hn4NRKE-ppI" },
];

/* 유튜브 ID 추출 */
const getVideoId = (url) => {
  try {
    const u = new URL((url || "").trim());
    if (u.hostname === "youtu.be") return u.pathname.slice(1);
    return u.searchParams.get("v") || "";
  } catch {
    return "";
  }
};

const DEMO_USER_ID = 5; // TODO: 실제 로그인 사용자 정보로 교체
const DEMO_RECIPE_ID = 42;

export default function CookingExplain() {
  /* ===== 2) 영상 상태 ===== */
  const [currentStep, setCurrentStep] = useState(0); // 0-index
  const [blocked, setBlocked] = useState(new Set()); // 임베딩 금지 스텝 기록
  const playerRef = useRef(null);

  const { videoId, link } = useMemo(() => {
    const url = steps[currentStep]?.url ?? steps[0].url;
    return { videoId: getVideoId(url), link: url };
  }, [currentStep]);

  /* ===== 3) 유튜브 옵션/핸들러 ===== */
  const ytOpts = {
    width: "100%",
    height: "315",
    host: "https://www.youtube.com",
    playerVars: { autoplay: 1, controls: 1, mute: 1, playsinline: 1 },
  };

  const onReady = (e) => {
    playerRef.current = e.target;
    try { e.target.playVideo(); } catch { }
  };

  const onError = (e) => {
    const code = e.data;
    // 101/150: 임베딩 금지 → 다음 재생 가능한 스텝으로 스킵
    if (code === 101 || code === 150) {
      setBlocked((prev) => new Set(prev).add(currentStep));
      const next = findNextPlayable(currentStep);
      if (next !== currentStep) setCurrentStep(next);
    }
  };

  const findNextPlayable = (startIdx) => {
    for (let i = startIdx + 1; i < steps.length; i++) {
      if (!blocked.has(i)) return i;
    }
    return startIdx;
  };

  const handlePrev = () => setCurrentStep((s) => Math.max(s - 1, 0));
  const handleNext = () => setCurrentStep((s) => Math.min(s + 1, steps.length - 1));

  /* ===== 4) OpenAI Realtime 훅 초기화 ===== */
  const selectStepFromEvent = useCallback((event) => {
    const fallback = Number.isFinite(event?.step)
      ? Math.max(0, Math.min(steps.length - 1, Number(event.step) - 1))
      : currentStep;
    if (typeof event?.data === "string" && event.data.trim()) {
      const normalized = event.data.trim().replace(/\/$/, "");
      const fromUrl = steps.findIndex(
        (s) => s.url.replace(/\/$/, "") === normalized,
      );
      if (fromUrl >= 0) return fromUrl;
    }
    return fallback;
  }, [currentStep]);

  const handleAssistantEvent = useCallback(
    (event) => {
      if (event.type === "video") {
        setCurrentStep(selectStepFromEvent(event));
      }
    },
    [selectStepFromEvent],
  );

  const voiceChat = useOpenAIVoiceChat({
    userId: DEMO_USER_ID,
    recipeId: DEMO_RECIPE_ID,
    onAssistantEvent: handleAssistantEvent,
  });

  const connectionLabel = voiceChat.isActive
    ? "연결됨"
    : voiceChat.isLoading
      ? "연결 중…"
      : "대기 중";

  const canStartVoice = Boolean(voiceChat.sessionInfo?.system_prompt);

  /* ===== 9) UI ===== */
  return (
    <div className="complete-page">
      <div className="complete-header">
        <img src={topLogo} className="logo" alt="CHEF YUM" />
      </div>

      <div className="main-icon">
        <img src={CookingIcon} alt="조리 아이콘" className="cooking-img" />
      </div>

      {/* 유튜브 영상 */}
      <div className="cooking-video">
        <YouTube key={videoId} videoId={videoId} opts={ytOpts} onReady={onReady} onError={onError} />
      </div>

      {/* 임베딩 금지 안내 */}
      {blocked.has(currentStep) && (
        <div className="yt-fallback">
          이 영상은 소유자 설정으로 앱에서 재생할 수 없어요.{" "}
          <a href={link} target="_blank" rel="noreferrer">유튜브에서 보기</a>
        </div>
      )}

      {/* 영상 제어 */}
      <div className="cooking-controls">
        <button onClick={handlePrev}>← 이전</button>
        <button onClick={() => playerRef.current?.playVideo()}>▶ 재생</button>
        <button onClick={() => playerRef.current?.pauseVideo()}>⏸ 멈춤</button>
        <button onClick={handleNext}>다음 →</button>
      </div>

      {/* 음성 제어 + 연결상태 */}
      <div className="control-buttons" style={{ alignItems: "center", gap: 12 }}>
        {!voiceChat.isActive ? (
          <button
            className="play-btn"
            onClick={voiceChat.start}
            disabled={!canStartVoice || voiceChat.isLoading}
          >
            <FaPlay /> 음성 시작
          </button>
        ) : (
          <button className="stop-btn" onClick={voiceChat.stop}>
            <FaStop /> 음성 중지
          </button>
        )}
        <span style={{ fontSize: 12, color: "#666" }}>
          상태: {connectionLabel}
        </span>
        {!canStartVoice && (
          <span style={{ fontSize: 12, color: "#999" }}>
            프롬프트 동기화 후 시작할 수 있어요.
          </span>
        )}
      </div>

      {voiceChat.error && (
        <div className="card error">
          <h2>에러</h2>
          <p>{voiceChat.error.message}</p>
        </div>
      )}

      {voiceChat.sessionInfo && (
        <div className="card">
          <h2>대화 기록</h2>
          <ul className="voice-log">
            {voiceChat.messages
              .filter((message) => message.role === "assistant")
              .slice(-1)
              .map((message) => {
                const firstPart = message.parts.find((p) => p.type === "text");
                const text = firstPart ? firstPart.text : "[도구 호출]";
                return (
                  <li key={message.id}>
                    <strong>🤖 </strong>{" "}
                    <span>{text}</span>
                  </li>
                );
              })}
          </ul>
        </div>
      )}
    </div>
  );
}
