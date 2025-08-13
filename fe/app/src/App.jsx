// src/App.jsx (차이: div.app-shell > div.app-frame 추가)
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import MainLayout from "./layouts/MainLayout";
import Home from "./pages/Home/Home.jsx";
import Menu from "./pages/Menu/Menu.jsx";
import Fridge from "./pages/Fridge/Fridge.jsx";
import Profile from "./pages/Profile/Profile.jsx";
import Welcome from "./pages/Welcome/Welcome.jsx";
import "./index.css";

export default function App() {
  return (
    <BrowserRouter>
      <div className="app-shell">
        <div className="app-frame">
          <Routes>
            <Route path="/" element={<Welcome />} />
            <Route element={<MainLayout />}>
              <Route path="/home" element={<Home />} />
              <Route path="/menu" element={<Menu />} />
              <Route path="/fridge" element={<Fridge />} />
              <Route path="/profile" element={<Profile />} />
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </div>
      </div>
    </BrowserRouter>
  );
}
