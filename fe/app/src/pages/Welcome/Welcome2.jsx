import React, { useState } from "react";
import { useNavigate } from "react-router-dom"; // ← 추가: 이동용
import "./Welcome2.css";
import baby from "../../assets/baby.png"; // 경로 주의: assets 폴더 기준

export default function Welcome2() {
  const [name, setName] = useState("");
  const [canUseFire, setCanUseFire] = useState(false);
  const [canUseKnife, setCanUseKnife] = useState(false);
  const [allergies, setAllergies] = useState(new Set());
  const navigate = useNavigate(); // ← 추가: 이동 훅

  const allergyOptions = [
    { key: "egg",    label: "계란",   emoji: "🥚" },
    { key: "milk",   label: "우유",   emoji: "🥛" },
    { key: "peanut", label: "땅콩",   emoji: "🥜" },
    { key: "banana", label: "바나나", emoji: "🍌" },
    { key: "shrimp", label: "새우",   emoji: "🍤" },
  ];

  const toggleAllergy = (key) => {
    const next = new Set(allergies);
    next.has(key) ? next.delete(key) : next.add(key);
    setAllergies(next);
  };

  const handleSubmit = async () => {
    const payload = {
      name: name,
      can_use_fire: !!canUseFire,
      can_use_knife: !!canUseKnife,
      allergy: Array.from(allergies).join(",") || "",
    };

    const url = "http://localhost:8000/users/profile";
    console.log("→ POST", url, payload);

    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const raw = await res.text();
      if (!res.ok) {
        console.error("❌ API 실패:", res.status, res.statusText, raw);
        alert(`프로필 생성 실패 (HTTP ${res.status})`);
        navigate("/home"); // 실패 후에도 홈으로 이동
        return;
      }

      let data = null;
      try { data = raw ? JSON.parse(raw) : null; } catch { data = raw; }

      console.log("✅ 프로필 생성 성공:", data);
      alert("프로필 생성 완료!");
      navigate("/home"); // 성공 시 홈으로 이동
    } catch (error) {
      console.error("❌ 네트워크/코르스 에러:", error);
      alert("프로필 생성 실패 (네트워크/CORS)");
      navigate("/home"); // 네트워크 에러 후에도 홈으로 이동
    }
  };

  return (
    <div className="profile-page">
      <h1 className="profile-title">요리 프로필 생성</h1>

      <section className="profile-card">
        <div className="avatar-box">
          <img src={baby} alt="프로필" className="avatar-img" />
        </div>

        <input
          className="name-input"
          placeholder="이름을 입력해주세요."
          value={name}
          onChange={(e) => setName(e.target.value)}
        />

        <div className="toggle-row">
          <button
            type="button"
            className={`toggle-btn ${canUseFire ? "active-fire" : ""}`}
            onClick={() => setCanUseFire((v) => !v)}
          >
            <span>🔥</span>
            <span>자녀가 불을 사용할 수 있어요.</span>
          </button>

          <button
            type="button"
            className={`toggle-btn ${canUseKnife ? "active-knife" : ""}`}
            onClick={() => setCanUseKnife((v) => !v)}
          >
            <span>🔪</span>
            <span>자녀가 칼을 사용할 수 있어요.</span>
          </button>
        </div>

        <div className="allergy-header">
          <span>🚫</span>
          <span className="allergy-title">음식 알러지</span>
        </div>
        <div className="allergy-sub">자녀가 피해야 할 음식을 선택하세요.</div>

        <div className="allergy-list">
          {allergyOptions.map((opt) => {
            const selected = allergies.has(opt.key);
            return (
              <button
                key={opt.key}
                type="button"
                className={`allergy-item ${selected ? "selected" : ""}`}
                onClick={() => toggleAllergy(opt.key)}
                aria-pressed={selected}
              >
                <span className="emoji">{opt.emoji}</span>
                <span className="label">{opt.label}</span>
              </button>
            );
          })}
        </div>
      </section>

      <div className="submit-wrap">
        <button type="button" className="submit-btn" onClick={handleSubmit}>
          생성하기
        </button>
      </div>
    </div>
  );
}
