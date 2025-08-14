import React from "react";
import { FaCog, FaPlay, FaStop } from "react-icons/fa";
import "./CookingExplain.css";
import CookingIcon from "../../assets/cookingexplain.png"; // 업로드한 PNG 경로

export default function CookingExplain() {
  // 버튼 클릭 이벤트
  const handlePlay = () => {
    console.log("재생 버튼 클릭됨");
    // 여기서 실제 재생 기능 실행
  };

  const handleStop = () => {
    console.log("정지 버튼 클릭됨");
    // 여기서 실제 정지 기능 실행
  };

  return (
    <div className="complete-page">
      {/* 상단 로고 + 설정 버튼 */}
      <div className="complete-header">
        <div className="logo">
          <span>CHEF</span> YUM
        </div>
        <button className="settings-btn">
          <FaCog />
        </button>
      </div>

      {/* 메인 아이콘 */}
      <div className="main-icon-wrapper">
        <div className="main-icon pulse-glow">
          <img src={CookingIcon} alt="조리 아이콘" className="cooking-img" />
        </div>
      </div>

      {/* 제목 */}
      <h2 className="title">조리 과정 설명 중</h2>

      {/* 재생/정지 버튼 */}
      <div className="control-buttons">
        <button className="play-btn" onClick={handlePlay}>
          <FaPlay /> 재생
        </button>
        <button className="stop-btn" onClick={handleStop}>
          <FaStop /> 정지
        </button>
      </div>
    </div>
  );
}
