// src/App.jsx
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import MainLayout from "./layouts/MainLayout";
import Home from "./pages/Home/Home.jsx";
import Menu from "./pages/Menu/Menu.jsx";
import Fridge from "./pages/Fridge/Fridge.jsx";
import Welcome from "./pages/Welcome/Welcome.jsx";
import Welcome2 from "./pages/Welcome/Welcome2.jsx";

import "./index.css";

export default function App() {
  return (
    <BrowserRouter>
      <div className="app-shell">
        <div className="app-frame">
          <Routes>
            {/* 온보딩들 (하단바 없음) */}
            <Route path="/" element={<Welcome />} />
            <Route path="/welcome2" element={<Welcome2 />} />

            {/* 앱 내부 (하단바 포함) */}
            <Route element={<MainLayout />}>
              <Route path="/home" element={<Home />} />
              <Route path="/menu" element={<Menu />} />
              <Route path="/fridge" element={<Fridge />} />
            </Route>

            {/* 그 외 경로는 첫 화면으로 */}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </div>
      </div>
    </BrowserRouter>
  );
}
