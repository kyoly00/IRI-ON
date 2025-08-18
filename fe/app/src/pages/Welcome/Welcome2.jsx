// src/pages/Welcome/Welcome2.jsx
import { useNavigate } from "react-router-dom";

export default function Welcome2() {
  const navigate = useNavigate();

  return (
    <div className="welcome2">
      <h1>프로필 생성</h1>
      {/* 실제 입력폼은 나중에 추가 */}
      <button onClick={() => navigate("/home")}>
        프로필 생성하기
      </button>
    </div>
  );
}
