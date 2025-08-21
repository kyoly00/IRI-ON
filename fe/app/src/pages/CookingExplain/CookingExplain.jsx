import React, { useState, useRef, useMemo } from "react";
import YouTube from "react-youtube";
import "./CookingExplain.css";
import topLogo from "../../assets/top_logo.png";

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

const getVideoId = (url) => {
  try {
    const u = new URL((url || "").trim());
    if (u.hostname === "youtu.be") return u.pathname.slice(1);
    return u.searchParams.get("v") || "";
  } catch {
    return "";
  }
};

export default function CookingExplain() {
  const [currentStep, setCurrentStep] = useState(0);
  const [blocked, setBlocked] = useState(new Set()); // 101/150 등 블락된 스텝 기록
  const playerRef = useRef(null);

  // 현재 스텝의 id / 원본 링크
  const { videoId, link } = useMemo(() => {
    const url = steps[currentStep].url;
    return { videoId: getVideoId(url), link: url };
  }, [currentStep]);

  const opts = {
    width: "100%",
    height: "315",
    host: "https://www.youtube.com", // 또는 'https://www.youtube-nocookie.com'
    playerVars: {
      autoplay: 1,
      controls: 1,
      mute: 1,
      playsinline: 1,
      origin: window.location.origin,
    },
  };

  const onReady = (e) => {
    playerRef.current = e.target;
    try { e.target.playVideo(); } catch {}
  };

  const onError = (e) => {
    const code = e.data;
    console.warn("YouTube onError code:", code, "step:", currentStep + 1, "videoId:", videoId);

    // 101/150: 임베딩 금지 → 자동으로 다음 스텝으로 스킵
    if (code === 101 || code === 150) {
      setBlocked((prev) => new Set(prev).add(currentStep));
      // 다음 재생 가능한 스텝 찾기
      const next = findNextPlayable(currentStep);
      if (next !== currentStep) setCurrentStep(next);
    }
  };

  const findNextPlayable = (startIdx) => {
    // 앞으로 가면서 blocked 아닌 첫 스텝
    for (let i = startIdx + 1; i < steps.length; i++) {
      if (!blocked.has(i)) return i;
    }
    // 뒤로도 없으면 그냥 현재 유지
    return startIdx;
  };

  const handlePrev = () => setCurrentStep((s) => Math.max(s - 1, 0));
  const handleNext = () => setCurrentStep((s) => Math.min(s + 1, steps.length - 1));

  const handlePlayPause = () => {
    if (!playerRef.current) return;
    const state = playerRef.current.getPlayerState();
    if (state === 1) playerRef.current.pauseVideo();
    else playerRef.current.playVideo();
  };

  return (
    <div className="cooking-page">
      <div className="cooking-top">
        <img className="cooking-logo" src={topLogo} alt="CHEF YUM" />
      </div>

      <div className="cooking-video">
        <YouTube
          key={videoId}          // videoId 바뀔 때 완전 리마운트
          videoId={videoId}
          opts={opts}
          onReady={onReady}
          onError={onError}
        />
      </div>

      {/* 임베딩 금지였던 스텝일 때 안내 + 대체 링크 */}
      {blocked.has(currentStep) && (
        <div className="yt-fallback">
          이 영상은 소유자 설정으로 앱에서 재생할 수 없어요.{" "}
          <a href={link} target="_blank" rel="noreferrer">유튜브에서 보기</a>
        </div>
      )}

      <div className="cooking-controls">
        <button onClick={handlePrev}>← 이전</button>
        <button onClick={handlePlayPause}>⏯ 재생/멈춤</button>
        <button onClick={handleNext}>다음 →</button>
      </div>
    </div>
  );
}
