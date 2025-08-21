import React from "react";
import { useLocation, useNavigate } from "react-router-dom";
import "./Personal.css";
import topLogo from "../../assets/top_logo.png";
import totalFood from "../../assets/community/total_food.png"; // ✅ 한 장 이미지
import { FiChevronLeft } from "react-icons/fi";

export default function Personal() {
  const nav = useNavigate();
  const { state } = useLocation();
  const profile =
    state?.profile || {
      name: "세프얌",
      avatar: "https://i.pravatar.cc/100?img=47",
      handle: "@chef_yum",
      posts: 9,
      followers: "1.2K",
      following: 856,
    };

  return (
    <div className="personal-page">
      {/* 상단바 */}
      <div className="personal-top">
        <button className="back-btn" onClick={() => nav(-1)} aria-label="뒤로">
          <FiChevronLeft />
        </button>
        <img src={topLogo} alt="CHEF YUM" className="personal-logo" />
        <div style={{ width: 32 }} />
      </div>

      {/* 프로필 카드 */}
      <section className="profile-card">
        <img className="profile-avatar" src={profile.avatar} alt={profile.name} />
        <div className="profile-name">{profile.name}</div>
        <div className="profile-handle">{profile.handle}</div>
        <div className="profile-stats">
          <div><strong>{profile.posts}</strong><span>게시물</span></div>
          <div><strong>{profile.followers}</strong><span>팔로워</span></div>
          <div><strong>{profile.following}</strong><span>팔로잉</span></div>
        </div>
      </section>

      {/* ✅ 사진 한 장만 크게 */}
      <section className="photo-one">
        <img src={totalFood} alt="내 요리 사진첩" className="mosaic-img" />
      </section>
    </div>
  );
}
