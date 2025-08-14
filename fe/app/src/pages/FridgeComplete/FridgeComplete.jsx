import React from "react";
import "./FridgeComplete.css";
import { FaCheck, FaTimes } from "react-icons/fa";
import { useNavigate } from "react-router-dom";
import fridgeCompleteIcon from "../../assets/fridgecomplete.png"; 

export default function FridgeComplete() {
  const navigate = useNavigate();

  return (
    <div className="complete-page">
      {/* 로고 + 설정 버튼 */}
      <header className="complete-header">
        <div className="logo">CHEF <span>YUM</span></div>
        <button className="settings-btn">
          <span role="img" aria-label="settings">⚙️</span>
        </button>
      </header>

      {/* 메인 아이콘 */}
      <div className="main-icon-wrapper">
        <div className="main-icon">
          <img 
      src={fridgeCompleteIcon} 
      alt="Fridge Complete Icon" 
      style={{ width: "120px", height: "106px" }} 
       />
        </div>
      </div>
      
      {/* 텍스트 */}
      <h2 className="title">냉장고 생성 완료 !</h2>
      <p className="subtitle">맞춤형 레시피를 추천해드릴까요?</p>

      {/* 버튼 */}
      <div className="button-group">
        <button className="yes-btn" onClick={() => navigate("/Menu")}>
          <FaCheck /> 네
        </button>
        <button className="no-btn" onClick={() => navigate("/")}>
          <FaTimes /> 아니오
        </button>
      </div>
    </div>
  );
}
