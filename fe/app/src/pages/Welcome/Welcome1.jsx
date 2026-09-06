import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { FaEnvelope, FaLock } from "react-icons/fa";
import "./Welcome1.css";
import topLogo from "../../assets/top_logo.png";
import { api } from "../../lib/api";

export default function Welcome1() {
  const navigate = useNavigate();
  const [isSignUp, setIsSignUp] = useState(false); // false: 로그인, true: 회원가입
  const [id, setId] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!id || !password) {
      alert("이메일과 비밀번호를 입력해주세요.");
      return;
    }

    if (isSignUp && password !== passwordConfirm) {
      alert("비밀번호 확인이 일치하지 않습니다.");
      return;
    }

    setSubmitting(true);
    try {
      const endpoint = isSignUp ? "/users/signUp" : "/users/login";
      const res = await fetch(api(endpoint), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id, password }),
      });

      let data = null;
      try { data = await res.json(); } catch { data = null; }

      if (res.ok && data?.user_id != null) {
        // ✅ user_id 저장
        localStorage.setItem("user_id", String(data.user_id));
        
        if (isSignUp) {
          alert("회원가입이 완료되었습니다! 맞춤 프로필을 설정해주세요.");
          navigate("/welcome2", { state: { userId: data.user_id } });
        } else {
          // 기존 회원이면 프로필 여부에 따라 홈 또는 온보딩으로 이동
          if (data.has_profile) {
            navigate("/home", { state: { userId: data.user_id } });
          } else {
            navigate("/welcome2", { state: { userId: data.user_id } });
          }
        }
      } else {
        const msg = (data && (data.detail || data.message)) || 
          (isSignUp ? "회원가입에 실패했습니다." : "로그인에 실패했습니다.");
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

      <h1 className="welcome1-title">{isSignUp ? "회원가입" : "환영합니다!"}</h1>
      <p className="welcome1-subtitle">
        {isSignUp ? "계정을 생성하고 맞춤 요리 가이드를 받아보세요." : "로그인을 하고 맞춤 메뉴를 추천받으세요."}
      </p>

      <form className="welcome1-form" onSubmit={handleSubmit}>
        <label className="input-group">
          <span className="input-icon"><FaEnvelope /></span>
          <input
            type="email"
            placeholder="이메일을 입력하세요."
            value={id}
            onChange={(e) => setId(e.target.value)}
            autoComplete="email"
            required
          />
        </label>

        <label className="input-group">
          <span className="input-icon"><FaLock /></span>
          <input
            type="password"
            placeholder="비밀번호를 입력하세요."
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete={isSignUp ? "new-password" : "current-password"}
            required
          />
        </label>

        {isSignUp && (
          <label className="input-group">
            <span className="input-icon"><FaLock /></span>
            <input
              type="password"
              placeholder="비밀번호를 다시 입력하세요."
              value={passwordConfirm}
              onChange={(e) => setPasswordConfirm(e.target.value)}
              autoComplete="new-password"
              required
            />
          </label>
        )}

        {!isSignUp && <div className="welcome1-forgot">잊어버렸어요.</div>}

        <button
          type="submit"
          className="btn btn-primary"
          disabled={submitting}
          aria-busy={submitting ? "true" : "false"}
        >
          {submitting ? (isSignUp ? "가입 중..." : "로그인 중...") : (isSignUp ? "회원가입 완료" : "로그인")}
        </button>

        <button
          type="button"
          className="btn btn-secondary"
          onClick={() => {
            setIsSignUp(!isSignUp);
            setPasswordConfirm("");
          }}
        >
          {isSignUp ? "이미 계정이 있으신가요? 로그인하기" : "새 계정 만들기 (회원가입)"}
        </button>
      </form>
    </div>
  );
}
