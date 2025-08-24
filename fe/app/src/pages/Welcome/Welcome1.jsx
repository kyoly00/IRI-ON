import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { FaEnvelope, FaLock } from "react-icons/fa";
import "./Welcome1.css";
import topLogo from "../../assets/top_logo.png";
import config from "../../config.js"

export default function Welcome1() {
  const navigate = useNavigate();
  const [id, setId] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e) => {
  e.preventDefault();
  if (!id || !password) {
    alert("이메일과 비밀번호를 입력해주세요.");
    return;
  }

  setSubmitting(true);
  try {
    const res = await fetch(`${config.API_BASE}/users/signUp`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, password }),
    });

    // 응답 JSON 시도 (text일 수도 있으니 try/catch)
    let data = null;
    try { data = await res.json(); } catch {}

    if (res.ok && data?.user_id != null) {
      // ✅ user_id 저장 + 다음 화면으로 함께 전달
      localStorage.setItem("user_id", String(data.user_id));
      navigate("/welcome2", { state: { userId: data.user_id } });
    } else {
      const msg = (data && (data.detail || data.message)) || "로그인에 실패했습니다.";
      alert(msg);
    }
  } catch (err) {
    console.error(err);
    alert("서버에 연결할 수 없습니다. 백엔드를 확인해주세요.");
  } finally {
    setSubmitting(false);
  }
};


  return (
    <div className="welcome1-page">
      <img className="welcome1-logo" src={topLogo} alt="CHEF YUM" />

      <h1 className="welcome1-title">환영합니다!</h1>
      <p className="welcome1-subtitle">로그인을 하고 맞춤 메뉴를 추천받으세요.</p>

      <form className="welcome1-form" onSubmit={handleSubmit}>
        <label className="input-group">
          <span className="input-icon"><FaEnvelope /></span>
          <input
            type="email"
            placeholder="이메일을 입력하세요."
            value={id}
            onChange={(e) => setId(e.target.value)}
            autoComplete="email"
          />
        </label>

        <label className="input-group">
          <span className="input-icon"><FaLock /></span>
          <input
            type="password"
            placeholder="비밀번호를 입력하세요."
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
          />
        </label>

        <div className="welcome1-forgot">잊어버렸어요.</div>

        <button
          type="submit"
          className="btn btn-primary"
          disabled={submitting}
          aria-busy={submitting ? "true" : "false"}
        >
          {submitting ? "로그인 중..." : "로그인"}
        </button>

        {/* 회원가입은 보여주기만 (동작 없음) */}
        <button type="button" className="btn btn-secondary">
          회원가입
        </button>
      </form>
    </div>
  );
}
