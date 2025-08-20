import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import "./Profile_Modify.css";
import baby from "../../assets/baby.png";

// 레벨 이미지
import Lv1 from "../../assets/Level/Lv1.png";
import Lv2 from "../../assets/Level/Lv2.png";
import Lv3 from "../../assets/Level/Lv3.png";
import Lv4 from "../../assets/Level/Lv4.png";
import Lv5 from "../../assets/Level/Lv5.png";
import Lv6 from "../../assets/Level/Lv6.png";
import Lv7 from "../../assets/Level/Lv7.png";
import Lv8 from "../../assets/Level/Lv8.png";
import Lv9 from "../../assets/Level/Lv9.png";
import Lv10 from "../../assets/Level/Lv10.png";

export default function ProfileModify() {
  const nav = useNavigate();
  const loc = useLocation();

  // 이름: 표시만(입력 X) — localStorage → location.state → 기본값
  const [name, setName] = useState("셰프얌");

  // 레벨 목록(가로 스크롤)
  const LEVELS = useMemo(
    () => [
      { value: 1, title: "요린이", img: Lv1 },
      { value: 2, title: "주방 탐험가", img: Lv2 },
      { value: 3, title: "라면 박사", img: Lv3 },
      { value: 4, title: "볶음밥의 지배자", img: Lv4 },
      { value: 5, title: "고기 지옥의 장인", img: Lv5 },
      { value: 6, title: "김밥집 사장님", img: Lv6 },
      { value: 7, title: "맛의 연금술사", img: Lv7 },
      { value: 8, title: "요리 전문가", img: Lv8 },
      { value: 9, title: "요리 마스터", img: Lv9 },
      { value: 10, title: "요리의 신", img: Lv10 },
    ],
    []
  );

  // 선택 레벨
  const [level, setLevel] = useState(() => {
    const saved = Number(localStorage.getItem("profile_level") || "4");
    return saved >= 1 && saved <= 10 ? saved : 4;
  });

  // 도구/조리도구/알레르기 — UI 전용(로컬 저장)
  const [tools, setTools] = useState({
    can_use_fire: false,
    can_use_knife: false,
    can_use_scissors: false,
    can_use_peeler: false,
  });
  const [appliances, setAppliances] = useState(new Set());
  const allergyOptions = useMemo(
    () => ["우유", "계란", "땅콩", "새우", "밀", "호두", "메밀", "대두", "복숭아"],
    []
  );
  const [allergies, setAllergies] = useState([]);

  // 초기 프리필
  useEffect(() => {
    const n =
      localStorage.getItem("profile_name") ??
      loc.state?.name ??
      "셰프얌";
    setName(n);

    try {
      const savedTools = JSON.parse(localStorage.getItem("profile_tools") || "null");
      if (savedTools) setTools((prev) => ({ ...prev, ...savedTools }));
    } catch {}

    try {
      const savedAppliances = JSON.parse(localStorage.getItem("profile_appliances") || "[]");
      setAppliances(new Set(savedAppliances));
    } catch {}

    try {
      const savedAllergies = JSON.parse(localStorage.getItem("profile_allergies") || "[]");
      if (Array.isArray(savedAllergies)) setAllergies(savedAllergies);
    } catch {}
  }, [loc.state]);

  // 토글 핸들러
  const toggleTool = (key) => setTools((p) => ({ ...p, [key]: !p[key] }));
  const toggleAppliance = (item) =>
    setAppliances((prev) => {
      const n = new Set(prev);
      n.has(item) ? n.delete(item) : n.add(item);
      return n;
    });
  const addAllergy = (item) => {
    if (!item) return;
    setAllergies((prev) => (prev.includes(item) ? prev : [...prev, item]));
  };
  const removeAllergy = (item) => setAllergies((prev) => prev.filter((x) => x !== item));

  // 저장 후 홈으로
  const saveAndGoHome = () => {
    localStorage.setItem("profile_name", name);
    localStorage.setItem("profile_level", String(level));
    localStorage.setItem("profile_tools", JSON.stringify(tools));
    localStorage.setItem("profile_appliances", JSON.stringify(Array.from(appliances)));
    localStorage.setItem("profile_allergies", JSON.stringify(allergies));
    nav("/home");
  };

  const goFridge = () => nav("/fridge");

  return (
    <div className="w2-page">
      <header className="w2-header">
        <h1>요리 프로필 수정하기</h1>
        <p>
          더 자세히 알려주시면 가볍고 안전하고
          <br />
          최고의 맞춤 메뉴를 추천해 드리겠습니다!
        </p>
      </header>

      {/* 아바타 + 이름(표시만) */}
      <section className="w2-hero w2-hero-center">
        <div className="w2-hero-col">
          <img src={baby} alt="아바타" className="w2-avatar" />
          <div className="w2-name-display">{name}</div>
        </div>
      </section>

      {/* 레벨 선택 — 가로 스크롤 */}
      <section className="w2-card">
        <div className="w2-card-title">
          <span className="w2-emoji">🎯</span> 나의 요리 성장 레벨! : <b>Lv.{level}</b>
        </div>

        <div className="w2-levels-row">
          {LEVELS.map((lv) => (
            <button
              key={lv.value}
              type="button"
              className={`w2-level-h ${level === lv.value ? "active" : ""}`}
              onClick={() => setLevel(lv.value)}
              aria-pressed={level === lv.value}
            >
              <div className="w2-level-badge">Lv. {lv.value}</div>
              <img className="w2-level-img" src={lv.img} alt={lv.title} loading="lazy" />
              <div className="w2-level-title">{lv.title}</div>
            </button>
          ))}
        </div>
      </section>

      {/* 도구 사용 가능 여부 */}
      <section className="w2-card">
        <div className="w2-card-title">
          <span className="w2-emoji">🛡️</span> 아래의 도구를 안전하게 사용할 수 있나요?
        </div>

        <div className="w2-grid-2">
          <button
            className={`w2-tool ${tools.can_use_fire ? "active" : ""}`}
            onClick={() => toggleTool("can_use_fire")}
            type="button"
          >
            <div className="w2-icon">🔥</div>
            <div className="w2-tool-title">불</div>
            <div className="w2-tool-sub">가스레인지</div>
          </button>

          <button
            className={`w2-tool ${tools.can_use_knife ? "active" : ""}`}
            onClick={() => toggleTool("can_use_knife")}
            type="button"
          >
            <div className="w2-icon">🔪</div>
            <div className="w2-tool-title">칼</div>
            <div className="w2-tool-sub">날카로운 도구</div>
          </button>

          <button
            className={`w2-tool ${tools.can_use_scissors ? "active" : ""}`}
            onClick={() => toggleTool("can_use_scissors")}
            type="button"
          >
            <div className="w2-icon">✂️</div>
            <div className="w2-tool-title">가위</div>
            <div className="w2-tool-sub">주방 가위</div>
          </button>

          <button
            className={`w2-tool ${tools.can_use_peeler ? "active" : ""}`}
            onClick={() => toggleTool("can_use_peeler")}
            type="button"
          >
            <div className="w2-icon">🥕</div>
            <div className="w2-tool-title">껍질 벗기는 칼</div>
            <div className="w2-tool-sub">예: 감자칼</div>
          </button>
        </div>
      </section>

      {/* 조리도구 (UI 전용) */}
      <section className="w2-card">
        <div className="w2-card-title">어떤 조리도구를 가지고 있나요?</div>
        <div className="w2-grid-3">
          {["전자레인지", "에어프라이어", "오븐", "전기밥솥", "믹서기", "그릴"].map((a) => (
            <button
              key={a}
              type="button"
              className={`w2-appliance ${appliances.has(a) ? "selected" : ""}`}
              onClick={() => toggleAppliance(a)}
            >
              {a}
            </button>
          ))}
        </div>

        <button type="button" className="w2-inline-cta" onClick={goFridge}>
          나만의 냉장고 만들기 →
        </button>
      </section>

      {/* 알레르기 */}
      <section className="w2-card">
        <div className="w2-card-title">
          <span className="w2-emoji">⚠️</span> 피해야 할 음식이 있나요?
        </div>

        <div className="w2-select-row">
          <select
            className="w2-select"
            defaultValue=""
            onChange={(e) => {
              addAllergy(e.target.value);
              e.target.value = "";
            }}
          >
            <option value="" disabled>
              알레르기 음식을 선택하세요
            </option>
            {allergyOptions.map((opt) => (
              <option key={opt} value={opt}>
                {opt}
              </option>
            ))}
          </select>
        </div>

        {allergies.length > 0 && (
          <div className="w2-chips">
            {allergies.map((a) => (
              <span className="w2-chip" key={a} onClick={() => removeAllergy(a)}>
                {a} ✕
              </span>
            ))}
          </div>
        )}

        <button className="w2-submit" type="button" onClick={saveAndGoHome}>
          수정하기
        </button>
      </section>
    </div>
  );
}
