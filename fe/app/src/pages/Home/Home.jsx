// Home.jsx
import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import "./Home.css";

import topLogo from "../../assets/top_logo.png";   // CHEF YUM 로고
import chef3d from "../../assets/3dLogo.png";     // 셰프 캐릭터
import { FiSearch, FiHeart, FiBell, FiStar, FiClock } from "react-icons/fi";

export default function Home() {
  const nav = useNavigate();

  // ✅ 메뉴를 하드코딩으로 많이 추가
  const [menus] = useState([
    { id: 1, name: "토마토 스파게티", time: "30분", thumb: "🍝" },
    { id: 2, name: "김치찌개", time: "25분", thumb: "🥘" },
    { id: 3, name: "초밥", time: "20분", thumb: "🍣" },
    { id: 4, name: "햄버거", time: "15분", thumb: "🍔" },
    { id: 5, name: "피자", time: "18분", thumb: "🍕" },
    { id: 6, name: "라면", time: "10분", thumb: "🍜" },
    { id: 7, name: "샐러드", time: "12분", thumb: "🥗" },
    { id: 8, name: "스테이크", time: "40분", thumb: "🥩" },
    { id: 9, name: "타코", time: "22분", thumb: "🌮" },
    { id: 10, name: "도넛", time: "8분", thumb: "🍩" },
    { id: 11, name: "케이크", time: "35분", thumb: "🍰" },
    { id: 12, name: "팬케이크", time: "15분", thumb: "🥞" },
  ]);

    const backendHost = window.location.hostname;
    const wsUrl = `ws://${backendHost}:8000/assistant/ws/cook-assistant/1/1`;

    wsRef.current = new WebSocket(wsUrl);

    wsRef.current.onopen = async () => {
      wsRef.current.send(JSON.stringify({
        type: 'config',
        config: config
      }));
      
      await startAudioStream();

      if (mode !== 'audio') {
        setVideoEnabled(true);
        setVideoSource(mode);
      }

      setIsStreaming(true);
      setIsConnected(true);
    };

    wsRef.current.onmessage = async (event) => {
      // 1. 바이너리(오디오) 데이터 처리
      if (event.data instanceof Blob || event.data instanceof ArrayBuffer) {
        let arrayBuffer;
        if (event.data instanceof Blob) {
          arrayBuffer = await event.data.arrayBuffer();
        } else {
          arrayBuffer = event.data;
        }

        // Float32Array 또는 Int16Array 등 AudioBuffer에 넣을 수 있는 형식으로 변환 필요!
        // 예: 16bit PCM → Int16Array → Float32Array로 변환
        const int16arr = new Int16Array(arrayBuffer);
        const floatArr = new Float32Array(int16arr.length);
        for (let i = 0; i < int16arr.length; i++) {
          floatArr[i] = int16arr[i] / 32768; // Float32 정규화(-1~1)
        }

        playAudioData(floatArr); // 기존 함수 호환
        return;
      }

      // 2. 텍스트(json) 데이터는 원래 방식대로 파싱
      let response;
      try {
        response = JSON.parse(event.data);
      } catch (e) {
        console.error('Failed to parse JSON:', e);
        return;
      }

      if (response.type === 'output_text') {
        setText(prev => prev + response.data + '\n');
      } else if (response.type === 'input_text') {
        console.log('Input transcription:', response.data);
      } else if (response.type === 'turn_complete') {
        console.log('Turn complete signal received');
      }
    };


    wsRef.current.onerror = (error) => {
      setError('WebSocket error: ' + error.message);
      setIsStreaming(false);
    };

    wsRef.current.onclose = () => {
      setIsStreaming(false);
    };

  // Initialize audio context and stream
  const startAudioStream = async () => {
    try {
      // Initialize audio context
      audioContextRef.current = new (window.AudioContext || window.webkitAudioContext)({
        sampleRate: 16000 // Required by Gemini
      });

      // Get microphone stream
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      
      // Create audio input node
      const source = audioContextRef.current.createMediaStreamSource(stream);
      const processor = audioContextRef.current.createScriptProcessor(512, 1, 1);
      
      processor.onaudioprocess = (e) => {
        if (wsRef.current?.readyState === WebSocket.OPEN) {
          const inputData = e.inputBuffer.getChannelData(0);
          const pcmData = float32ToPcm16(inputData);
          // Convert to base64 and send as binary
          const base64Data = btoa(String.fromCharCode(...new Uint8Array(pcmData.buffer)));
          wsRef.current.send(JSON.stringify({
            type: 'audio',
            data: base64Data
          }));
        }
      };

      source.connect(processor);
      processor.connect(audioContextRef.current.destination);
      
      audioInputRef.current = { source, processor, stream };
      setIsStreaming(true);
    } catch (err) {
      setError('Failed to access microphone: ' + err.message);
    }
  };

  // Stop streaming
  const stopStream = () => {
    if (audioInputRef.current) {
      const { source, processor, stream } = audioInputRef.current;
      source.disconnect();
      processor.disconnect();
      stream.getTracks().forEach(track => track.stop());
      audioInputRef.current = null;
    }

    if (chatMode === 'video') {
      setVideoEnabled(false);
      setVideoSource(null);

      if (videoStreamRef.current) {
        videoStreamRef.current.getTracks().forEach(track => track.stop());
        videoStreamRef.current = null;
      }
      if (videoIntervalRef.current) {
        clearInterval(videoIntervalRef.current);
        videoIntervalRef.current = null;
      }
    }

    // stop ongoing audio playback
    if (audioContextRef.current) {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }

    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    setIsStreaming(false);
    setIsConnected(false);
    setChatMode(null);
  };

  const playAudioData = async (audioData) => {
    audioBuffer.push(audioData);
    if (!isPlaying) {
      playNextInQueue(); // Start playback if not already playing
    }
  };

  const playNextInQueue = async () => {
    if (!audioContextRef.current || audioBuffer.length === 0) {
      isPlaying = false;
      return;
    }

    isPlaying = true;
    const audioData = audioBuffer.shift();

    const buffer = audioContextRef.current.createBuffer(1, audioData.length, 24000);
    buffer.copyToChannel(audioData, 0);

    const source = audioContextRef.current.createBufferSource();
    source.buffer = buffer;
    source.connect(audioContextRef.current.destination);
    source.onended = () => {
      playNextInQueue();
    };
    source.start();
  };

  useEffect(() => {
    const current = texts[textIdx];
    let timer;

    if (!isDeleting && charIdx <= current.length) {
      timer = setTimeout(() => {
        setDisplayText(current.slice(0, charIdx));
        setCharIdx((c) => c + 1);
      }, 120);
    } else if (isDeleting && charIdx >= 0) {
      timer = setTimeout(() => {
        setDisplayText(current.slice(0, charIdx));
        setCharIdx((c) => c - 1);
      }, 80);
    } else if (!isDeleting && charIdx > current.length) {
      timer = setTimeout(() => setIsDeleting(true), 1500);
    } else if (isDeleting && charIdx < 0) {
      setIsDeleting(false);
      setTextIdx((idx) => (idx + 1) % texts.length);
      setCharIdx(0);
    }

    return () => clearTimeout(timer);
  }, [charIdx, isDeleting, textIdx, texts]);

  return (
    <div className="home-page">
      {/* 상단바 */}
      <div className="home-top">
        <img className="home-logo" src={topLogo} alt="CHEF YUM" />
        <div className="home-actions">
          <FiSearch onClick={() => nav("/menu")} />
          <FiHeart />
          <FiBell />
        </div>
      </div>

      {/* 히어로 영역 */}
      <section className="hero">
        <img className="hero-chef" src={chef3d} alt="셰프 캐릭터" />
        <div className="hero-ment">
          {displayText}
          <span className="cursor">|</span>
        </div>
      </section>

      {/* CTA 버튼 */}
      <button className="cta" onClick={() => nav("/fridge")}>
         나만의 냉장고 만들기
      </button>

      {/* 인기 메뉴 */}
      <section className="popular">
        <div className="sec-title">
          <FiStar className="star" />
          오늘의 인기 메뉴
        </div>

        {/* 메뉴 카드 */}
<div className="menu-list">
  {menus.map((menu) => (
    <div key={menu.id} className="menu-card">
      <div className="thumb">{menu.thumb}</div>
      <div className="menu-name">{menu.name}</div>
      <div className="menu-meta">
        <FiClock /> {menu.time}
      </div>
    </div>
  ))}
</div>

      </section>
    </div>
  );
};