// src/layouts/MainLayout.jsx
import { Outlet, useLocation } from "react-router-dom";
import BottomNav from "../components/BottomNav";   // ✅ 추가
import "../app.css";

const HIDE_ON = ["/welcome", "/welcome1", "/welcome2"]; // 온보딩 페이지들만 숨김

export default function MainLayout() {
  const { pathname } = useLocation();
  const showNav = !HIDE_ON.some(p => pathname.startsWith(p));

  return (
    <div className="phone">
      <div className="phone-body">
        <main className="phone-content">
          <Outlet />
        </main>

        {/* ✅ 하단 네비 실제 렌더링 */}
        {showNav && <BottomNav />}
      </div>
    </div>
  );
}
