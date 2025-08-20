import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import "./Welcome2.css";
import baby from "../../assets/baby.png";

export default function Welcome2() {
  const nav = useNavigate();
  const loc = useLocation();

  // userId: navigate state 우선 → localStorage 백업
  const userIdFromState = loc.state && loc.state.userId;
  const [userId, setUserId] = useState(userIdFromState || localStorage.getItem("user_id") || "");

  useEffect(() => {
    if (userIdFromState) localStorage.setItem("user_id", String(userIdFromState));
  }, [userIdFromState]);

  // form states
  const [name, setName] = useState("");
  const [tools, setTools] = useState({
    can_use_fire: false,
    can_use_knife: false,
    can_use_scissors: false,
    can_use_peeler: false,
  });

  // 조리도구(명세 X → UI 전용)
  const [appliances, setAppliances] = useState(new Set());

  // 알레르기
  const allergyOptions = useMemo(
    () => ["우유", "계란", "땅콩", "새우", "밀", "호두", "메밀", "대두", "복숭아"],
    []
  );
  const [allergies, setAllergies] = useState([]);

  const toggleTool = (key) => setTools((prev) => ({ ...prev, [key]: !prev[key] }));
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

  const goFridge = () => nav("/fridge");

  const submitProfile = async () => {
    if (!userId) {
      alert("user_id가 없습니다. 로그인부터 진행해주세요.");
      return;
    }
    if (!name.trim()) {
      alert("이름을 입력해주세요.");
      return;
    }

    const payload = {
      name: name.trim(),
      ...tools,
      allergy: allergies.join(","),
    };

    try {
      const res = await fetch(`http://127.0.0.1:8000/users/profile?user_id=${userId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const t = await res.text();
        throw new Error(t || "프로필 생성 실패");
      }

      nav("/home");
    } catch (e) {
      console.error(e);
      alert("프로필 생성 중 오류가 발생했습니다.");
    }
  };

  return (
    <div className="w2-page">
      <header className="w2-header">
        <h1>요리 프로필 생성하기</h1>
        <p>더 자세히 알려주시면 가볍고 안전하고<br />최고의 맞춤 메뉴를 추천해 드릴게요!</p>
      </header>

      <section className="w2-hero">
        <img src={baby} alt="아바타" className="w2-avatar" />
        <input
          className="w2-name"
          type="text"
          placeholder="이름을 입력하세요"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </section>

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

      <section className="w2-card">
        <div className="w2-card-title"><span className="w2-emoji">⚠️</span> 피해야 할 음식이 있나요?</div>

        <div className="w2-select-row">
          <select
            className="w2-select"
            defaultValue=""
            onChange={(e) => {
              addAllergy(e.target.value);
              e.target.value = "";
            }}
          >
            <option value="" disabled>알레르기 음식을 선택하세요</option>
            {allergyOptions.map((opt) => (
              <option key={opt} value={opt}>{opt}</option>
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

        <button className="w2-submit" type="button" onClick={submitProfile}>
          생성하기
        </button>
      </section>
    </div>
  );
}
