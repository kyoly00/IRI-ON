import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import "./Menu.css";
import { FaSearch, FaClock } from "react-icons/fa";

const categories = ["전체", "한식", "중식", "일식", "양식", "간편식", "기타"];

export default function Menu() {
  // 백엔드 없이 기본 메뉴 데이터
  const [menuList] = useState([
    { recipe_id: 1, name: "김치찌개", time: 30, image_url: "/images/kimchi.png", category: "한식" },
    { recipe_id: 2, name: "된장찌개", time: 25, image_url: "/images/soybean.png", category: "한식" },
    { recipe_id: 3, name: "짜장면", time: 20, image_url: "/images/jjajang.png", category: "중식" },
    { recipe_id: 4, name: "탕수육", time: 25, image_url: "/images/tangsuyuk.png", category: "중식" },
    { recipe_id: 5, name: "초밥 모둠", time: 15, image_url: "/images/sushi.png", category: "일식" },
    { recipe_id: 6, name: "라멘", time: 18, image_url: "/images/ramen.png", category: "일식" },
    { recipe_id: 7, name: "마르게리타 피자", time: 20, image_url: "/images/pizza.png", category: "양식" },
    { recipe_id: 8, name: "스파게티", time: 15, image_url: "/images/spaghetti.png", category: "양식" },
  ]);

  const [selectedId, setSelectedId] = useState(null);
  const [selectedCategory, setSelectedCategory] = useState("전체");
  const navigate = useNavigate();

  // 버튼 클릭 시 CookingExplain 페이지로 이동
  const handleStartCooking = () => {
    if (selectedId) {
      navigate(`/CookingExplain/${selectedId}`);
    } else {
      alert("메뉴를 선택해주세요!");
    }
  };

  return (
    <div className="menu-page">
      <h2 className="title">오늘의 메뉴를 선택하세요!</h2>

      {/* 검색창 */}
      <div className="search-bar">
        <FaSearch className="search-icon" />
        <input placeholder="메뉴를 검색하세요." />
      </div>

      {/* 카테고리 */}
      <div className="category-bar">
        <div
          className="category-highlight"
          style={{
            transform: `translateX(${categories.indexOf(selectedCategory) * 100}%)`,
            width: `${100 / categories.length}%`,
          }}
        ></div>
        {categories.map((cat) => (
          <button
            key={cat}
            className={`category-btn ${selectedCategory === cat ? "active" : ""}`}
            onClick={() => setSelectedCategory(cat)}
          >
            {cat}
          </button>
        ))}
      </div>

      {/* 메뉴 리스트 */}
      <div className="menu-list">
        {menuList
          .filter((menu) => selectedCategory === "전체" || menu.category === selectedCategory)
          .map((menu) => (
            <div
              key={menu.recipe_id}
              className={`menu-card ${selectedId === menu.recipe_id ? "selected" : ""}`}
              onClick={() => setSelectedId(menu.recipe_id)}
            >
              <img src={menu.image_url} alt={menu.name} className="menu-img" />
              <div className="menu-info">
                <span className="menu-name">{menu.name}</span>
                <div className="menu-time">
                  <FaClock /> {menu.time}분
                </div>
              </div>
            </div>
          ))}
      </div>

      {/* 하단 버튼 */}
      <div className="bottom-btn-wrapper">
        <button className="start-btn" onClick={handleStartCooking}>
          요리시작하기
        </button>
      </div>
    </div>
  );
}
