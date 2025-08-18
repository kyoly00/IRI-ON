import { NavLink } from "react-router-dom";
import homeIcon   from "../assets/home.png";
import menuIcon   from "../assets/menu.png";
import fridgeIcon from "../assets/fridge.png";
import profileIcon from "../assets/profile.png";
import logoIcon   from "../assets/logo.png"; // 가운데 아이콘(사진)

export default function BottomNav() {
  const linkCls = ({ isActive }) => "bn-item" + (isActive ? " bn-active" : "");

  return (
    <nav className="bn five" role="navigation" aria-label="Bottom navigation">
      {/* 1. 홈 */}
      <NavLink to="/home" className={linkCls} aria-label="홈">
        <img src={homeIcon} alt="" />
        <span>홈</span>
      </NavLink>

      {/* 2. 메뉴 */}
      <NavLink to="/menu" className={linkCls} aria-label="메뉴">
        <img src={menuIcon} alt="" />
        <span>메뉴</span>
      </NavLink>

      {/* 3. 사진 (중앙, 기능 연결 원하면 to="/camera" 등으로 변경) */}
      <button type="button" className="bn-item bn-center" aria-label="사진">
        <span className="bn-center-ring">
          <img src={logoIcon} alt="" />
        </span>
        <span>사진</span>
      </button>

      {/* 4. 냉장고 */}
      <NavLink to="/fridge" className={linkCls} aria-label="냉장고">
        <img src={fridgeIcon} alt="" />
        <span>냉장고</span>
      </NavLink>

      {/* 5. 프로필 */}
      <NavLink to="/profile" className={linkCls} aria-label="프로필">
        <img src={profileIcon} alt="" />
        <span>프로필</span>
      </NavLink>
    </nav>
  );
}
