import { useState } from "react";
import { useNavigate } from "react-router-dom";
import "./Welcome1.css";

export default function Welcome1() {
  const navigate = useNavigate();
  const [id, setId] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (submitting) return;                    // 중복 제출 방지
    if (!id || !password) {
      alert("이메일과 비밀번호를 입력해주세요.");
      return;
    }

    const url = "http://localhost:8000/users/signUp";
    const payload = { id, password };

    console.groupCollapsed("🔶 POST /users/signUp");
    console.log("→ URL:", url);
    console.log("→ Payload:", payload);

    setSubmitting(true);
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const raw = await res.text();
      let data = null;
      try { data = raw ? JSON.parse(raw) : null; } catch { data = raw; }

      console.log("← Status:", res.status, res.statusText);
      console.log("← Raw:", raw);

      if (!res.ok) {
        console.error("❌ 요청 실패:", data);
        alert(`로그인/가입 실패 (HTTP ${res.status})`);
        // return;  // ❌ 막지 말고 finally에서 이동
      } else {
        console.log("✅ 요청 성공:", data);
        alert("로그인/가입 성공!");
      }
    } catch (err) {
      console.error("❌ 네트워크/CORS 에러:", err);
      alert("네트워크/CORS 에러로 요청에 실패했습니다.");
    } finally {
      console.groupEnd();
      setSubmitting(false);
      navigate("/welcome2");                   // ✅ 성공/실패 상관없이 이동
    }
  };

  return (
    <div className="welcome1">
      <div className="panel">
        <h1 className="title">환영합니다!</h1>
        <p className="subtitle">로그인을 하고 맞춤형 레시피를 추천받으세요.</p>

        <form className="form" onSubmit={handleSubmit}>
          <label htmlFor="email" className="sr-only">이메일</label>
          <input
            id="email"
            type="email"
            placeholder="이메일"
            value={id}
            onChange={(e) => setId(e.target.value)}
            autoComplete="email"
            disabled={submitting}
          />

          <label htmlFor="password" className="sr-only">패스워드</label>
          <input
            id="password"
            type="password"
            placeholder="패스워드"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            disabled={submitting}
          />

          <button className="cta" type="submit" disabled={submitting}>
            {submitting ? "처리 중..." : "로그인"}
          </button>
        </form>
      </div>
    </div>
  );
}
