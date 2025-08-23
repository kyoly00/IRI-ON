import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import "./Menu.css";
import { FaSearch, FaClock } from "react-icons/fa";

const categories = ["전체", "한식", "중식", "일식", "양식", "간편식", "기타"];

export default function Menu() {
  const [menuList, setMenuList] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [selectedCategory, setSelectedCategory] = useState("전체");
  const [viewMode, setViewMode] = useState("전체"); // 전체 or 맞춤형
  const [searchTerm, setSearchTerm] = useState("");
  const navigate = useNavigate();

  // ✅ 메뉴 불러오기
  const fetchMenus = async (mode, search = "", category = "전체") => {
    try {
      let url = "";
      if (mode === "전체") {
        url = "http://192.168.35.9:8000/recipes/";
      } else {
        // TODO: 로그인 후 실제 user_id로 교체
        const userId = localStorage.getItem("user_id") || 1;
        url = `http://192.168.35.9:8000/recipes/recommendations/${userId}`;
      }

      const params = new URLSearchParams();
      if (search) params.append("search", search);
      if (category !== "전체") params.append("category", category);

      const res = await fetch(`${url}?${params.toString()}`);
      if (!res.ok) throw new Error(`서버 오류: ${res.status}`);
      const data = await res.json();
      setMenuList(data);
    } catch (err) {
      console.error("❌ 메뉴 불러오기 실패:", err);
    }
  };

  // 처음 전체 메뉴 불러오기
  useEffect(() => {
    fetchMenus("전체");
  }, []);

  // ✅ 보기 모드 변경
  const handleViewModeChange = (mode) => {
    setViewMode(mode);
    fetchMenus(mode, searchTerm, selectedCategory);
  };

  // ✅ 검색 이벤트
  const handleSearchChange = (e) => {
    const value = e.target.value;
    setSearchTerm(value);
    fetchMenus(viewMode, value, selectedCategory);
  };

  // ✅ 카테고리 선택
  const handleCategoryChange = (cat) => {
    setSelectedCategory(cat);
    fetchMenus(viewMode, searchTerm, cat);
  };

  // ✅ 요리 시작 버튼
  const handleStartCooking = () => {
    if (selectedId) {
      navigate(`/CookingExplain/${selectedId}`);
    } else {
      alert("메뉴를 선택해주세요!");
    }
  };

  return (
    <div className="menu-page">
      <h2 className="title">오늘의 메뉴를 선택하세요 !</h2>

      {/* 보기 모드 버튼 */}
      <div className="view-toggle">
        <button
          className={`view-btn ${viewMode === "전체" ? "active" : ""}`}
          onClick={() => handleViewModeChange("전체")}
        >
          전체 메뉴 보기
        </button>
        <button
          className={`view-btn ${viewMode === "맞춤형" ? "active" : ""}`}
          onClick={() => handleViewModeChange("맞춤형")}
        >
          맞춤 메뉴 보기
        </button>
      </div>

      {/* 검색창 */}
      <div className="search-bar">
        <FaSearch className="search-icon" />
        <input
          type="text"
          placeholder="메뉴를 검색하세요."
          value={searchTerm}
          onChange={handleSearchChange}
        />
      </div>

      {/* 카테고리 */}
      <div className="category-bar">
        {categories.map((cat) => (
          <button
            key={cat}
            className={`category-btn ${selectedCategory === cat ? "active" : ""}`}
            onClick={() => handleCategoryChange(cat)}
          >
            {cat}
          </button>
        ))}
      </div>

      {/* 메뉴 리스트 */}
      <div className="menu-list">
        {menuList.map((menu) => (
          <div
            key={menu.recipe_id}
            className={`menu-card ${selectedId === menu.recipe_id ? "selected" : ""}`}
            onClick={() => setSelectedId(menu.recipe_id)}
          >
            <img src={menu.image_url} alt={menu.name} className="menu-img" />
            <div className="menu-info">
              <span className="menu-name">{menu.name}</span>
              <div className="menu-meta">
                <div className="menu-time">
                  <FaClock /> {menu.time}분
                </div>
                {/* 맞춤형 모드에서만 난이도 표시 */}
                {viewMode === "맞춤형" && (
                  <div className="menu-difficulty">난이도: {menu.difficulty}</div>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* 하단 버튼 */}
      <div className="bottom-btn-wrapper">
        <button className="start-btn" onClick={handleStartCooking}>
          요리 시작하기
        </button>
      </div>
    </div>
  );
}
