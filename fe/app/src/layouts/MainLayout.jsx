// src/layouts/MainLayout.jsx
<<<<<<< HEAD
import { Outlet, NavLink, Link } from "react-router-dom";
=======
import { Outlet } from "react-router-dom";
<<<<<<< Updated upstream
import BottomNav from "../components/BottomNav";
=======
import BottomNav from "../components/BottomNav.jsx"; // 아이콘 네비
>>>>>>> Stashed changes
>>>>>>> 254c1a0 (하단바 수정)

export default function MainLayout() {
  return (
    <div className="app-layout">
      <main className="content">
        <Outlet />
      </main>
<<<<<<< HEAD

      {/* ⬇️ Tailwind 제거하고 .bn 구조로 */}
      <nav className="bn">
        <div className="bn-side bn-left">
          <NavLink to="/home"   className={({isActive}) => `bn-item ${isActive ? "bn-active" : ""}`}>홈</NavLink>
          <NavLink to="/fridge" className={({isActive}) => `bn-item ${isActive ? "bn-active" : ""}`}>냉장고</NavLink>
        </div>

        <Link to="/home" className="bn-fab" aria-label="중앙">🍳</Link>

        <div className="bn-side bn-right">
          <NavLink to="/menu"    className={({isActive}) => `bn-item ${isActive ? "bn-active" : ""}`}>메뉴</NavLink>
          <NavLink to="/profile" className={({isActive}) => `bn-item ${isActive ? "bn-active" : ""}`}>프로필</NavLink>
        </div>
      </nav>
=======
<<<<<<< Updated upstream
=======

      {/* 하단바 */}
>>>>>>> Stashed changes
      <BottomNav />
>>>>>>> 254c1a0 (하단바 수정)
    </div>
  );
}
