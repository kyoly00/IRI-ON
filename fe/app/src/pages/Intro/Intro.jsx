import React from "react";
import { useNavigate } from "react-router-dom";
import "./Intro.css";

export default function Welcome() {
  return (
    <div className="welcome-page">
      {/* 배경 장식 */}
      <div className="polygon1"></div>
      <div className="vector1"></div>

      {/* 메인 캐릭터 영역 */}
      <div className="character-frame">
        <div className="circle-shadow"></div>
        <div className="circle-white"></div>
        <img
          src="/img/chef.png" // 캐릭터 이미지 경로
          alt="셰프 캐릭터"
          className="chef-img"
        />

        {/* 말풍선 - 맞춤형 레시피 추천 */}
        <div className="bubble-recipe">
          <span>맞춤형 레시피 추천</span>
          <div className="icon-box purple"></div>
        </div>

        {/* 말풍선 - 보호자 아동 모니터링 */}
        <div className="bubble-monitoring">
          <div className="icon-box pink"></div>
          <span>보호자 아동 모니터링</span>
        </div>

        {/* 말풍선 - 나만의 냉장고 만들기 */}
        <div className="bubble-fridge">
          <div className="icon-box blue"></div>
          <span>나만의 냉장고 만들기</span>
        </div>
      </div>

      {/* 타이틀 */}
      <div className="title-text">
        <p>돌봄 공백 아동을 위한</p>
        <h1>AI 요리 선생님</h1>
      </div>

     {/* 시작하기 버튼 */}
      <button className="start-btn">시작하기</button>
    </div> 
  );
}

// Intro.jsx


export default function Intro() {
  const navigate = useNavigate();

  return (
    <div className="intro-page">
      <h1>Welcome!</h1>
      <button onClick={() => navigate("/home")}>시작하기</button>
    </div>
  );
}
