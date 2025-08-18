// src/App.jsx
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import MainLayout from "./layouts/MainLayout";

// 페이지들
import Home from "./pages/Home/Home.jsx";
import Menu from "./pages/Menu/Menu.jsx";
import Fridge from "./pages/Fridge/Fridge.jsx";
import ProfileModify from "./pages/Profile/Profile_modify.jsx";

// 온보딩
import Welcome from "./pages/Welcome/Welcome.jsx";
import Welcome1 from "./pages/Welcome/Welcome1.jsx";
import Welcome2 from "./pages/Welcome/Welcome2.jsx";

import "./index.css";

export default function App() {
  return (
    <BrowserRouter>
      <div className="app-shell">
        <div className="app-frame">
          <Routes>
            {/* 온보딩 (하단바 없음) */}
            <Route path="/" element={<Welcome />} />
            <Route path="/welcome1" element={<Welcome1 />} />
            <Route path="/welcome2" element={<Welcome2 />} />

            {/* 메인 (하단바 있음 → MainLayout) */}
            <Route element={<MainLayout />}>
              <Route path="/home" element={<Home />} />
              <Route path="/menu" element={<Menu />} />
              <Route path="/fridge" element={<Fridge />} />
              <Route path="/profile" element={<ProfileModify />} />
            </Route>

            {/* 잘못된 경로 처리 */}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </div>
      </div>
    </BrowserRouter>
  );
}
