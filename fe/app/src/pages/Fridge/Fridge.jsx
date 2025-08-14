import React, { useState, useEffect } from "react";
import "./Fridge.css";
import { FaSearch } from "react-icons/fa";
import { useNavigate } from "react-router-dom";

export default function Fridge() {
  const [selected, setSelected] = useState([]);
  const [ingredients, setIngredients] = useState([]); // 백엔드에서 불러올 재료
  const navigate = useNavigate();

  // 📌 페이지 로드 시 재료 불러오기
  useEffect(() => {
    const fetchIngredients = async () => {
      try {
        const res = await fetch("http://localhost:8000/ingredients/"); // ✅ 수정된 경로
        if (!res.ok) throw new Error("서버 응답 오류");
        const data = await res.json();
        setIngredients(data);
      } catch (err) {
        console.error("❌ 재료 불러오기 실패:", err);
      }
    };
    fetchIngredients();
  }, []);

  // 재료 선택 토글
  const handleSelect = (item) => {
    setSelected((prev) =>
      prev.includes(item.ingredient_id)
        ? prev.filter((x) => x !== item.ingredient_id)
        : [...prev, item.ingredient_id]
    );
  };

  // 선택된 재료 서버에 저장 후 이동
  const goToComplete = async () => {
    // 1. fridge 저장용 payload
    const selectedData = ingredients
      .filter((item) => selected.includes(item.ingredient_id))
      .map((item) => ({
        ingredient_id: item.ingredient_id,
        name: item.name,
      }));

    // 2. users/ingredients 저장용 payload
    const userIngredientData = selected.map((id) => ({
      user_id: 1, // 🔹 로그인 사용자 ID로 교체 필요
      ingredient_id: id,
    }));

    try {
      // 📌 첫 번째 API: fridge 저장
      const fridgeUrl = "http://localhost:8000/api/fridge";
      console.log("→ POST", fridgeUrl, selectedData);
      const res1 = await fetch(fridgeUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(selectedData),
      });

      if (!res1.ok) {
        const raw = await res1.text();
        console.error("❌ fridge 저장 실패:", res1.status, res1.statusText, raw);
        alert(`저장 실패 (HTTP ${res1.status})`);
        return;
      }

      // 📌 두 번째 API: users/ingredients 저장
      const userIngredientsUrl = "http://localhost:8000/users/ingredients";
      console.log("→ POST", userIngredientsUrl, userIngredientData);
      const res2 = await fetch(userIngredientsUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(userIngredientData),
      });

      if (!res2.ok) {
        const raw = await res2.text();
        console.error("❌ users/ingredients 저장 실패:", res2.status, res2.statusText, raw);
        alert(`저장 실패 (HTTP ${res2.status})`);
        return;
      }

      console.log("✅ 모든 저장 성공");
      alert("재료 저장 완료!");
      navigate("/fridgecomplete");
    } catch (error) {
      console.error("❌ 네트워크/코르스 에러:", error);
      alert("저장 실패 (네트워크/CORS)");
    }
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
        {ingredients.length > 0 ? (
          ingredients.map((item) => (
            <div
              key={item.ingredient_id}
              className={`ingredient-card ${
                selected.includes(item.ingredient_id) ? "selected" : ""
              }`}
              onClick={() => handleSelect(item)}
            >
              <img src={item.img} alt={item.name} />
              <span>{item.name}</span>
            </div>
          ))
        ) : (
          <p>재료를 불러오는 중...</p>
        )}
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
    </div>
  );
}
