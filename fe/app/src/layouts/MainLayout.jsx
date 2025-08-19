// src/layouts/MainLayout.jsx
import { Outlet } from "react-router-dom";
import BottomNav from "../components/BottomNav";

export default function MainLayout() {
  return (
    <>
      <main className="content">
        <Outlet />
      </main>
      <BottomNav />
    </>
  );
}
