// Home.jsx
import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import "./Home.css";

import topLogo from "../../assets/top_logo.png";   // CHEF YUM 로고
import chef3d from "../../assets/3dLogo.png";     // 셰프 캐릭터
import { FiSearch, FiHeart, FiBell, FiStar, FiClock } from "react-icons/fi";

export default function Home() {
  const nav = useNavigate();

  // ✅ 메뉴를 하드코딩으로 많이 추가
  const [menus] = useState([
    { id: 1, name: "토마토 스파게티", time: "30분", thumb: "🍝" },
    { id: 2, name: "김치찌개", time: "25분", thumb: "🥘" },
    { id: 3, name: "초밥", time: "20분", thumb: "🍣" },
    { id: 4, name: "햄버거", time: "15분", thumb: "🍔" },
    { id: 5, name: "피자", time: "18분", thumb: "🍕" },
    { id: 6, name: "라면", time: "10분", thumb: "🍜" },
    { id: 7, name: "샐러드", time: "12분", thumb: "🥗" },
    { id: 8, name: "스테이크", time: "40분", thumb: "🥩" },
    { id: 9, name: "타코", time: "22분", thumb: "🌮" },
    { id: 10, name: "도넛", time: "8분", thumb: "🍩" },
    { id: 11, name: "케이크", time: "35분", thumb: "🍰" },
    { id: 12, name: "팬케이크", time: "15분", thumb: "🥞" },
  ]);

  // ✅ 타이핑 효과용 멘트들
  const texts = [
    "안녕! \n나는 AI 요리선생님\n셰프얌이야.",
    "나만의 냉장고를 만들고\n맞춤 메뉴를 추천받아보자!\n\n오늘은 무엇을 먹을까? 🤔"
  ];
  const [displayText, setDisplayText] = useState("");
  const [textIdx, setTextIdx] = useState(0);
  const [charIdx, setCharIdx] = useState(0);
  const [isDeleting, setIsDeleting] = useState(false);

  useEffect(() => {
    const current = texts[textIdx];
    let timer;

    if (!isDeleting && charIdx <= current.length) {
      timer = setTimeout(() => {
        setDisplayText(current.slice(0, charIdx));
        setCharIdx((c) => c + 1);
      }, 120);
    } else if (isDeleting && charIdx >= 0) {
      timer = setTimeout(() => {
        setDisplayText(current.slice(0, charIdx));
        setCharIdx((c) => c - 1);
      }, 80);
    } else if (!isDeleting && charIdx > current.length) {
      timer = setTimeout(() => setIsDeleting(true), 1500);
    } else if (isDeleting && charIdx < 0) {
      setIsDeleting(false);
      setTextIdx((idx) => (idx + 1) % texts.length);
      setCharIdx(0);
    }

    return () => clearTimeout(timer);
  }, [charIdx, isDeleting, textIdx, texts]);

  return (
    <div className="home-page">
      {/* 상단바 */}
      <div className="home-top">
        <img className="home-logo" src={topLogo} alt="CHEF YUM" />
        <div className="home-actions">
          <FiSearch onClick={() => nav("/menu")} />
          <FiHeart />
          <FiBell />
        </div>
      </div>

      {/* 히어로 영역 */}
      <section className="hero">
        <img className="hero-chef" src={chef3d} alt="셰프 캐릭터" />
        <div className="hero-ment">
          {displayText}
          <span className="cursor">|</span>
        </div>
      </section>

      {/* CTA 버튼 */}
      <button className="cta" onClick={() => nav("/fridge")}>
         나만의 냉장고 만들기
      </button>

      {/* 인기 메뉴 */}
      <section className="popular">
        <div className="sec-title">
          <FiStar className="star" />
          오늘의 인기 메뉴
        </div>

        {/* 메뉴 카드 */}
<div className="menu-list">
  {menus.map((menu) => (
    <div key={menu.id} className="menu-card">
      <div className="thumb">{menu.thumb}</div>
      <div className="menu-name">{menu.name}</div>
      <div className="menu-meta">
        <FiClock /> {menu.time}
      </div>
    </div>
  ))}
</div>

      </section>
    </div>
  );
}
