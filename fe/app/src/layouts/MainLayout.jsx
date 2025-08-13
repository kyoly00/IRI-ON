// src/layouts/MainLayout.jsx
import { Outlet, NavLink, Link } from "react-router-dom";

export default function MainLayout() {
  return (
    <div className="app-layout">
      <main className="content">
        <Outlet />
      </main>

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
    </div>
  );
}
