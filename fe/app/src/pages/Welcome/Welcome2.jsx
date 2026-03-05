import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import "./Welcome2.css";
import baby from "../../assets/baby.png";

export default function Welcome2() {
  const nav = useNavigate();
  const loc = useLocation();

  // ✅ userId 가져오기 (state > localStorage > "")
  const userIdFromState = loc.state?.userId || null;
  const [userId, setUserId] = useState(
    userIdFromState || localStorage.getItem("user_id") || ""
  );

  // ✅ state로 받은 경우 localStorage 갱신
  useEffect(() => {
    if (userIdFromState) {
      localStorage.setItem("user_id", String(userIdFromState));
      setUserId(String(userIdFromState));
    }
  }, [userIdFromState]);

  // form states
  const [name, setName] = useState("");

  // === UserProfile: 불/칼/가위/필러 사용 여부 ===
  const [tools, setTools] = useState({
    can_use_fire: false,
    can_use_knife: false,
    can_use_scissors: false,
    can_use_peeler: false,
  });
  const toggleTool = (key) =>
    setTools((prev) => ({ ...prev, [key]: !prev[key] }));

  // === 보유 도구 (API 기반) ===
  const [toolsList, setToolsList] = useState([]);
  const [selectedTools, setSelectedTools] = useState(new Set());

  useEffect(() => {
    const fetchTools = async () => {
      try {
        const res = await fetch("http://127.0.0.1:8000/tools");
        if (!res.ok) throw new Error("도구 불러오기 실패");
        const data = await res.json();
        setToolsList(data); // [{tool_id:1, name:"에어프라이어"}, ...]
      } catch (err) {
        console.error(err);
      }
    };
    fetchTools();
  }, []);

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

  // === 프로필 + 선택 도구 전송 ===
  const submitProfile = async () => {
    if (!userId) {
      alert("user_id가 없습니다. 로그인부터 진행해주세요.");
      return;
    }
    if (!name.trim()) {
      alert("이름을 입력해주세요.");
      return;
    }

    try {
      // 1) 프로필 저장
      const profilePayload = {
        name: name.trim(),
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
      if (!res1.ok) throw new Error("프로필 생성 실패");

      // 2) 선택 도구 저장
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

      nav("/home");
    } catch (e) {
      console.error(e);
      alert("프로필/도구 저장 중 오류 발생: " + e.message);
    }
  };

  return (
    <div className="w2-page">
      <header className="w2-header">
        <h1>요리 프로필 생성하기</h1>
        <p>
          더 자세히 알려주시면 가볍고 안전하고
          <br />
          최고의 맞춤 메뉴를 추천해 드릴게요!
        </p>
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

      {/* === 안전성 도구 === */}
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

      {/* === 보유 도구 === */}
      <section className="w2-card">
        <div className="w2-card-title">어떤 조리도구를 가지고 있나요?</div>
        <div className="w2-grid-3">
          {toolsList.map((tool) => (
            <button
              key={tool.tool_id}
              type="button"
              className={`w2-appliance ${
                selectedTools.has(tool.tool_id) ? "selected" : ""
              }`}
              onClick={() => toggleAppliance(tool.tool_id)}
            >
              {tool.name}
            </button>
          ))}
        </div>

        <button type="button" className="w2-inline-cta" onClick={goFridge}>
          나만의 냉장고 만들기 →
        </button>
      </section>

      {/* === 알레르기 === */}
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

        <button className="w2-submit" type="button" onClick={submitProfile}>
          생성하기
        </button>

        {/* ▼ 하단 제스처바/네비바에 가리지 않게 스페이서 */}
        <div className="w2-safe-bottom" aria-hidden />
      </section>
    </div>
  );
}
