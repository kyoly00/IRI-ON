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
  try {
    // 선택된 재료 하나씩 서버로 전송
    for (let id of selected) {
      const payload = { ingredient_id: id }; // ✅ 스펙에 맞게 구성
      const url = "http://localhost:8000/users/ingredients";
      console.log("→ POST", url, payload);

      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const raw = await res.text();
      if (!res.ok) {
        console.error(`❌ 재료 ${id} 저장 실패:`, res.status, res.statusText, raw);
        alert(`재료 저장 실패 (ingredient_id: ${id}, HTTP ${res.status})`);
        return; // 하나라도 실패하면 중단
      }

      let data = null;
      try {
        data = raw ? JSON.parse(raw) : null;
      } catch {
        data = raw;
      }

      console.log(`✅ 재료 ${id} 저장 성공, 서버 응답:`, data);
      alert(`재료 ${id} 저장 성공 (user_id: ${data.user_id})`);
    }

    // 모든 저장 완료 시 페이지 이동
    alert("모든 재료 저장 완료!");
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
        className={`ingredient-card ${selected.includes(item.ingredient_id) ? "selected" : ""}`}
        onClick={() => handleSelect(item)}
      >
        <span>{item.name}</span> {/* ✅ 이름만 표시 */}
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
