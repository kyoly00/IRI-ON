import { NavLink, Link } from "react-router-dom";
import homeIcon from "../assets/home.png";
import menuIcon from "../assets/menu.png";
import fridgeIcon from "../assets/fridge.png";
import profileIcon from "../assets/profile.png";
import logoIcon from "../assets/logo.png"; // 가운데 마스코트

export default function BottomNav() {
  const linkCls = ({ isActive }) => "bn-item" + (isActive ? " bn-active" : "");

  return (
    <nav className="bn" role="navigation" aria-label="Bottom navigation">
      {/* 좌측 2개 */}
      <div className="bn-side bn-left">
        <NavLink to="/home" className={linkCls} aria-label="홈">
          <img src={homeIcon} alt="" />
          <span>홈</span>
        </NavLink>
        <NavLink to="/menu" className={linkCls} aria-label="메뉴">
          <img src={menuIcon} alt="" />
          <span>메뉴</span>
        </NavLink>
      </div>

      {/* 중앙 플로팅 버튼 */}
      <div className="bn-fab" aria-label="중앙">
        <img src={logoIcon} alt="" />
      </div>

      {/* 우측 2개 */}
      <div className="bn-side bn-right">
        <NavLink to="/fridge" className={linkCls} aria-label="냉장고">
          <img src={fridgeIcon} alt="" />
          <span>냉장고</span>
        </NavLink>
        <NavLink to="/profile" className={linkCls} aria-label="프로필">
          <img src={profileIcon} alt="" />
          <span>프로필</span>
        </NavLink>
      </div>
    </nav>
  );
}
