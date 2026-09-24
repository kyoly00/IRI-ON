import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { authFetch } from "../../lib/api";
import "./RecipeCheck.css";

export default function RecipeCheck() {
  const { id } = useParams();
  const navigate = useNavigate();
  const userId = localStorage.getItem("user_id");
  const [household, setHousehold] = useState(null);
  const [servings, setServings] = useState(1);
  const [result, setResult] = useState(null);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!userId) return navigate("/");
    authFetch("/households/me").then((r) => r.json()).then((data) => {
      setHousehold(data.household);
      if (!data.household) setMessage("공유 냉장고를 먼저 만들어 주세요.");
    }).catch(() => setMessage("가정 정보를 불러오지 못했습니다.")).finally(() => setLoading(false));
  }, [navigate, userId]);

  useEffect(() => {
    if (!household) return;
    setLoading(true);
    authFetch(`/households/${household.household_id}/recipes/${id}/availability`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ servings }),
    }).then(async (r) => { const data = await r.json(); if (!r.ok) throw new Error(data.detail); return data; })
      .then(setResult).catch((e) => setMessage(e.message || "재료를 비교하지 못했습니다.")).finally(() => setLoading(false));
  }, [household, id, servings, userId]);

  const requestPurchase = async () => {
    const shortages = result?.shortages || [];
    if (!shortages.length) return navigate(`/CookingExplain/${id}`);
    const response = await authFetch(`/households/${household.household_id}/purchase-requests`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ recipe_id: Number(id), servings, items: shortages.map((item) => ({ ingredient_id: item.ingredient_id, quantity: item.shortage_quantity, unit: item.unit })) }),
    });
    const data = await response.json();
    if (!response.ok) return setMessage(data.detail || "구매 요청 생성에 실패했습니다.");
    setMessage(household.role === "child" ? "부모님에게 구매 요청을 보냈어요." : "구매 예정 목록에 추가했어요.");
  };

  return <main className="recipe-check-page">
    <button className="back" onClick={() => navigate("/menu")}>← 메뉴</button>
    <h1>재료 확인</h1>
    {!household && !loading && <><p>{message}</p><button className="primary" onClick={() => navigate("/fridge")}>공유 냉장고 설정</button></>}
    {household && <>
      <label>몇 인분인가요?
        <select value={servings} onChange={(e) => setServings(Number(e.target.value))}>{[1,2,3,4,5,6].map((n) => <option key={n} value={n}>{n}인분</option>)}</select>
      </label>
      {loading ? <p>재료를 비교하는 중…</p> : result && <>
        <h2>{result.recipe_name}</h2>
        {result.items.map((item) => <div className={`check-item ${item.is_shortage ? "shortage" : ""}`} key={item.ingredient_id}>
          <strong>{item.name}</strong><span>필요 {item.needed_quantity}{item.unit} · 보유 {item.available_quantity}{item.unit}</span>
          <b>{item.is_shortage ? `부족 ${item.shortage_quantity}${item.unit}` : "충분해요"}</b>
        </div>)}
        {result.shortages.length ? <button className="primary" onClick={requestPurchase}>{household.role === "child" ? "부모님께 구매 요청" : "구매 예정 목록에 추가"}</button> : <button className="primary" onClick={() => navigate(`/CookingExplain/${id}`)}>요리 시작하기</button>}
      </>}
    </>}
    {message && <p className="notice">{message}</p>}
  </main>;
}
