import React, { useState, useRef, useMemo, useEffect } from "react";
import { useNavigate } from "react-router-dom"; // ✅ 라우팅용
import YouTube from "react-youtube";
import { FaPlay, FaStop } from "react-icons/fa";
import topLogo from "../../assets/top_logo.png";
import { float32ToPcm16 } from "../../lib/utils";
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

export default function CookingExplain() {
  // ✅ 라우터 훅 & 이동 함수
  const nav = useNavigate();
  const goCleanup = () => nav("/cleanup"); // 필요 시 경로를 원하는 값으로 바꿔줘

  /* ===== 2) 영상 상태 ===== */
  const [currentStep, setCurrentStep] = useState(0);
  const [blocked, setBlocked] = useState(new Set());
  const playerRef = useRef(null);

  const { videoId, link } = useMemo(() => {
    const url = steps[currentStep].url;
    return { videoId: getVideoId(url), link: url };
  }, [currentStep]);

  /* ===== 3) 음성/WS 상태 ===== */
  const [isStreaming, setIsStreaming] = useState(false);
  const [connStatus, setConnStatus] = useState("disconnected");
  const [currentMsg, setCurrentMsg] = useState({ role: "", text: "" });
  const [prevMsg, setPrevMsg] = useState({ role: "", text: "" });

  const wsRef = useRef(null);
  const micCtxRef = useRef(null);
  const micChainRef = useRef(null);
  const playbackCtxRef = useRef(null);
  const playbackSrcRef = useRef(null);
  const audioQueueRef = useRef([]);
  const isPlayingRef = useRef(false);

  /* ===== 4) 유튜브 옵션 ===== */
  const ytOpts = {
    width: "100%",
    height: "315",
    host: "https://www.youtube.com",
    playerVars: { autoplay: 1, controls: 1, mute: 1, playsinline: 1 },
  };

  const onReady = (e) => {
    playerRef.current = e.target;
    try {
      e.target.playVideo();
    } catch {}
  };

  const onError = (e) => {
    const code = e.data;
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

  /* ===== 5) WebSocket ===== */
  const WS_URL = "ws://localhost:8000/assistant/ws/cook-assistant/2/42";

  const startStream = async () => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) return;
    setConnStatus("connecting");
    wsRef.current = new WebSocket(WS_URL);

    wsRef.current.onopen = async () => {
      setConnStatus("connected");
      await startMicCapture();
      await ensurePlaybackCtx();
      setIsStreaming(true);
    wsRef.current.send(
        JSON.stringify({ type: "config", data: { init: true } })
        );
    };


    wsRef.current.onmessage = async (event) => {
      // 오디오 응답
      if (event.data instanceof Blob || event.data instanceof ArrayBuffer) {
        let arrayBuffer;
        if (event.data instanceof Blob) arrayBuffer = await event.data.arrayBuffer();
        else arrayBuffer = event.data;

        const int16 = new Int16Array(arrayBuffer);
        const float32 = new Float32Array(int16.length);
        for (let i = 0; i < int16.length; i++) float32[i] = int16[i] / 32768;
        enqueuePlayback(float32);
        return;
      }

      // JSON 메시지
      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch {
        return;
      }

      if (msg?.type === "video") {
        const n = Math.max(1, Math.min(steps.length, Number(msg.step) || 1));
        const fromUrl =
          typeof msg.data === "string" && msg.data
            ? steps.findIndex(
                (s) =>
                  s.url.replace(/\/$/, "") === msg.data.trim().replace(/\/$/, "")
              )
            : -1;
        const idx = fromUrl >= 0 ? fromUrl : n - 1;
        setCurrentStep(idx);
        return;
      }
      
      if (msg.type === "audio_start") {
        // 새 오디오가 들어올 거라는 신호
        audioQueueRef.current = [];
        if (playbackSrcRef.current) {
          try { playbackSrcRef.current.stop(); } catch {}
        }
        return; // audio_start 이벤트는 오디오 재생 준비용이므로 더 처리할 필요 없음
      }

      // 대화 메시지
      const pushMsg = (role, text) => {
        if (!text) return;
        setPrevMsg((prev) => (currentMsg.text ? currentMsg : prev));
        setCurrentMsg({ role, text });
      };

      if (msg?.type === "input_text") pushMsg("stt", msg.data);
      if (msg?.type === "output_text") pushMsg("ai", msg.data);
    };

    wsRef.current.onerror = () => {
      setConnStatus("disconnected");
      setIsStreaming(false);
    };

    wsRef.current.onclose = () => {
      setConnStatus("disconnected");
      setIsStreaming(false);
      stopMicCapture();
      closePlaybackCtx();
    };
  };

  const stopStream = () => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      try {
        wsRef.current.close();
      } catch {}
    }
    setIsStreaming(false);
  };

  /* ===== 6) 마이크 캡처 ===== */
  const startMicCapture = async () => {
    if (micCtxRef.current) return;
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    micCtxRef.current = new AudioCtx({ sampleRate: 16000 });

    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const source = micCtxRef.current.createMediaStreamSource(stream);
    const processor = micCtxRef.current.createScriptProcessor(512, 1, 1);

    processor.onaudioprocess = (e) => {
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
      const inputData = e.inputBuffer.getChannelData(0);
      const pcm = float32ToPcm16(inputData);
      const base64 = btoa(String.fromCharCode(...new Uint8Array(pcm.buffer)));
      wsRef.current.send(JSON.stringify({ type: "audio", data: base64 }));
    };

    source.connect(processor);
    processor.connect(micCtxRef.current.destination);
    micChainRef.current = { source, processor, stream };
  };

  const stopMicCapture = () => {
    if (micChainRef.current) {
      const { source, processor, stream } = micChainRef.current;
      try {
        source.disconnect();
        processor.disconnect();
        stream.getTracks().forEach((t) => t.stop());
      } catch {}
      micChainRef.current = null;
    }
    if (micCtxRef.current) {
      try { micCtxRef.current.close(); } catch {}
      micCtxRef.current = null;
    }
  };

  /* ===== 7) 서버 음성 응답 재생 큐 ===== */
  const ensurePlaybackCtx = async () => {
    if (playbackCtxRef.current) return;
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    playbackCtxRef.current = new AudioCtx();
  };

  const closePlaybackCtx = () => {
    if (playbackCtxRef.current) {
      try {
        playbackCtxRef.current.close();
      } catch {}
      playbackCtxRef.current = null;
    }
    audioQueueRef.current = [];
    isPlayingRef.current = false;
  };

  const enqueuePlayback = (float32) => {
    audioQueueRef.current.push(float32);
    if (!isPlayingRef.current) playNextFromQueue();
  };

  const playNextFromQueue = () => {
    if (!playbackCtxRef.current || audioQueueRef.current.length === 0) {
      isPlayingRef.current = false;
      return;
    }
    isPlayingRef.current = true;

    const data = audioQueueRef.current.shift();
    const buffer = playbackCtxRef.current.createBuffer(1, data.length, 24000);
    buffer.copyToChannel(data, 0);

    const src = playbackCtxRef.current.createBufferSource();
    src.buffer = buffer;
    src.connect(playbackCtxRef.current.destination);
    playbackSrcRef.current = src; // 저장
    src.onended = () => playNextFromQueue();
    src.start();
  };

  /* ===== 8) 언마운트 시 정리 ===== */
  useEffect(() => {
    return () => {
      stopMicCapture();
      closePlaybackCtx();
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        try {
          wsRef.current.close();
        } catch {}
      }
    };
  }, []);

  /* ===== 9) UI ===== */
  return (
    <div className="complete-page">
      <div className="complete-header">
        <img src={topLogo} className="logo" alt="CHEF YUM" />
      </div>

      {/* 유튜브 영상 */}
      <div className="cooking-video">
        <YouTube
          key={videoId}
          videoId={videoId}
          opts={ytOpts}
          onReady={onReady}
          onError={onError}
        />
      </div>

      {/* 임베딩 금지 안내 */}
      {blocked.has(currentStep) && (
        <div className="yt-fallback">
          이 영상은 소유자 설정으로 앱에서 재생할 수 없어요.{" "}
          <a href={link} target="_blank" rel="noreferrer">
            유튜브에서 보기
          </a>
        </div>
      )}

      {/* 영상 제어 */}
      <div className="cooking-controls">
        <button onClick={handlePrev}>← 이전</button>
        <button onClick={() => playerRef.current?.playVideo()}>▶ 재생</button>
        <button onClick={() => playerRef.current?.pauseVideo()}>⏸ 멈춤</button>
        <button onClick={handleNext}>다음 →</button>
      </div>

      {/* 음성 제어 */}
      <div className="control-buttons">
        {!isStreaming ? (
          <button className="play-btn" onClick={startStream}>
            <FaPlay /> 음성 시작
          </button>
        ) : (
          <button className="stop-btn" onClick={stopStream}>
            <FaStop /> 음성 중지
          </button>
        )}
        <span className="conn-status">
          상태:{" "}
          {connStatus === "connected"
            ? "연결됨"
            : connStatus === "connecting"
            ? "연결 중…"
            : "끊김"}
        </span>
      </div>

      {/* 대화 기록 */}
      {(currentMsg.text || prevMsg.text) && (
        <div className="card">
          <h2>대화기록</h2>
          <div className="msg-stage">
            {prevMsg.text && (
              <div className={`msg-prev ${prevMsg.role}`}>
                <span className="bullet">
                  {prevMsg.role === "ai" ? "🤖" : "👂"}
                </span>
                <span className="text">{prevMsg.text}</span>
              </div>
            )}
            {currentMsg.text && (
              <div className={`msg-current ${currentMsg.role}`}>
                <span className="bullet">
                  {currentMsg.role === "ai" ? "🤖" : "👂"}
                </span>
                <span className="text">{currentMsg.text}</span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ✅ 하단 텍스트 버튼: CleanupExplain으로 이동 */}
      <div className="cleanup-row">
        <button
          type="button"
          className="cleanup-link"
          onClick={goCleanup}
          aria-label="남은 재료 보관법 및 분리배출 보러가기"
        >
          남은 재료 보관법 및 분리배출 보러가기 →
        </button>
      </div>
    </div>
  );
}
