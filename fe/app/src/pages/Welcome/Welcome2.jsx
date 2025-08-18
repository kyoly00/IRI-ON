import React, { useMemo, useRef, useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import "./Welcome2.css";

import baby from "../../assets/baby.png";
import Lv1 from "../../assets/Lv1.png";
import Lv2 from "../../assets/Lv2.png";
import Lv3 from "../../assets/Lv3.png";

export default function Welcome2() {
  const navigate = useNavigate();

  // ---------------- state ----------------
  const [name, setName] = useState("홍석진");

  // 도구 안전 사용 (불/칼/가위/필러)
  const [safeTools, setSafeTools] = useState({
    fire: false,
    knife: false,
    scissors: false,
    peeler: false,
  });

  // 보유 조리도구
  const [hasTools, setHasTools] = useState(new Set());

  // 요리 레벨
  const [level, setLevel] = useState(null); // 1 | 2 | 3

  // 알러지 (칩 + 드롭다운)
  const allergyOptions = [
    { key: "peanut", label: "땅콩" },
    { key: "milk", label: "우유" },
    { key: "egg", label: "계란" },
    { key: "shrimp", label: "새우" },
    { key: "banana", label: "바나나" },
  ];
  const [allergies, setAllergies] = useState(new Set(["peanut", "milk"]));
  const [openAllergy, setOpenAllergy] = useState(false);

  // 드롭다운 위/아래 방향 결정
  const [ddUp, setDdUp] = useState(false);
  const ddRef = useRef(null);

  // 바깥 클릭시 드롭다운 닫기
  useEffect(() => {
    const close = (e) => {
      if (!ddRef.current) return;
      if (!ddRef.current.contains(e.target)) setOpenAllergy(false);
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, []);

  const toggleSafeTool = (key) =>
    setSafeTools((s) => ({ ...s, [key]: !s[key] }));

  const toggleHasTool = (key) => {
    const next = new Set(hasTools);
    next.has(key) ? next.delete(key) : next.add(key);
    setHasTools(next);
  };

  const toggleAllergy = (key) => {
    const next = new Set(allergies);
    next.has(key) ? next.delete(key) : next.add(key);
    setAllergies(next);
  };

  const selectedAllergiesText = useMemo(() => {
    const arr = allergyOptions
      .filter((o) => allergies.has(o.key))
      .map((o) => o.label);
    return arr.join(", ");
  }, [allergies]);

  // 드롭다운 열 때 방향 계산
  const onToggleDropdown = () => {
    setOpenAllergy((prev) => {
      const next = !prev;
      if (next) {
        requestAnimationFrame(() => {
          if (!ddRef.current) return;
          const rect = ddRef.current.getBoundingClientRect();
          const spaceBelow = window.innerHeight - rect.bottom;
          // 옵션 높이 예상치(약 264px)보다 공간이 작으면 위로
          setDdUp(spaceBelow < 280);
        });
      }
      return next;
    });
  };

  // ---------------- submit (항상 /home 이동) ----------------
  const handleSubmit = async () => {
    const payload = {
      name,
      can_use_fire: !!safeTools.fire,
      can_use_knife: !!safeTools.knife,
      allergy: Array.from(allergies).join(","),
      // 레벨/도구도 필요하면 여기에 추가
    };

    try {
      const res = await fetch("http://localhost:8000/users/profile", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        alert(`프로필 생성 실패 (HTTP ${res.status})`);
      } else {
        let raw = await res.text();
        try { JSON.parse(raw); } catch (_) {}
        alert("프로필 생성 완료!");
      }
    } catch (e) {
      console.error("네트워크/CORS 오류:", e);
      alert("프로필 생성 실패 (네트워크/CORS)");
    } finally {
      navigate("/home"); // ✅ 성공/실패 관계없이 이동
    }
  };

  // ---------------- UI ----------------
  return (
    <div className="profile-page">
      {/* 헤더 */}
      <header className="header">
        <h1 className="title">요리 프로필 생성</h1>
        <p className="subtitle">
          <span className="linkish">더 자세히 알려주시면 가장 안전하고</span>
          <br />
          <span className="linkish">최고의 맞춤형 메뉴를 추천해 드리겠습니다!</span>
        </p>

        <div className="avatar-ring">
          <img src={baby} alt="프로필 아바타" />
        </div>
        <div className="child-name">{name}</div>
      </header>

      {/* 1) 안전 도구 사용 */}
      <section className="section">
        <h2 className="section-label">
          <span className="icon-orange">🔶</span>
          아래의 도구를 안전하게 사용할 수 있나요?
        </h2>

        <div className="cards-2col">
          <SafetyCard
            active={safeTools.fire}
            onClick={() => toggleSafeTool("fire")}
            icon="🔥"
            title="불"
            descTop="가스레인지"
          />
          <SafetyCard
            active={safeTools.knife}
            onClick={() => toggleSafeTool("knife")}
            icon="🍴"
            title="칼"
            descTop="날카로운 도구"
          />
          <SafetyCard
            active={safeTools.scissors}
            onClick={() => toggleSafeTool("scissors")}
            icon="✂️"
            title="가위"
            descTop="주방 가위"
          />
          <SafetyCard
            active={safeTools.peeler}
            onClick={() => toggleSafeTool("peeler")}
            icon="🥕"
            title="껍질을 벗기는 칼"
            descTop="예: 감자칼"
          />
        </div>
      </section>

      {/* 2) 보유 조리도구 */}
      <section className="section">
        <h2 className="section-label">
          <span className="icon-orange">🧰</span>
          어떤 조리도구를 가지고 있나요?
        </h2>

        <div className="grid-tools">
          {[
            { k: "steamer", t: "찜기", e: "🍲" },
            { k: "airfryer", t: "에어프라이어", e: "🍟" },
            { k: "oven", t: "오븐", e: "🍞" },
            { k: "microwave", t: "전자레인지", e: "📡" },
            { k: "bag", t: "비닐봉지", e: "🛍️" },
            { k: "bowl", t: "그릇", e: "🥣" },
          ].map((it) => (
            <button
              key={it.k}
              type="button"
              className={`tool-chip ${hasTools.has(it.k) ? "on" : ""}`}
              onClick={() => toggleHasTool(it.k)}
            >
              <span className="t-emoji">{it.e}</span>
              <span className="t-text">{it.t}</span>
            </button>
          ))}
        </div>
      </section>

      {/* 3) 냉장고 만들기 CTA */}
      <section className="section">
        <h2 className="section-label">
          <span className="icon-orange">🧊</span>
          나만의 냉장고를 만들어주세요!
        </h2>

        <button
          className="fridge-cta"
          type="button"
          onClick={() => navigate("/fridge")}
        >
          <span>나만의 냉장고 만들기</span>
          <span className="arrow">→</span>
        </button>
      </section>

      {/* 4) 요리 레벨 선택 */}
      <section className="section">
        <h2 className="section-label">
          <span className="icon-orange">🍳</span>
          요리 레벨을 선택해 주세요!
        </h2>

        <div className="levels">
          <LevelCard
            lvl={1}
            active={level === 1}
            onSelect={() => setLevel(1)}
            img={Lv1}
            title="요린이"
            desc="카나페, 과일꼬치, 요거트볼"
          />
          <LevelCard
            lvl={2}
            active={level === 2}
            onSelect={() => setLevel(2)}
            img={Lv2}
            title="주방 탐험가"
            desc="전자레인지 계란빵, 콘치즈, 토스트"
          />
          <LevelCard
            lvl={3}
            active={level === 3}
            onSelect={() => setLevel(3)}
            img={Lv3}
            title="라면 박사"
            desc="라면, 계란 볶음밥 등"
          />
        </div>
      </section>

      {/* 5) 알러지 */}
      <section className="section">
        <h2 className="section-label">
          <span className="icon-red">⚠️</span>
          피해야 할 음식이 있나요?
        </h2>

        {/* 선택 칩 */}
        <div className="chips">
          {Array.from(allergies).map((k) => {
            const lab = allergyOptions.find((o) => o.key === k)?.label ?? k;
            return (
              <button
                key={k}
                type="button"
                className="chip on"
                onClick={() => toggleAllergy(k)}
                aria-pressed="true"
              >
                {lab} <span className="x">×</span>
              </button>
            );
          })}
        </div>

        {/* 커스텀 드롭다운 */}
        <div className="dropdown" ref={ddRef}>
          <button
            type="button"
            className={`dd-input ${openAllergy ? "open" : ""}`}
            onClick={onToggleDropdown}
            aria-haspopup="listbox"
            aria-expanded={openAllergy}
          >
            <span className={selectedAllergiesText ? "" : "muted"}>
              {selectedAllergiesText || "알러지 음식을 선택하세요"}
            </span>
            <span className="chev">▾</span>
          </button>

          {openAllergy && (
            <div className={`dd-menu ${ddUp ? "up" : ""}`} role="listbox">
              {allergyOptions.map((opt) => {
                const on = allergies.has(opt.key);
                return (
                  <button
                    key={opt.key}
                    className={`dd-item ${on ? "on" : ""}`}
                    onClick={() => toggleAllergy(opt.key)}
                    type="button"
                    role="option"
                    aria-selected={on}
                  >
                    {opt.label}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </section>

      {/* 하단 CTA */}
      <div className="submit-wrap">
        <button className="submit-btn" type="button" onClick={handleSubmit}>
          생성하기
        </button>
      </div>
    </div>
  );
}

/* ---------------- components ---------------- */

function SafetyCard({ active, onClick, icon, title, descTop }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`safety-card ${active ? "on" : ""}`}
      aria-pressed={active}
    >
      <div className="s-icon">{icon}</div>
      <div className="s-title">{title}</div>
      <div className="s-desc">{descTop}</div>
    </button>
  );
}

function LevelCard({ lvl, active, onSelect, img, title, desc }) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`level-card ${active ? "active" : ""}`}
      aria-pressed={active}
    >
      <div className="lv-badge">Lv. {lvl}</div>
      <img className="lv-img" src={img} alt={`레벨 ${lvl}`} />
      <div className="lv-title">{title}</div>
      <div className="lv-desc">{desc}</div>
    </button>
  );
}
