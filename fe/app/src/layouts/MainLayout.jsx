// src/layouts/MainLayout.jsx
import { Outlet } from "react-router-dom";
import BottomNav from "../components/BottomNav";

export default function MainLayout() {
  return (
    <div className="app-shell">
      <main className="content">{/* 하단바에 안 가리게 */}
        <Outlet />
      </main>
      <BottomNav />
    </div>
  );
}
