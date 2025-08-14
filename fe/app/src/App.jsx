// src/App.jsx
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import MainLayout from "./layouts/MainLayout";
<<<<<<< HEAD
import Home from "./pages/Home/Home.jsx";
import Menu from "./pages/Menu/Menu.jsx";
import Fridge from "./pages/Fridge/Fridge.jsx";
import FridgeComplete from "./pages/FridgeComplete/FridgeComplete.jsx";
import CookingExplain from "./pages/CookingExplain/CookingExplain.jsx"; 
import Welcome from "./pages/Welcome/Welcome.jsx";
import Welcome2 from "./pages/Welcome/Welcome2.jsx";
import "./index.css";

=======

// 온보딩 (하단바 없음)
import Welcome from "./pages/Welcome/Welcome.jsx";
import Welcome2 from "./pages/Welcome/Welcome2.jsx";

// 메인 탭 (하단바 있음)
import Home from "./pages/Home/Home.jsx";
import Menu from "./pages/Menu/Menu.jsx";
import Fridge from "./pages/Fridge/Fridge.jsx";
import Profile from "./pages/Profile/Profile.jsx";

// 독립 페이지 (하단바 없음)
import FridgeComplete from "./pages/FridgeComplete/FridgeComplete.jsx";
import CookingExplain from "./pages/CookingExplain/CookingExplain.jsx";

import "./index.css";

>>>>>>> b331b489b4d342156a09f1dda4bc3b51d0260bbe
export default function App() {
  return (
    <BrowserRouter>
      <div className="app-shell">
        <div className="app-frame">
          <Routes>
<<<<<<< HEAD
            {/* 온보딩 화면 (하단바 없음) */}
            <Route path="/" element={<Welcome />} />
            <Route path="/welcome2" element={<Welcome2 />} />

            {/* 하단바 있는 페이지 */}
=======
            {/* 온보딩 흐름: / -> /welcome2 -> /home */}
            <Route path="/" element={<Welcome />} />
            <Route path="/welcome2" element={<Welcome2 />} />

            {/* 하단바 포함 구간 */}
>>>>>>> b331b489b4d342156a09f1dda4bc3b51d0260bbe
            <Route element={<MainLayout />}>
              <Route path="/home" element={<Home />} />     {/* 루트 이후 메인 */}
              <Route path="/menu" element={<Menu />} />
              <Route path="/fridge" element={<Fridge />} />
<<<<<<< HEAD
            
            </Route>

            {/* 하단바 없는 독립 페이지 */}
            <Route path="/fridgecomplete" element={<FridgeComplete />} />
            <Route path="/CookingExplain/:id" element={<CookingExplain />} />

            {/* 잘못된 경로 처리 */}
=======
              <Route path="/profile" element={<Profile />} />
            </Route>

            {/* 하단바 없는 독립 단계들: Fridge -> FridgeComplete -> Menu -> CookingExplain */}
            <Route path="/fridgecomplete" element={<FridgeComplete />} />
            <Route path="/CookingExplain/:id" element={<CookingExplain />} />

            {/* 잘못된 경로는 첫 화면으로 */}
>>>>>>> b331b489b4d342156a09f1dda4bc3b51d0260bbe
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </div>
      </div>
    </BrowserRouter>
  );
}
