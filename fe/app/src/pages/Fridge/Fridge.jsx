import React, { useEffect, useMemo, useState } from "react";
import "./Fridge.css";
import { useNavigate } from "react-router-dom";
import { FaSearch, FaClock } from "react-icons/fa";

const API_BASE = "http://127.0.0.1:8000";

export default function Fridge() {
  const [ingredients, setIngredients] = useState([]);
  const [selected, setSelected] = useState([]);
  const [searchTerm, setSearchTerm] = useState("");
  const [loading, setLoading] = useState(true);
  const [errMsg, setErrMsg] = useState("");

  const navigate = useNavigate();

  // 날짜 포맷: 08.26 화
  const dateLabel = useMemo(() => {
    const d = new Date();
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    const dd = String(d.getDate()).padStart(2, "0");
    const weekdays = ["일", "월", "화", "수", "목", "금", "토"];
    const wd = weekdays[d.getDay()];
    return `${mm}.${dd} ${wd}`;
  }, []);

  // 백엔드 연동
  useEffect(() => {
    const ac = new AbortController();
    (async () => {
      try {
        setLoading(true);
        setErrMsg("");
        const res = await fetch(`${API_BASE}/ingredients/`, { signal: ac.signal });
        if (!res.ok) throw new Error(`서버 응답 오류 (${res.status})`);
        const data = await res.json();
        setIngredients(Array.isArray(data) ? data : []);
      } catch (err) {
        if (err.name !== "AbortError") {
          console.error("❌ 재료 불러오기 실패:", err);
          setErrMsg("재료 목록을 불러오지 못했습니다.");
        }
      } finally {
        setLoading(false);
      }
    })();
    return () => ac.abort();
  }, []);

  // 선택 토글
  const toggleSelect = (id) => {
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  // 생성하기 버튼
  const goToComplete = () => {
    navigate("/fridgeComplete", { state: { selected } });
  };

  // 검색 필터 (공백/대소문자 무시)
  const filteredIngredients = useMemo(() => {
    const q = searchTerm.trim().toLowerCase();
    if (!q) return ingredients;
    return ingredients.filter((item) => String(item.name).toLowerCase().includes(q));
  }, [ingredients, searchTerm]);

  return (
    <div className="fridge-page">
      {/* ===== 헤더 ===== */}
      <header className="fridge-header">
        <h1 className="fridge-title">냉장고 만들기</h1>
        <p className="fridge-desc">
          냉장고 속 재료를 선택하고,
          <br />
          메뉴를 추천받으세요!
        </p>

        {/* 날짜 */}
        <div className="date-chip">
          <FaClock aria-hidden style={{ marginRight: 6 }} />
          {dateLabel}
        </div>

        {/* 검색창 */}
        <div className="search-box">
          <FaSearch className="search-icon" aria-hidden />
          <input
            type="text"
            placeholder="재료를 검색하세요."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            aria-label="재료 검색"
          />
        </div>
      </header>

      {/* ===== 본문 ===== */}
      <main className="fridge-content">
        {loading ? (
          <div className="empty-state">불러오는 중...</div>
        ) : errMsg ? (
          <div className="empty-state error">{errMsg}</div>
        ) : filteredIngredients.length === 0 ? (
          <div className="empty-state">표시할 재료가 없어요.</div>
        ) : (
          <div className="ingredient-grid">
            {filteredIngredients.map((item) => {
              const id = item.ingredient_id;
              const isSelected = selected.includes(id);
              return (
                <button
                  key={id}
                  type="button"
                  className={`ingredient-card ${isSelected ? "selected" : ""}`}
                  onClick={() => toggleSelect(id)}
                  aria-pressed={isSelected}
                >
                  <span className="ingredient-name">{item.name}</span>
                </button>
              );
            })}
          </div>
        )}
      </main>

      {/* ===== 푸터 ===== */}
      <footer className="fridge-footer">
        <button
          onClick={goToComplete}
          disabled={selected.length === 0}
          className="create-btn"
          aria-disabled={selected.length === 0}
          title={selected.length === 0 ? "재료를 하나 이상 선택하세요" : undefined}
        >
          생성하기{selected.length > 0 ? ` (${selected.length})` : ""}
        </button>
      </footer>

      {/* ⛔️ 페이지 내부 bottom-nav는 제거 (MainLayout에서 렌더링되도록) */}
    </div>
  );
}
