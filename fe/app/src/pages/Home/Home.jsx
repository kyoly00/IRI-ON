import React, { useState, useRef, useEffect } from "react";
import { Mic, StopCircle, Video, Monitor } from 'lucide-react';
import { FaCog, FaPlay, FaStop } from "react-icons/fa";
import { base64ToFloat32Array, float32ToPcm16 } from "../../lib/utils";
import CookingIcon from "../../assets/cookingexplain.png";
import "./Home.css";

export default function CookingExplain() {
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState(null);
  const [text, setText] = useState('');
  const [config, setConfig] = useState({
  systemPrompt: "You are a friendly Gemini 2.0 model. Respond verbally in a casual, helpful tone.",
  voice: "Puck",
  googleSearch: true,
  allowInterruptions: false
});
  const [isConnected, setIsConnected] = useState(false);
  const wsRef = useRef(null);
  const audioContextRef = useRef(null);
  const audioInputRef = useRef(null);
  const [videoEnabled, setVideoEnabled] = useState(false);
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const videoStreamRef = useRef(null);
  const videoIntervalRef = useRef(null);
  const [chatMode, setChatMode] = useState(null);
  const [videoSource, setVideoSource] = useState(null);

  const voices = ["Puck", "Charon", "Kore", "Fenrir", "Aoede"];
  let audioBuffer = []
  let isPlaying = false

  const startStream = async (mode) => {
    if (mode !== 'audio') {
      setChatMode('video');
    } else {
      setChatMode('audio');
    }

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
      const response = JSON.parse(event.data);
      if (response.type === 'audio') {
        const audioData = base64ToFloat32Array(response.data);
        playAudioData(audioData);
      } else if (response.type === 'output_text') {
        // output_text 타입 처리: Gemini에서 보낸 완성된 텍스트
        setText(prev => prev + response.data + '\n');
      } else if (response.type === 'input_text') {
        // 필요하면 input_text도 처리 가능
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
    if (videoEnabled && videoRef.current) {
      const startVideo = async () => {
        try {
          let stream;
          if (videoSource === 'camera') {
            stream = await navigator.mediaDevices.getUserMedia({
              video: { width: { ideal: 320 }, height: { ideal: 240 } }
            });
          } else if (videoSource === 'screen') {
            stream = await navigator.mediaDevices.getDisplayMedia({
              video: { width: { ideal: 1920 }, height: { ideal: 1080 } }
            });
          }
          
          videoRef.current.srcObject = stream;
          videoStreamRef.current = stream;
          
          // Start frame capture after video is playing
          videoIntervalRef.current = setInterval(() => {
            captureAndSendFrame();
          }, 1000);

        } catch (err) {
          console.error('Video initialization error:', err);
          setError('Failed to access camera/screen: ' + err.message);

          if (videoSource === 'screen') {
            // Reset chat mode and clean up any existing connections
            setChatMode(null);
            stopStream();
          }

          setVideoEnabled(false);
          setVideoSource(null);
        }
      };

      startVideo();

      // Cleanup function
      return () => {
        if (videoStreamRef.current) {
          videoStreamRef.current.getTracks().forEach(track => track.stop());
          videoStreamRef.current = null;
        }
        if (videoIntervalRef.current) {
          clearInterval(videoIntervalRef.current);
          videoIntervalRef.current = null;
        }
      };
    }
  }, [videoEnabled, videoSource]);

  // Frame capture function
  const captureAndSendFrame = () => {
    if (!canvasRef.current || !videoRef.current || !wsRef.current) return;
    
    const context = canvasRef.current.getContext('2d');
    if (!context) return;
    
    canvasRef.current.width = videoRef.current.videoWidth;
    canvasRef.current.height = videoRef.current.videoHeight;
    
    context.drawImage(videoRef.current, 0, 0);
    const base64Image = canvasRef.current.toDataURL('image/jpeg').split(',')[1];
    
    wsRef.current.send(JSON.stringify({
      type: 'image',
      data: base64Image
    }));
  };

  // Toggle video function
  const toggleVideo = () => {
    setVideoEnabled(!videoEnabled);
  };

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      stopStream();
    };
  }, []);

  return (
    <div className="container mx-auto py-8 px-4 space-y-6">
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
      </div>

      <div className="control-buttons">
        {!isStreaming ? (
          <>
            <button className="play-btn" onClick={() => startStream('audio')} disabled={isStreaming}>
              <FaPlay /> 재생
            </button>
            <button className="stop-btn" onClick={stopStream} disabled={!isStreaming}>
              <FaStop /> 정지
            </button>
          </>
        ) : (
          <button className="stop-btn" onClick={stopStream}>
            <FaStop /> 정지
          </button>
        )}
      </div>

      {isStreaming && (
        <div className="card">
          <div className="card-content flex items-center justify-center h-24 mt-6">
            <div className="flex flex-col items-center gap-2">
              <Mic className="h-8 w-8 text-blue-500 animate-pulse" />
              <p className="text-gray-600">Listening...</p>
            </div>
          </div>
        </div>
      )}

      {chatMode === 'video' && (
        <div className="card">
          <div className="card-content pt-6 space-y-4">
            <h2 className="text-lg font-semibold">Video Input</h2>
            <div className="relative aspect-video bg-black rounded-lg overflow-hidden">
              <video
                ref={videoRef}
                autoPlay
                playsInline
                muted
                width={320}
                height={240}
                className="w-full h-full object-contain"
                style={{ transform: videoSource === 'camera' ? 'scaleX(-1)' : 'none' }}
              />
              <canvas ref={canvasRef} className="hidden" width={640} height={480} />
            </div>
          </div>
        </div>
      )}

      {text && (
        <div className="card">
          <div className="card-content pt-6">
            <h2 className="text-lg font-semibold mb-2">Conversation:</h2>
            <pre className="whitespace-pre-wrap text-gray-700">{text}</pre>
          </div>
        </div>
      )}
    </div>
  );
}