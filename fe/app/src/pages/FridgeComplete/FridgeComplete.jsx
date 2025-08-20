import { useEffect } from "react";
import "./FridgeComplete.css";
import { FaCheck, FaTimes } from "react-icons/fa";
import { useNavigate } from "react-router-dom";
import fridgeCompleteIcon from "../../assets/fridgecomplete.png";
import topLogo from "../../assets/top_logo.png";

// ...위 import 동일
export default function FridgeComplete() {
  const navigate = useNavigate();

  useEffect(() => {
    const frame = document.querySelector(".app-frame");
    frame?.classList.add("complete-mode");
    return () => frame?.classList.remove("complete-mode");
  }, []);

  return (
    <div className="complete-page">
      <img src={topLogo} alt="Top Logo" className="top-logo" />

      {/* ✅ 가운데 묶음 */}
      <div className="center-stack">
        <div className="main-icon-wrapper">
          <div className="main-icon">
            <img src={fridgeCompleteIcon} alt="Fridge Complete Icon" />
          </div>
        </div>

        <h2 className="title">냉장고 생성 완료 !</h2>
        <p className="subtitle">맞춤형 레시피를 추천해드릴까요?</p>

        <div className="button-group">
          <button className="yes-btn" onClick={() => navigate("/Menu")}>
            <FaCheck /> 네
          </button>
          <button className="no-btn" onClick={() => navigate("/")}>
            <FaTimes /> 아니오
          </button>
        </div>
      </div>
    </div>
  );
}
