import { Link, useLocation } from "react-router-dom";
import "./BottomNav.css";

// 아이콘 이미지 불러오기
import homeIcon from "../assets/bottom_bar/home.png";
import fridgeIcon from "../assets/bottom_bar/fridge.png";
import menuIcon from "../assets/bottom_bar/menu.png";
import profileIcon from "../assets/bottom_bar/profile.png";
import logoIcon from "../assets/bottom_bar/logo.png";

export default function BottomNav() {
  const { pathname } = useLocation();

  return (
    <nav className="bottom-nav">
      <Link to="/home" className={`nav-item ${pathname === "/" ? "active" : ""}`}>
        <img src={homeIcon} alt="홈" className="icon" />
        <span>홈</span>
      </Link>

      <Link
        to="/fridge"
        className={`nav-item ${pathname === "/fridge" ? "active" : ""}`}
      >
        <img src={fridgeIcon} alt="냉장고" className="icon" />
        <span>냉장고</span>
      </Link>

      {/* 중앙 FAB (커뮤니티 이동) */}
      <Link to="/community" className="nav-fab">
        <img src={logoIcon} alt="logo" />
      </Link>

      {/* 오른쪽 메뉴 버튼 (Menu.jsx 이동) */}
      <Link
        to="/menu"
        className={`nav-item ${pathname === "/menu" ? "active" : ""}`}
      >
        <img src={menuIcon} alt="메뉴" className="icon" />
        <span>메뉴</span>
      </Link>


      <Link
        to="/profile"
        className={`nav-item ${pathname === "/profile" ? "active" : ""}`}
      >
        <img src={profileIcon} alt="프로필" className="icon" />
        <span>프로필</span>
      </Link>
    </nav>
  );
}
