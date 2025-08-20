import React, { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import "./Home.css";
import topLogo from "../../assets/top_logo.png";
import chef3d from "../../assets/3dLogo.png";
import ment from "../../assets/ment.png";
import { FiSearch, FiHeart, FiBell, FiClock } from "react-icons/fi";

const API_BASE = "http://localhost:8000"; // Menu.jsx와 동일하게

export default function Home() {
  const nav = useNavigate();

  // 카테고리
  const categories = ["한식", "중식", "일식", "양식"];
  const [activeCat, setActiveCat] = useState("한식");

  // 서버 데이터
  const [menus, setMenus] = useState([]);   // 항상 배열로 유지
  const [loading, setLoading] = useState(false);
  const [errMsg, setErrMsg] = useState("");

  // 카테고리 바뀔 때마다 백엔드에서 가져오기
  useEffect(() => {
    const ac = new AbortController();

    (async () => {
      try {
        setLoading(true);
        setErrMsg("");

        const qs = new URLSearchParams();
        // 백엔드가 category 필터를 지원하면 유지, 아니면 이 줄 제거
        qs.set("category", activeCat);

        const res = await fetch(`${API_BASE}/recipes/?${qs.toString()}`, {
          signal: ac.signal,
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        const data = await res.json();
        setMenus(Array.isArray(data) ? data : []);
      } catch (e) {
        if (e.name !== "AbortError") {
          console.error("Home fetch error:", e);
          setErrMsg("메뉴를 불러오지 못했어요.");
          setMenus([]); // 흰화면 방지
        }
      } finally {
        setLoading(false);
      }
    })();

    return () => ac.abort();
  }, [activeCat]);

  // 홈에서 보여줄 카드 2개만 추려서, 필드명 방어적으로 매핑
  const cards = useMemo(() => {
    return menus.slice(0, 2).map((m, i) => ({
      key: m.recipe_id ?? m.id ?? i,
      name: m.name ?? "메뉴",
      time: m.time ?? m.cook_time ?? 0,
      image: m.image_url ?? "",
    }));
  }, [menus]);

  const goMenu = (opt = {}) => nav("/menu", { state: opt });
  const goFridge = () => nav("/fridge");

  return (
    <div className="home-page">
      {/* 상단 바 */}
      <div className="home-top">
        <img className="home-logo" src={topLogo} alt="CHEF YUM" />
        <div className="home-actions">
          <FiSearch onClick={() => goMenu()} />
          <FiHeart />
          <FiBell />
        </div>
      </div>

      {/* 히어로: 캐릭터 + 멘트 */}
      <section className="hero">
        <img className="hero-chef" src={chef3d} alt="셰프 캐릭터" loading="lazy" />
        <img className="hero-ment" src={ment} alt="환영 멘트" loading="lazy" />
      </section>

      {/* 인기 메뉴 */}
      <section className="popular">
        <div className="sec-title">
          <span className="star">⭐</span>
          오늘의 인기 메뉴
        </div>

        {/* 카테고리 칩 */}
        <div className="chips">
          {categories.map((c) => (
            <button
              key={c}
              className={`chip ${activeCat === c ? "active" : ""}`}
              onClick={() => setActiveCat(c)}
              type="button"
              aria-pressed={activeCat === c}
            >
              {c}
            </button>
          ))}
        </div>

        {/* 상태별 렌더 */}
        {loading ? (
          <div className="menu-grid">
            <article className="menu-card skeleton" />
            <article className="menu-card skeleton" />
          </div>
        ) : errMsg ? (
          <div className="empty-state">{errMsg}</div>
        ) : cards.length === 0 ? (
          <div className="empty-state">표시할 메뉴가 없어요.</div>
        ) : (
          <div className="menu-grid">
            {cards.map((m) => (
              <article
                key={m.key}
                className="menu-card"
                onClick={() => goMenu({ category: activeCat, search: m.name })}
              >
                <div className="thumb">
                  {m.image ? (
                    <img
                      src={m.image}
                      alt={m.name}
                      loading="lazy"
                      style={{ width: "100%", height: "100%", objectFit: "cover", borderRadius: 12 }}
                    />
                  ) : (
                    <span className="thumb-emoji" aria-hidden>
                      🍽️
                    </span>
                  )}
                </div>
                <div className="menu-name">{m.name}</div>
                <div className="menu-meta">
                  <FiClock className="meta-icon" />
                  {m.time}분
                </div>
              </article>
            ))}
          </div>
        )}

        {/* CTA */}
        <button className="cta" type="button" onClick={goFridge}>
          나만의 냉장고 만들기 <span className="arrow">→</span>
        </button>
      </section>
    </div>
  );
}
