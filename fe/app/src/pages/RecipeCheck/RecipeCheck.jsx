import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import "./RecipeCheck.css";

// 재료 보유 여부는 추천을 위한 정보일 뿐, 요리 시작을 막지 않는다.
export default function RecipeCheck() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [servings, setServings] = useState(1);

  return <main className="recipe-check-page">
    <button className="back" onClick={() => navigate("/menu")}>← 메뉴</button>
    <h1>몇 인분으로 만들까요?</h1>
    <p className="serving-guide">인분을 고르면 요리 화면의 재료량이 자동으로 조절돼요.</p>
    <label>인분 선택
      <select value={servings} onChange={(e) => setServings(Number(e.target.value))}>
        {[1, 2, 3, 4, 5, 6].map((n) => <option key={n} value={n}>{n}인분</option>)}
      </select>
    </label>
    <button className="primary" onClick={() => navigate(`/CookingExplain/${id}?servings=${servings}`)}>
      요리 시작하기
    </button>
  </main>;
}
