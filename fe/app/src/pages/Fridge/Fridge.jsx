import React, { useState } from "react";
import "./Fridge.css";
import { FaSearch, FaArrowRight } from "react-icons/fa";
import { useNavigate } from "react-router-dom"; // ✅ 추가

export default function Fridge() {
  const [selected, setSelected] = useState([]);
  const [popupItem, setPopupItem] = useState(null);
  const [amount, setAmount] = useState("");
  const navigate = useNavigate(); // ✅ 추가

  const ingredients = [
    { id: 1, name: "소고기", img: "/images/beef.png" },
    { id: 2, name: "감자", img: "/images/potato.png" },
    { id: 3, name: "당근", img: "/images/carrot.png" },
    { id: 4, name: "레몬", img: "/images/lemon.png" },
    { id: 5, name: "브로콜리", img: "/images/broccoli.png" },
    { id: 6, name: "양파", img: "/images/onion.png" },
    { id: 7, name: "카레가루", img: "/images/curry.png" },
    { id: 8, name: "닭가슴살", img: "/images/chicken.png" },
    { id: 9, name: "대파", img: "/images/leek.png" },
  ];

  const handleSelect = (item) => {
    setSelected((prev) =>
      prev.includes(item.id)
        ? prev.filter((x) => x !== item.id)
        : [...prev, item.id]
    );
    setPopupItem(item);
    setAmount("");
  };

  const closePopup = () => {
    setPopupItem(null);
  };

  const goToComplete = () => {
    navigate("/fridgecomplete"); // ✅ 이동
  };

  return (
    <div className="fridge-page">
      {/* 상단 헤더 */}
      <header className="fridge-header">
        <h1>냉장고 만들기</h1>
        <p>
          냉장고 속 재료를 선택하고,<br />레시피를 추천받으세요!
        </p>
        <div className="date-badge">08.11 월</div>
      </header>

      {/* 검색 바 */}
      <div className="search-bar">
        <FaSearch className="search-icon" />
        <input placeholder="재료를 검색하세요." />
      </div>

      {/* 재료 목록 */}
      <div className="ingredient-grid">
        {ingredients.map((item) => (
          <div
            key={item.id}
            className={`ingredient-card ${
              selected.includes(item.id) ? "selected" : ""
            }`}
            onClick={() => handleSelect(item)}
          >
            <img src={item.img} alt={item.name} />
            <span>{item.name}</span>
          </div>
        ))}
      </div>

      {/* 하단 버튼 */}
      <button className="bottom-btn" onClick={goToComplete}>
        생성하기
      </button>

      {/* 하단 네비게이션 */}
      <nav className="bottom-nav">
        <div className="nav-item">홈</div>
        <div className="nav-item active">냉장고</div>
        <div className="nav-item">메뉴</div>
        <div className="nav-item">프로필</div>
      </nav>

      {/* 팝업 */}
      {popupItem && (
        <div className="popup-overlay">
          <div className="popup-card">
            <img src={popupItem.img} alt={popupItem.name} />
            <p>
              정확한 레시피 추천을 위해<br />남은 양을 알려주세요.
            </p>

            {/* 입력창 + 버튼 래퍼 */}
            <div className="amount-input-wrapper">
              <input
                className="amount-input"
                type="text"
                placeholder="예) 2개, 500ml, 300g"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
              />
              <button className="amount-btn" onClick={closePopup}>
                <FaArrowRight />
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
