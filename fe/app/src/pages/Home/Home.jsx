import React, { useRef, useState } from "react";
import { FaCog, FaPlay, FaStop } from "react-icons/fa";
import "./Home.css";

import CookingIcon from "../../assets/cookingexplain.png";

export default function CookingExplain() {
  const [isPlaying, setIsPlaying] = useState(false);
  const wsRef = useRef(null);
  const audioContextRef = useRef(null);
  const audioQueueRef = useRef([]);

  const handlePlay = () => {
    if (isPlaying) return;

    wsRef.current = new WebSocket(
      "ws://localhost:8000/assistant/ws/cook-assistant/1/1"
    );

    wsRef.current.onopen = () => {
      console.log("🔌 WebSocket 연결 성공");
      setIsPlaying(true);
      audioContextRef.current =
        new (window.AudioContext || window.webkitAudioContext)();
    };

    wsRef.current.onmessage = async (event) => {
      const msg = JSON.parse(event.data);

      if (msg.type === "ai") {
        console.log("🤖 AI 텍스트:", msg.text);
      }

      if (msg.type === "tts") {
        const audioBase64 = msg.audio_base64;
        const audioBytes = Uint8Array.from(atob(audioBase64), (c) =>
          c.charCodeAt(0)
        );

        try {
          const audioBuffer = await audioContextRef.current.decodeAudioData(
            audioBytes.buffer
          );
          audioQueueRef.current.push(audioBuffer);
          playNextChunk();
        } catch (err) {
          console.error("❌ 오디오 디코딩 실패:", err);
        }
      }
    };

    wsRef.current.onclose = () => {
      console.log("❌ WebSocket 닫힘");
      setIsPlaying(false);
    };
  };

  const playNextChunk = () => {
    if (!audioContextRef.current || audioQueueRef.current.length === 0) return;

    const buffer = audioQueueRef.current.shift();
    const source = audioContextRef.current.createBufferSource();
    source.buffer = buffer;
    source.connect(audioContextRef.current.destination);

    source.onended = () => {
      playNextChunk();
    };

    source.start();
  };

  const handleStop = () => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    if (audioContextRef.current) {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }
    audioQueueRef.current = [];
    setIsPlaying(false);
    console.log("⏹ 재생 정지");
  };

  return (
    <div className="complete-page">
      <div className="complete-header">
        <div className="logo">
          <span>CHEF</span> YUM
        </div>
        <button className="settings-btn">
          <FaCog />
        </button>
      </div>

      <div className="main-icon-wrapper">
        <div className="main-icon pulse-glow">
          <img src={CookingIcon} alt="조리 아이콘" className="cooking-img" />
        </div>
      </div>

      <h2 className="title">조리 과정 설명 중</h2>

      <div className="control-buttons">
        <button className="play-btn" onClick={handlePlay} disabled={isPlaying}>
          <FaPlay /> 재생
        </button>
        <button className="stop-btn" onClick={handleStop} disabled={!isPlaying}>
          <FaStop /> 정지
        </button>
      </div>
    </div>
  );
}
