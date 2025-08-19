// src/layouts/MainLayout.jsx
import { Outlet, useLocation } from "react-router-dom";
import BottomNav from "../components/BottomNav";

const HIDE_NAV_PATHS = ["/", "/welcome1", "/welcome2"]; // 온보딩 경로

export default function MainLayout() {
  const { pathname } = useLocation();
  const hideNav = HIDE_NAV_PATHS.includes(pathname);

  return (
    <>
      <main className="content">
        <Outlet />
      </main>
      {!hideNav && <BottomNav />}   {/* 온보딩 경로에서는 숨김 */}
    </>
  );
}

