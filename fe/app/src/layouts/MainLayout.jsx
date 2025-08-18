import { Outlet, useLocation } from "react-router-dom";
import BottomNav from "../components/BottomNav";

const HIDE_ON = ["/", "/welcome1", "/welcome2"]; // 온보딩 페이지 경로

export default function MainLayout() {
  const { pathname } = useLocation();
  const showNav = !HIDE_ON.includes(pathname); // 온보딩이면 false

  return (
    <div className="app-shell">
      <main className="content">
        <Outlet />
      </main>
      {showNav && <BottomNav />} {/* 온보딩 페이지가 아닐 때만 하단바 출력 */}
    </div>
  );
}
