// src/pages/Welcome/Welcome.jsx
import { useNavigate } from "react-router-dom";
import logo3D from "../../assets/3dLogo.png";
import "./welcome.css";

export default function Welcome() {
  const navigate = useNavigate();

  return (
    <div className="welcome" id="welcome">   {/* ✅ id 추가 */}
      <div className="stack">
        <section className="hero">
          <div className="avatar">
            <img src={logo3D} alt="셰프 캐릭터" className="char" />
          </div>
        </section>

        <section className="copy">
          <p className="eyebrow">돌봄 공백 아동을 위한</p>
          <h1 className="headline">AI 요리 선생님</h1>
        </section>

        <button className="cta" onClick={() => navigate("/welcome2")}>
          시작하기
        </button>
      </div>
    </div>
  );
}
