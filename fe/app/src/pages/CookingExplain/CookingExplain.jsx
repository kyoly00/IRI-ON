import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import YouTube from "react-youtube";
import { FaPlay, FaRedo, FaStop } from "react-icons/fa";

import topLogo from "../../assets/top_logo.png";
import { api } from "../../lib/api";
import { useVoiceChat } from "../../lib/ai/speech/use-voice-chat";
import "./CookingExplain.css";

const getVideoId = (url) => {
  if (!url) return "";
  try {
    const parsed = new URL(url);
    if (parsed.hostname.includes("youtu.be")) return parsed.pathname.split("/")[1] || "";
    const parts = parsed.pathname.split("/").filter(Boolean);
    if (["embed", "shorts", "live"].includes(parts[0])) return parts[1] || "";
    return parsed.searchParams.get("v") || "";
  } catch {
    return "";
  }
};

const formatSeconds = (seconds) => {
  if (!Number.isFinite(seconds)) return "";
  const minutes = Math.floor(seconds / 60);
  const remain = Math.floor(seconds % 60);
  return `${minutes}:${String(remain).padStart(2, "0")}`;
};

export default function CookingExplain() {
  const { id } = useParams();
  const navigate = useNavigate();
  const recipeId = Number(id);
  const userId = Number(localStorage.getItem("user_id")) || 5;
  const playerRef = useRef(null);

  const [recipe, setRecipe] = useState(null);
  const [currentStep, setCurrentStep] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [embedError, setEmbedError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    fetch(api(`/recipes/${recipeId}`), { credentials: "include" })
      .then(async (response) => {
        if (!response.ok) throw new Error("레시피를 불러오지 못했어요.");
        return response.json();
      })
      .then((data) => {
        if (!cancelled) {
          setRecipe(data);
          setCurrentStep(0);
        }
      })
      .catch((reason) => {
        if (!cancelled) setError(reason.message || "레시피를 불러오지 못했어요.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [recipeId]);

  const steps = recipe?.steps || [];
  const activeStep = steps[currentStep] || null;
  const videoId = activeStep?.video_id || recipe?.video_id || getVideoId(recipe?.video_url);
  const startSeconds = Number(activeStep?.start_seconds) || 0;
  const stepLength = Number(activeStep?.step_len) || null;
  const startUrl = activeStep?.start_url || recipe?.video_url || "";

  const moveToStep = useCallback((index) => {
    setCurrentStep(Math.max(0, Math.min(index, Math.max(steps.length - 1, 0))));
    setEmbedError(false);
  }, [steps.length]);

  const handleAssistantEvent = useCallback((event) => {
    if (event.type === "video" && Number.isFinite(Number(event.step))) {
      moveToStep(Number(event.step) - 1);
      return;
    }
    if (event.type !== "navigate_step") return;
    if (event.action === "next") setCurrentStep((value) => Math.min(value + 1, Math.max(steps.length - 1, 0)));
    if (event.action === "prev") setCurrentStep((value) => Math.max(value - 1, 0));
    if (event.action === "set" && Number.isFinite(Number(event.targetStep))) {
      moveToStep(Number(event.targetStep) - 1);
    }
  }, [moveToStep, steps.length]);

  const voiceChat = useVoiceChat({
    userId,
    recipeId,
    onAssistantEvent: handleAssistantEvent,
  });

  const ytOpts = useMemo(() => {
    const playerVars = {
      autoplay: 1,
      controls: 1,
      playsinline: 1,
      start: startSeconds,
      rel: 0,
    };
    if (stepLength) playerVars.end = startSeconds + stepLength;
    return { width: "100%", height: "315", playerVars };
  }, [startSeconds, stepLength]);

  const handleReady = (event) => {
    playerRef.current = event.target;
    event.target.seekTo(startSeconds, true);
    event.target.playVideo();
  };

  const replay = () => {
    if (!playerRef.current) return;
    playerRef.current.seekTo(startSeconds, true);
    playerRef.current.playVideo();
  };

  const latestAssistantMessage = [...voiceChat.messages]
    .reverse()
    .find((message) => message.role === "assistant" && message.parts.some((part) => part.type === "text"));
  const latestText = latestAssistantMessage?.parts.find((part) => part.type === "text")?.text;

  if (loading) return <div className="cooking-page cooking-state">레시피를 준비하고 있어요…</div>;
  if (error || !recipe) {
    return (
      <div className="cooking-page cooking-state">
        <p>{error || "레시피가 없어요."}</p>
        <button onClick={() => navigate("/menu")}>메뉴로 돌아가기</button>
      </div>
    );
  }

  return (
    <div className="cooking-page">
      <header className="cooking-header">
        <button className="back-button" onClick={() => navigate("/menu")} aria-label="메뉴로 돌아가기">←</button>
        <img src={topLogo} className="logo" alt="CHEF YUM" />
        <span className="header-spacer" />
      </header>

      <section className="recipe-heading">
        <img src={recipe.image_url} alt="" />
        <div>
          <span className="video-badge">{recipe.has_video ? "영상 레시피" : "레시피"}</span>
          <h1>{recipe.name}</h1>
          <p>{recipe.description}</p>
          <div className="recipe-meta">
            {recipe.time && <span>⏱ {recipe.time}분</span>}
            {recipe.servings && <span>🍽 {recipe.servings}인분</span>}
            {recipe.difficulty && <span>난이도 {recipe.difficulty}</span>}
          </div>
        </div>
      </section>

      {videoId ? (
        <section className="video-section">
          <YouTube
            key={`${videoId}-${startSeconds}-${stepLength || "full"}`}
            videoId={videoId}
            opts={ytOpts}
            onReady={handleReady}
            onError={() => setEmbedError(true)}
          />
          {embedError && (
            <p className="yt-fallback">
              앱에서 재생할 수 없는 영상이에요. <a href={startUrl} target="_blank" rel="noreferrer">YouTube에서 보기</a>
            </p>
          )}
          {!recipe.timeline_ready && (
            <p className="timeline-notice">아직 구간 타임라인을 생성하지 않아 전체 영상과 원문 단계를 보여주고 있어요.</p>
          )}
        </section>
      ) : (
        <img className="recipe-main-image" src={recipe.image_url} alt={recipe.name} />
      )}

      {activeStep && (
        <section className="step-card">
          <div className="step-title-row">
            <h2>{activeStep.step}단계 <small>/ {steps.length}</small></h2>
            {recipe.timeline_ready && (
              <span>{formatSeconds(startSeconds)} · {stepLength}초</span>
            )}
          </div>
          <p>{activeStep.text}</p>
        </section>
      )}

      <div className="cooking-controls">
        <button onClick={() => moveToStep(currentStep - 1)} disabled={currentStep === 0}>← 이전</button>
        {videoId && <button className="replay-button" onClick={replay}><FaRedo /> 다시 보기</button>}
        <button onClick={() => moveToStep(currentStep + 1)} disabled={currentStep >= steps.length - 1}>다음 →</button>
      </div>

      <nav className="step-list" aria-label="레시피 단계">
        {steps.map((step, index) => (
          <button
            key={step.step}
            className={index === currentStep ? "active" : ""}
            onClick={() => moveToStep(index)}
          >
            {step.step}
          </button>
        ))}
      </nav>

      <section className="voice-card">
        <div>
          <h2>셰프얌과 같이 요리하기</h2>
          <p>{voiceChat.isActive ? (voiceChat.isAssistantSpeaking ? "셰프얌이 말하고 있어요" : "듣고 있어요. 편하게 말해 주세요!") : "음성으로 단계 이동과 질문을 도와줄게요."}</p>
        </div>
        {!voiceChat.isActive ? (
          <button className="play-btn" onClick={voiceChat.start} disabled={!voiceChat.sessionInfo || voiceChat.isLoading}>
            <FaPlay /> {voiceChat.isLoading ? "연결 중" : "시작"}
          </button>
        ) : (
          <button className="stop-btn" onClick={voiceChat.stop}><FaStop /> 종료</button>
        )}
      </section>

      {voiceChat.error && <p className="voice-error">음성 연결 오류: {voiceChat.error.message}</p>}
      {latestText && <div className="assistant-bubble">🤖 {latestText}</div>}

      <details className="recipe-detail-card">
        <summary>재료와 조리도구 보기</summary>
        <h3>재료</h3>
        <p>{recipe.materials || "등록된 재료가 없어요."}</p>
        <h3>조리도구</h3>
        <p>{recipe.tools || "등록된 조리도구가 없어요."}</p>
        {recipe.tips && <><h3>팁</h3><p>{recipe.tips}</p></>}
      </details>
    </div>
  );
}
