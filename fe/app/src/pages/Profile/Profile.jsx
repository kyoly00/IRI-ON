import React, { useState } from "react";
import "./Profile.css";
import baby from "../../assets/baby.png"; // 기본 아바타

export default function Profile() {
  const [name, setName] = useState("");
  const [canUseFire, setCanUseFire] = useState(false);
  const [canUseKnife, setCanUseKnife] = useState(false);
  const [allergies, setAllergies] = useState(new Set()); // 다중 선택

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
      name: name,                          // str
      can_use_fire: !!canUseFire,          // bool
      can_use_knife: !!canUseKnife,        // bool
      allergy: Array.from(allergies).join(",") || "", // str
    };

    // 시연용: 하드코딩(백엔드 8000 포트)
    const url = "http://localhost:8000/users/profile";
    console.log("→ POST", url, payload);

    try {
      const res = await fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          // 인증 필요 시:
          // "Authorization": `Bearer ${token}`
        },
        body: JSON.stringify(payload),
      });

      const raw = await res.text(); // 응답이 JSON 아닐 수도 있으니 텍스트 우선
      if (!res.ok) {
        console.error("❌ API 실패:", res.status, res.statusText, raw);
        alert(`프로필 생성 실패 (HTTP ${res.status})`);
        return;
      }

      let data = null;
      try { data = raw ? JSON.parse(raw) : null; } catch { data = raw; }

      console.log("✅ 프로필 생성 성공:", data);
      alert("프로필 생성 완료!");
      // TODO: 성공 후 이동 처리 (예: navigate("/home"))
    } catch (error) {
      console.error("❌ 네트워크/코르스 에러:", error);
      alert("프로필 생성 실패 (네트워크/CORS)");
    }
  };

  return (
    <div className="profile-page">
      <h1 className="profile-title">요리 프로필 생성</h1>

      <section className="profile-card">
        {/* 아바타 */}
        <div className="avatar-box">
          <img src={baby} alt="프로필" className="avatar-img" />
        </div>

        {/* 이름 */}
        <input
          className="name-input"
          placeholder="이름을 입력해주세요."
          value={name}
          onChange={(e) => setName(e.target.value)}
        />

        {/* 불/칼 사용 여부 */}
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

        {/* 알레르기 */}
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

      {/* 제출 */}
      <div className="submit-wrap">
        <button type="button" className="submit-btn" onClick={handleSubmit}>
          생성하기
        </button>
      </div>
    </div>
  );
}
