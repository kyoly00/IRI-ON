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
      <button className="welcome-start-btn" onClick={handleStart}>
        시작하기
      </button>
    </div>
  );
}
