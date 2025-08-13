// src/layouts/MainLayout.jsx
import { Outlet } from "react-router-dom";
import BottomNav from "../components/BottomNav.jsx"; // 아이콘 네비

export default function MainLayout() {
  return (
    <div className="app-layout">
      <main className="content">
        <Outlet />
      </main>

      {/* 하단바 */}
      <BottomNav />
    </div>
  );
}
