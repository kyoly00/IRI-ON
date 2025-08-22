import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import "./Profile_modify.css";
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

  // ✅ userId: state > localStorage > ""
  const userIdFromState = loc.state?.userId || null;
  const [userId, setUserId] = useState(
    userIdFromState || localStorage.getItem("user_id") || ""
  );
  useEffect(() => {
    if (userIdFromState) {
      localStorage.setItem("user_id", String(userIdFromState));
      setUserId(String(userIdFromState));
    }
  }, [userIdFromState]);

  // ✅ 이름(표시만) : localStorage → state → 기본값
  const [name, setName] = useState(
    localStorage.getItem("user_name") || loc.state?.name || "셰프얌"
  );

  // === 레벨 목록(가로 스크롤) ===
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
  const [level, setLevel] = useState(() => {
    const saved = Number(localStorage.getItem("profile_level") || "4");
    return saved >= 1 && saved <= 10 ? saved : 4;
  });
  const pickLevel = (v) => {
    setLevel(v);
    localStorage.setItem("profile_level", String(v)); // DB 전송 없음
  };

  // === 안전 도구 ===
  const [tools, setTools] = useState({
    can_use_fire: false,
    can_use_knife: false,
    can_use_scissors: false,
    can_use_peeler: false,
  });
  const toggleTool = (key) =>
    setTools((prev) => ({ ...prev, [key]: !prev[key] }));

  // === 보유 도구 ===
  const [toolsList, setToolsList] = useState([]);           // [{tool_id, name}]
  const [selectedTools, setSelectedTools] = useState(new Set());
  const toggleAppliance = (toolId) => {
    setSelectedTools((prev) => {
      const n = new Set(prev);
      n.has(toolId) ? n.delete(toolId) : n.add(toolId);
      return n;
    });
  };

  // === 알레르기 ===
  const allergyOptions = useMemo(
    () => ["우유", "계란", "땅콩", "새우", "밀", "호두", "메밀", "대두", "복숭아"],
    []
  );
  const [allergies, setAllergies] = useState([]);
  const addAllergy = (item) => {
    if (!item) return;
    setAllergies((prev) => (prev.includes(item) ? prev : [...prev, item]));
  };
  const removeAllergy = (item) =>
    setAllergies((prev) => prev.filter((x) => x !== item));

  const goFridge = () => nav("/fridge");

  // ✅ 저장 토스트(페이지 유지)
  const [showToast, setShowToast] = useState(false);

  // === 초기 데이터 로드 ===
  useEffect(() => {
    const load = async () => {
      try {
        const resTools = await fetch("http://127.0.0.1:8000/tools");
        if (resTools.ok) setToolsList(await resTools.json());

        if (userId) {
          const resProfile = await fetch(
            `http://127.0.0.1:8000/users/profile?user_id=${userId}`
          );
          if (resProfile.ok) {
            const p = await resProfile.json();
            if (p?.name) setName(p.name);
            setTools({
              can_use_fire: !!p?.can_use_fire,
              can_use_knife: !!p?.can_use_knife,
              can_use_scissors: !!p?.can_use_scissors,
              can_use_peeler: !!p?.can_use_peeler,
            });
            const parsed =
              typeof p?.allergy === "string"
                ? p.allergy.split(",").map((s) => s.trim()).filter(Boolean)
                : [];
            setAllergies(parsed);
          }

          const resMyTools = await fetch(
            `http://127.0.0.1:8000/users/tools?user_id=${userId}`
          );
          if (resMyTools.ok) {
            const my = await resMyTools.json();
            const ids = Array.isArray(my)
              ? my
                  .map((x) =>
                    typeof x === "number" ? x : x?.tool_id ?? x?.id ?? null
                  )
                  .filter((v) => Number.isInteger(v))
              : [];
            setSelectedTools(new Set(ids));
          }
        }
      } catch (e) {
        console.error(e);
      }
    };
    load();
  }, [userId]);

  // === 저장(서버 반영) – 페이지/상태 유지(하이라이트 그대로) ===
  const submitProfile = async () => {
    if (!userId) return alert("user_id가 없습니다. 로그인부터 진행해주세요.");
    try {
      const profilePayload = {
        name,
        ...tools,
        allergy: allergies.join(","),
      };
      const res1 = await fetch(
        `http://127.0.0.1:8000/users/profile?user_id=${userId}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(profilePayload),
        }
      );
      if (!res1.ok) throw new Error("프로필 저장 실패");

      const toolPayload = Array.from(selectedTools).map((id) => ({ tool_id: id }));
      const res2 = await fetch(
        `http://127.0.0.1:8000/users/tools?user_id=${userId}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(toolPayload),
        }
      );
      if (!res2.ok) throw new Error("도구 저장 실패");

      // ✅ 여기서 상태 변화 없음 → 기존 active/selected 색상 그대로 유지됨
      setShowToast(true);
      setTimeout(() => setShowToast(false), 1500);
    } catch (e) {
      console.error(e);
      alert("프로필/도구 저장 중 오류: " + e.message);
    }
  };

  return (
    <div className="pm-page">
      <header className="pm-header">
        <h1>요리 프로필 수정하기</h1>
        <p>
          더 자세히 알려주시면 가볍고 안전하고
          <br />
          최고의 맞춤 메뉴를 추천해 드립니다!
        </p>
      </header>

      {/* 상단 아바타 + 이름(표시만) */}
      <section className="pm-hero-center">
        <img src={baby} alt="아바타" className="pm-avatar-lg" />
        <div className="pm-name-pill">{name}</div>
      </section>

      {/* === 요리 레벨 선택(로컬 저장만) === */}
      <section className="pm-card">
        <div className="pm-card-title">
          🎯 나의 요리 성장 레벨 : <b>Lv.{level}</b>
        </div>
        <div className="pm-levels" role="listbox" aria-label="요리 레벨 선택">
          {LEVELS.map((it) => (
            <button
              key={it.value}
              type="button"
              className={`pm-level-card ${level === it.value ? "selected" : ""}`}
              onClick={() => pickLevel(it.value)}
              aria-selected={level === it.value}
            >
              <span className="pm-level-badge">Lv.{it.value}</span>
              <img src={it.img} alt={it.title} className="pm-level-img" />
              <div className="pm-level-title">{it.title}</div>
            </button>
          ))}
        </div>
      </section>

      {/* === 안전 도구 === */}
      <section className="pm-card">
        <div className="pm-card-title">
          <span className="pm-emoji">🛡️</span> 아래의 도구를 안전하게 사용할 수 있나요?
        </div>
        <div className="pm-grid-2">
          <button
            className={`pm-tool ${tools.can_use_fire ? "active" : ""}`}
            onClick={() => toggleTool("can_use_fire")}
            type="button"
          >
            <div className="pm-icon">🔥</div>
            <div className="pm-tool-title">불</div>
            <div className="pm-tool-sub">가스레인지</div>
          </button>

          <button
            className={`pm-tool ${tools.can_use_knife ? "active" : ""}`}
            onClick={() => toggleTool("can_use_knife")}
            type="button"
          >
            <div className="pm-icon">🔪</div>
            <div className="pm-tool-title">칼</div>
            <div className="pm-tool-sub">날카로운 도구</div>
          </button>

          <button
            className={`pm-tool ${tools.can_use_scissors ? "active" : ""}`}
            onClick={() => toggleTool("can_use_scissors")}
            type="button"
          >
            <div className="pm-icon">✂️</div>
            <div className="pm-tool-title">가위</div>
            <div className="pm-tool-sub">주방 가위</div>
          </button>

          <button
            className={`pm-tool ${tools.can_use_peeler ? "active" : ""}`}
            onClick={() => toggleTool("can_use_peeler")}
            type="button"
          >
            <div className="pm-icon">🥕</div>
            <div className="pm-tool-title">껍질 벗기는 칼</div>
            <div className="pm-tool-sub">예: 감자칼</div>
          </button>
        </div>
      </section>

      {/* === 보유 도구 === */}
      <section className="pm-card">
        <div className="pm-card-title">어떤 조리도구를 가지고 있나요?</div>
        <div className="pm-grid-3">
          {toolsList.map((tool) => (
            <button
              key={tool.tool_id}
              type="button"
              className={`pm-appliance ${
                selectedTools.has(tool.tool_id) ? "selected" : ""
              }`}
              onClick={() => toggleAppliance(tool.tool_id)}
            >
              {tool.name}
            </button>
          ))}
        </div>

        <button type="button" className="pm-inline-cta" onClick={goFridge}>
          나만의 냉장고 만들기 →
        </button>
      </section>

      {/* === 알레르기 === */}
      <section className="pm-card">
        <div className="pm-card-title">
          <span className="pm-emoji">⚠️</span> 피해야 할 음식이 있나요?
        </div>

        <div className="pm-select-row">
          <select
            className="pm-select"
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
          <div className="pm-chips">
            {allergies.map((a) => (
              <span className="pm-chip" key={a} onClick={() => removeAllergy(a)}>
                {a} ✕
              </span>
            ))}
          </div>
        )}

        <button className="pm-submit" type="button" onClick={submitProfile}>
          수정하기
        </button>
      </section>

      {showToast && <div className="pm-save-toast">수정 완료! 저장됨</div>}
    </div>
  );
}
