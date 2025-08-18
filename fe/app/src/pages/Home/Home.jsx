import React, { useState } from "react";
import "./Home.css";

import topLogo from "../../assets/top_logo.png"; // 좌측 상단 로고
import chef3d  from "../../assets/3dLogo.png";   // 왼쪽 캐릭터

const CATS = ["한식", "중식", "일식", "양식"];

export default function Home() {
  const [cat, setCat] = useState("한식");
  const trending = []; // 백엔드 미연동 시 빈 배열 → "표시할 메뉴가 없어요." 노출

  return (
    <div className="home-page">
      {/* ===== 헤더 ===== */}
      <header className="home-header">
        <img className="home-logo" src={topLogo} alt="CHEF YUM" />
        <div className="home-actions">
          <button className="icon-btn" aria-label="검색">🔎</button>
          <button className="icon-btn" aria-label="찜">🤍</button>
          <button className="icon-btn" aria-label="알림">🔔</button>
        </div>
      </header>

      {/* ===== 히어로: (왼) 캐릭터 / (오) 말풍선 ===== */}
      <section className="hero">
        <div className="hero-left">
          <img className="hero-chef" src={chef3d} alt="셰프 캐릭터" />
        </div>
        <div className="hero-bubble">
          <p className="bubble-title">안녕!</p>
          <p className="bubble-text">나는 AI 요리선생님 셰프얌이야.</p>
          <p className="bubble-text">나만의 냉장고를 만들고</p>
          <p className="bubble-text">맞춤형 레시피를 추천받아보자!</p>
        </div>
      </section>

      {/* ===== 섹션: 오늘의 인기 메뉴 ===== */}
      <section className="section">
        <div className="section-row">
          <div className="section-title">
            <span className="star">⭐</span>
            오늘의 인기 메뉴
          </div>
          <button className="more-btn" type="button">더보기</button>
        </div>

        <div className="cat-row">
          {CATS.map((c) => (
            <button
              key={c}
              type="button"
              className={`cat-chip ${cat === c ? "on" : ""}`}
              onClick={() => setCat(c)}
            >
              {c}
            </button>
          ))}
        </div>

        {/* 카드 리스트(백엔드 연결 전엔 비어있음) */}
        {trending.length === 0 ? (
          <p className="empty">표시할 메뉴가 없어요.</p>
        ) : (
          <div className="card-grid">
            {trending.map((m) => (
              <article key={m.id} className="menu-card">
                <img className="menu-img" src={m.image} alt={m.name} />
                <div className="menu-name">{m.name}</div>
                <div className="menu-meta">⏱ {m.time}분</div>
              </article>
            ))}
          </div>
        )}

        {/* 냉장고 만들기 CTA */}
        <button className="fridge-cta" type="button">
          나만의 냉장고 만들기 <span className="arrow">→</span>
        </button>
      </section>
    </div>
  );
}
