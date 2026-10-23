import React, { useEffect, useState, useCallback } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, authFetch } from "../../lib/api";
import "./RecipeCheck.css";

export default function RecipeCheck() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [household, setHousehold] = useState(null);
  const [servings, setServings] = useState(1);
  const [result, setResult] = useState(null);
  const [recipeInfo, setRecipeInfo] = useState(null);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);
  const [requesting, setRequesting] = useState(false);

  // 1. 기본 레시피 정보 불러오기 (fallback 및 레시피 이름용)
  useEffect(() => {
    fetch(api(`/recipes/${id}?servings=${servings}`))
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data) setRecipeInfo(data);
      })
      .catch(() => {});
  }, [id, servings]);

  // 2. 가구(household) 정보 불러오기
  useEffect(() => {
    authFetch("/households/me")
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data && data.household) {
          setHousehold(data.household);
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  // 3. 재료 보유 현황 비교하기
  const fetchAvailability = useCallback(() => {
    if (!household) return;
    setLoading(true);
    authFetch(`/households/${household.household_id}/recipes/${id}/availability`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ servings }),
    })
      .then(async (r) => {
        const data = await r.json();
        if (!r.ok) throw new Error(data.detail);
        return data;
      })
      .then((data) => {
        setResult(data);
      })
      .catch((e) => {
        setMessage(e.message || "재료 보유 현황을 확인하지 못했습니다.");
      })
      .finally(() => setLoading(false));
  }, [household, id, servings]);

  useEffect(() => {
    if (household) {
      fetchAvailability();
    }
  }, [household, fetchAvailability]);

  // 구매 요청
  const requestPurchase = async () => {
    const shortages = result?.shortages || [];
    if (!shortages.length || !household) return;
    setRequesting(true);
    try {
      const response = await authFetch(`/households/${household.household_id}/purchase-requests`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          recipe_id: Number(id),
          servings,
          items: shortages.map((item) => ({
            ingredient_id: item.ingredient_id,
            quantity: item.shortage_quantity,
            unit: item.unit,
          })),
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "구매 요청 생성에 실패했습니다.");
      setMessage(
        household.role === "child"
          ? "부모님에게 부족한 재료 구매 요청을 보냈어요!"
          : "부족한 재료를 구매 예정 목록에 추가했어요!"
      );
    } catch (err) {
      setMessage(err.message || "구매 요청 중 오류가 발생했습니다.");
    } finally {
      setRequesting(false);
    }
  };

  const recipeTitle = result?.recipe_name || recipeInfo?.name || "레시피 재료 확인";
  const items = result?.items || recipeInfo?.ingredients || [];

  return (
    <main className="recipe-check-page">
      <div className="check-top-bar">
        <button type="button" className="back-btn" onClick={() => navigate("/menu")}>
          ← 메뉴
        </button>
      </div>

      <div className="check-header">
        <h1 className="recipe-title">{recipeTitle}</h1>
        <p className="serving-guide">인분을 고르면 필요한 재료량이 자동으로 조절돼요.</p>

        <div className="serving-selector-box">
          <label htmlFor="servings-select" className="serving-label">
            인분 선택
          </label>
          <select
            id="servings-select"
            className="serving-select"
            value={servings}
            onChange={(e) => setServings(Number(e.target.value))}
          >
            {[1, 2, 3, 4, 5, 6].map((n) => (
              <option key={n} value={n}>
                {n}인분
              </option>
            ))}
          </select>
        </div>
      </div>

      <section className="ingredient-list-section">
        <h2 className="section-title">필요한 재료</h2>

        {loading && <p className="loading-text">재료를 확인하는 중이에요…</p>}

        {!loading && items.length === 0 && (
          <p className="empty-text">등록된 재료 정보가 없습니다.</p>
        )}

        <div className="ingredient-items-container">
          {items.map((item, idx) => {
            const hasStockInfo = item.available_quantity !== undefined;
            const isShortage = item.is_shortage;
            const neededQty = item.needed_quantity ?? item.quantity ?? 0;
            const unit = item.unit || "";

            return (
              <div
                className={`check-item ${isShortage ? "shortage" : ""}`}
                key={item.ingredient_id || idx}
              >
                <div className="check-item-header">
                  <strong className="ingredient-name">{item.name}</strong>
                  {hasStockInfo && (
                    <b className={isShortage ? "badge shortage" : "badge sufficient"}>
                      {isShortage ? `부족 ${item.shortage_quantity}${unit}` : "충분해요"}
                    </b>
                  )}
                </div>
                <span className="ingredient-detail">
                  {hasStockInfo
                    ? `필요 ${neededQty}${unit} · 보유 ${item.available_quantity}${unit}`
                    : `필요 ${neededQty}${unit}`}
                </span>
              </div>
            );
          })}
        </div>
      </section>

      {message && <p className="notice-message">{message}</p>}

      {/* 하단 버튼 영역: 요리 시작 버튼과 구매 요청 버튼 */}
      <div className="check-actions-wrapper">
        {result?.shortages?.length > 0 && household && (
          <button
            type="button"
            className="purchase-btn"
            onClick={requestPurchase}
            disabled={requesting}
          >
            {requesting
              ? "요청 보내는 중…"
              : household.role === "child"
              ? "부모님께 부족한 재료 요청하기"
              : "부족한 재료 구매 목록에 담기"}
          </button>
        )}

        <button
          type="button"
          className="start-cooking-primary-btn"
          onClick={() => navigate(`/CookingExplain/${id}?servings=${servings}`)}
        >
          요리 시작하기
        </button>
      </div>
    </main>
  );
}
