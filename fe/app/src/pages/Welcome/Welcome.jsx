// src/pages/Welcome/Welcome.jsx
import { useNavigate } from "react-router-dom";
import "./Welcome.css";  // 스타일 있으면 유지

export default function Welcome() {
  const navigate = useNavigate();

  const handleStart = () => {
    navigate("/welcome1");
  };

  return (
    <div className="welcome-page">
      <h1>요리 도우미에 오신 걸 환영합니다 👩‍🍳</h1>
      <p>아이들이 안전하게 요리할 수 있도록 함께 도와드려요!</p>
      <button className="start-btn" onClick={handleStart}>
        시작하기
      </button>
    </div>
  );
}
