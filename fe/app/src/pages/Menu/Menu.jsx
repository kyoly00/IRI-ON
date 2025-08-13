import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import "./Menu.css";
import { FaSearch, FaClock } from "react-icons/fa";

const categories = ["전체", "한식", "중식", "일식", "양식", "간편식", "기타"];

const menuList = [
  { id: 1, name: "토마토 스파게티", time: 30, img: "/img/spaghetti.png" },
  { id: 2, name: "소고기 카레", time: 40, img: "/img/curry.png" },
  { id: 3, name: "닭가슴살 야채볶음밥", time: 20, img: "/img/rice.png" },
  { id: 4, name: "오믈렛", time: 10, img: "/img/omelet.png" },
  { id: 5, name: "김치볶음밥", time: 10, img: "/img/omelet.png" },
  { id: 6, name: "토마토 스파게티", time: 30, img: "/img/spaghetti.png" },
  { id: 7, name: "소고기 카레", time: 40, img: "/img/curry.png" },
  { id: 8, name: "닭가슴살 야채볶음밥", time: 20, img: "/img/rice.png" },
  { id: 9, name: "오믈렛", time: 10, img: "/img/omelet.png" },
  { id: 10, name: "김치볶음밥", time: 10, img: "/img/omelet.png" },
];

export default function Menu() {
  const [selectedId, setSelectedId] = useState(null);
  const navigate = useNavigate();

  const handleStartCooking = () => {
    if (selectedId) {
      navigate(`/cook/${selectedId}`); // 선택된 메뉴 id를 가지고 다음 페이지로 이동
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
        {categories.map((cat) => (
          <button
            key={cat}
            className={`category-btn ${cat === "전체" ? "active" : ""}`}
          >
            {cat}
          </button>
        ))}
      </div>

      {/* 메뉴 리스트 */}
      <div className="menu-list">
        {menuList.map((menu) => (
          <div
            key={menu.id}
            className={`menu-card ${selectedId === menu.id ? "selected" : ""}`}
            onClick={() => setSelectedId(menu.id)}
          >
            <img src={menu.img} alt={menu.name} className="menu-img" />
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
