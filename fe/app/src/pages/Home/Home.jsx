import React from "react";
import ChefYum from "../../assets/ChefYum.png";
import Logo3D from "../../assets/3dLogo.png";
import "./Home.css";

export default function Home() {
  return (
    <div className="home">
      {/* Header */}
      <header className="home-header">
        <img src={ChefYum} alt="CHEF YUM 로고" className="brand" />
        <div className="header-icons">
          {/* 아이콘은 나중에 실제 아이콘으로 교체 */}
          <button className="icon-btn" aria-label="검색">🔍</button>
          <button className="icon-btn" aria-label="찜">♡</button>
          <button className="icon-btn" aria-label="알림">🔔</button>
        </div>
      </header>

      {/* Hero */}
      <section className="hero">
        <img src={Logo3D} alt="셰프 캐릭터" className="chef-3d" />

        <div className="bubbles">
          <div className="bubble">
            <p>
              안녕!<br />
              나는 여러분의<br />
              <b>AI 요리선생님 셰프얌</b>이야.
            </p>
          </div>
          <div className="bubble shadow">
            <p>
              <b>나만의 냉장고</b>를 만들고<br />
              맞춤 레시피를 추천받아보자!
            </p>
          </div>
        </div>
      </section>

      {/* Actions */}
      <section className="actions">
        <button className="ghost-btn" onClick={() => console.log("나만의 냉장고 만들기")}>
          나만의 냉장고 만들기 <span className="arrow">→</span>
        </button>
        <button className="ghost-btn" onClick={() => console.log("다양한 레시피 구경하기")}>
          다양한 레시피 구경하기 <span className="arrow">→</span>
        </button>
      </section>

      {/* 하단 네비는 기존 레이아웃 컴포넌트로 표시됨 */}
    </div>
  );
}
