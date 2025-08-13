import { useNavigate } from "react-router-dom";
import logo3D from "../../assets/3dLogo.png";
import "./welcome.css";

export default function Welcome() {
  const navigate = useNavigate();

  return (
    <div className="welcome">
      {/* 캐릭터 원형 카드 */}
      <section className="hero">
        <div className="avatar">
          <img src={logo3D} alt="셰프 캐릭터" className="char" />
        </div>
      </section>

      {/* 타이포 */}
      <section className="copy">
        <p className="eyebrow">돌봄 공백 아동을 위한</p>
        <h1 className="headline">AI 요리 선생님</h1>
      </section>

      {/* CTA 버튼 */}
      <button className="cta" onClick={() => navigate("/home")}>
        시작하기
      </button>
    </div>
  );
}
