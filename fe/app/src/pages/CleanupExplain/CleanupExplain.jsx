import React, { useState, useRef, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { FaPlay, FaStop } from "react-icons/fa";
import topLogo from "../../assets/top_logo.png";
import { float32ToPcm16 } from "../../lib/utils";
import "./CleanupExplain.css";

export default function CleanupExplain() {
  const nav = useNavigate();

  /* ===== 상태 ===== */
  const [isStreaming, setIsStreaming] = useState(false);
  const [connStatus, setConnStatus] = useState("disconnected");
  const [currentMsg, setCurrentMsg] = useState({ role: "", text: "" });
  const [prevMsg, setPrevMsg] = useState({ role: "", text: "" });

  /* ===== 오디오/소켓 레퍼런스 ===== */
  const wsRef = useRef(null);
  const micCtxRef = useRef(null);
  const micChainRef = useRef(null);
  const playbackCtxRef = useRef(null);
  const audioQueueRef = useRef([]);
  const isPlayingRef = useRef(false);

  /* ===== WebSocket URL (필요 시 수정) ===== */
  const WS_URL = "ws://192.168.0.11:8000/assistant/ws/cleanup-assistant/2/42";

  /* ===== 스트리밍 시작/중지 ===== */
  const startStream = async () => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) return;

    setConnStatus("connecting");
    wsRef.current = new WebSocket(WS_URL);

    wsRef.current.onopen = async () => {
      setConnStatus("connected");
      await startMicCapture();
      await ensurePlaybackCtx();
      setIsStreaming(true);
        // ✅ 연결 직후 서버에 초기 메시지(config) 전송
    wsRef.current.send(
        JSON.stringify({ type: "config", data: { init: true } })
        );
    };

    wsRef.current.onmessage = async (event) => {
      // 오디오 바이너리
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

      // 텍스트 JSON
      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch {
        return;
      }

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
      try { wsRef.current.close(); } catch {}
    }
    setIsStreaming(false);
  };

  /* ===== 마이크 캡처 ===== */
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

  /* ===== 서버 음성 재생 ===== */
  const ensurePlaybackCtx = async () => {
    if (playbackCtxRef.current) return;
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    playbackCtxRef.current = new AudioCtx();
  };

  const closePlaybackCtx = () => {
    if (playbackCtxRef.current) {
      try { playbackCtxRef.current.close(); } catch {}
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
    src.onended = () => playNextFromQueue();
    try { src.start(); } catch { isPlayingRef.current = false; }
  };

  /* ===== 언마운트 정리 ===== */
  useEffect(() => {
    return () => {
      stopMicCapture();
      closePlaybackCtx();
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        try { wsRef.current.close(); } catch {}
      }
    };
  }, []);

  return (
    <div className="cleanup-page">
      <div className="cleanup-header">
        <img src={topLogo} className="logo" alt="CHEF YUM" />
      </div>

      <h1 className="cleanup-title">남은 재료 보관법 & 분리배출 도우미</h1>
      <p className="cleanup-desc">
        마이크로 질문하면 음성으로 안내해 드릴게요. (예: “대파는 어떻게 보관해?”)
      </p>

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
          상태: {connStatus === "connected" ? "연결됨" : connStatus === "connecting" ? "연결 중…" : "끊김"}
        </span>
      </div>

      {/* 대화 기록 */}
      {(currentMsg.text || prevMsg.text) && (
        <div className="card">
          <h2>대화기록</h2>
          <div className="msg-stage">
            {prevMsg.text && (
              <div className={`msg-prev ${prevMsg.role}`}>
                <span className="bullet">{prevMsg.role === "ai" ? "🤖" : "👂"}</span>
                <span className="text">{prevMsg.text}</span>
              </div>
            )}
            {currentMsg.text && (
              <div className={`msg-current ${currentMsg.role}`}>
                <span className="bullet">{currentMsg.role === "ai" ? "🤖" : "👂"}</span>
                <span className="text">{currentMsg.text}</span>
              </div>
            )}
          </div>
        </div>
      )}

      <div className="bottom-actions">
        <button className="text-link" onClick={() => nav(-1)}>← 요리 화면으로 돌아가기</button>
      </div>
    </div>
  );
}
''