import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import "./Menu.css";
import { FaSearch, FaClock } from "react-icons/fa";
import { api, authFetch } from "../../lib/api";

const categories = ["전체", "한식", "중식", "일식", "양식", "간식", "기타"];

export default function Menu() {
  const [menuList, setMenuList] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [selectedCategory, setSelectedCategory] = useState("전체");
  const [viewMode, setViewMode] = useState("전체"); // 전체 or 맞춤형
  const [searchTerm, setSearchTerm] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [youtubeUrl, setYoutubeUrl] = useState("");
  const [youtubeName, setYoutubeName] = useState("");
  const [minDurationSeconds, setMinDurationSeconds] = useState("");
  const [minSteps, setMinSteps] = useState("");
  const [maxSteps, setMaxSteps] = useState("");
  const [youtubeImporting, setYoutubeImporting] = useState(false);
  const [youtubeMessage, setYoutubeMessage] = useState("");
  const [youtubeOpen, setYoutubeOpen] = useState(false);
  const navigate = useNavigate();

  // ✅ 메뉴 불러오기
  const fetchMenus = async (mode, search = "", category = "전체") => {
    try {
      setLoading(true);
      setError("");
      let url = "";
      if (mode === "전체") {
        url = api('/recipes/');
      } else {
        // TODO: 로그인 후 실제 user_id로 교체
        url = api("/recipes/recommendations");
      }

      const params = new URLSearchParams();
      if (search) params.append("search", search);
      if (category !== "전체") params.append("category", category);

      const res = mode === "맞춤" ? await authFetch(`${url}?${params.toString()}`) : await fetch(`${url}?${params.toString()}`);
      if (!res.ok) throw new Error(`서버 오류: ${res.status}`);
      const data = await res.json();
      setMenuList(data);
    } catch (err) {
      console.error("❌ 메뉴 불러오기 실패:", err);
      setError("메뉴를 불러오지 못했어요. 백엔드 연결을 확인해 주세요.");
    } finally {
      setLoading(false);
    }
  };

  // 처음 전체 메뉴 불러오기
  useEffect(() => {
    const timer = window.setTimeout(() => {
      fetchMenus(viewMode, searchTerm, selectedCategory);
    }, searchTerm ? 250 : 0);
    return () => window.clearTimeout(timer);
  }, [viewMode, searchTerm, selectedCategory]);

  // ✅ 보기 모드 변경
  const handleViewModeChange = (mode) => {
    setViewMode(mode);
  };

  // ✅ 검색 이벤트
  const handleSearchChange = (e) => {
    const value = e.target.value;
    setSearchTerm(value);
  };

  // ✅ 카테고리 선택
  const handleCategoryChange = (cat) => {
    setSelectedCategory(cat);
  };

  // ✅ 요리 시작 버튼
  const handleStartCooking = () => {
    if (selectedId) {
      navigate(`/recipes/${selectedId}/check`);
    } else {
      alert("메뉴를 선택해주세요!");
    }
  };

  // 서버가 URL·중복·자막·LLM 단계 검증을 모두 통과시킨 레시피만 요리 화면으로 연다.
  const handleYouTubeImport = async (event) => {
    event.preventDefault();
    const videoUrl = youtubeUrl.trim();
    if (!videoUrl) {
      setYoutubeMessage("YouTube 링크를 먼저 입력해 주세요.");
      return;
    }
    const optionalNumber = (value) => (value === "" ? undefined : Number(value));
    setYoutubeImporting(true);
    setYoutubeMessage("");
    try {
      const response = await authFetch("/recipes/import-youtube", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          video_url: videoUrl,
          name: youtubeName.trim() || undefined,
          min_duration_seconds: optionalNumber(minDurationSeconds),
          min_steps: optionalNumber(minSteps),
          max_steps: optionalNumber(maxSteps),
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "영상 레시피를 만들지 못했어요.");
      const recipeId = data.recipe?.recipe_id;
      if (!recipeId) throw new Error("생성된 레시피 정보를 받지 못했어요.");
      setYoutubeMessage(data.message || "레시피를 준비했어요.");
      // 중복이면 새 row를 만들지 않고, 이미 검증된 기존 레시피로 바로 안내한다.
      navigate(`/CookingExplain/${recipeId}`);
    } catch (reason) {
      setYoutubeMessage(reason.message || "영상 레시피를 만들지 못했어요.");
    } finally {
      setYoutubeImporting(false);
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

      <section className="youtube-import-card" aria-label="YouTube 영상 레시피 등록">
        <h3>YouTube 링크로 바로 요리하기</h3>
        <p>자막과 조리 단계를 검증한 뒤 레시피를 만들고 음성 보조 화면으로 이동해요.</p>
        <button
          type="button"
          className="youtube-import-toggle"
          onClick={() => setYoutubeOpen((open) => !open)}
          aria-expanded={youtubeOpen}
        >
          {youtubeOpen ? "YouTube 검색 닫기" : "YouTube 검색 열기"}
        </button>
        {youtubeOpen && (
        <form onSubmit={handleYouTubeImport}>
          <input
            type="url"
            placeholder="YouTube 링크를 붙여 넣어 주세요"
            value={youtubeUrl}
            onChange={(event) => setYoutubeUrl(event.target.value)}
            disabled={youtubeImporting}
            required
          />
          <input
            type="text"
            placeholder="요리 이름 (비우면 영상 자막에서 만들어요)"
            value={youtubeName}
            onChange={(event) => setYoutubeName(event.target.value)}
            disabled={youtubeImporting}
          />
          <details>
            <summary>짧은 영상·단계 수 설정</summary>
            <div className="youtube-policy-inputs">
              <label>최소 영상 길이(초)<input type="number" min="0" value={minDurationSeconds} onChange={(event) => setMinDurationSeconds(event.target.value)} placeholder="서버 기본값: 0" /></label>
              <label>최소 단계 수<input type="number" min="1" max="60" value={minSteps} onChange={(event) => setMinSteps(event.target.value)} placeholder="서버 기본값: 1" /></label>
              <label>최대 단계 수<input type="number" min="1" max="60" value={maxSteps} onChange={(event) => setMaxSteps(event.target.value)} placeholder="서버 기본값: 24" /></label>
            </div>
          </details>
          <button type="submit" disabled={youtubeImporting}>{youtubeImporting ? "자막·단계 검증 중…" : "영상으로 레시피 만들기"}</button>
        </form>
        )}
        {youtubeMessage && <p className="youtube-import-message">{youtubeMessage}</p>}
      </section>

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
              {menu.has_video && <span className="menu-video-badge">▶ 구간 영상</span>}
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
        {loading && <p className="menu-message">메뉴를 불러오는 중이에요…</p>}
        {!loading && error && <p className="menu-message error">{error}</p>}
        {!loading && !error && menuList.length === 0 && <p className="menu-message">조건에 맞는 메뉴가 없어요.</p>}
      </div>

      {/* 하단 버튼 */}
      <div className="bottom-btn-wrapper">
        <button className="start-btn" onClick={handleStartCooking} disabled={!selectedId}>
          요리 시작하기
        </button>
      </div>
    </div>
  );
}
