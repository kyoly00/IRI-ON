// src/pages/Welcome/Welcome1.jsx
import { useNavigate } from "react-router-dom";

export default function Welcome1() {
  const navigate = useNavigate();

  return (
    <div className="welcome1">
      <h1>로그인</h1>
      {/* 실제 로그인 로직은 나중에 추가 */}
      <button onClick={() => navigate("/welcome2")}>
        로그인 하기
      </button>
    </div>
  );
}
