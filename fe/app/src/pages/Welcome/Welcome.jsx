// src/pages/Welcome/Welcome.jsx
import React from "react";
import { useNavigate } from "react-router-dom";
import "./Welcome.css";

export default function Welcome() {
  const navigate = useNavigate();

  const handleStart = () => {
    navigate("/welcome1"); // 👉 버튼 누르면 welcome1으로 이동
  };

  return (
    <div className="welcome-page">
      <img src="/Onboarding.png" alt="온보딩" className="onboarding-img" />
        {/* 👉 시작하기 버튼 위 텍스트 */}
    <div className="welcome-subtitle">
      {/* <div className="small-text">결식아동을 위한</div> */}
      {/* <div className="big-text">AI 요리 선생님</div> */}
    </div>
      <button className="welcome-start-btn" onClick={handleStart}>
        시작하기
      </button>
    </div>
  );
}
