import { BrowserRouter, Routes, Route } from "react-router-dom";
import MainLayout from "./layouts/MainLayout";
import Home from "./pages/Home/Home.jsx";
import Menu from "./pages/Menu/Menu.jsx";
import Fridge from "./pages/Fridge/Fridge.jsx";
import Profile from "./pages/Profile/Profile.jsx";
import "./index.css";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* 하단바 있는 페이지들 */}
        <Route element={<MainLayout />}>
          <Route path="/" element={<Home />} />        {/* 루트 = Home */}
          <Route path="/home" element={<Home />} />
          <Route path="/menu" element={<Menu />} />
          <Route path="/fridge" element={<Fridge />} />
          <Route path="/profile" element={<Profile />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
