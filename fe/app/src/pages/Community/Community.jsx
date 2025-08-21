import React, { useState } from "react";
import { useNavigate } from "react-router-dom"; // ✅ 추가
import "./Community.css";
import topLogo from "../../assets/top_logo.png";

// ✅ 로컬 이미지
import food1 from "../../assets/community/food1.png";
import food2 from "../../assets/community/food2.png";
import food3 from "../../assets/community/food3.png";

import {
  FiSearch,
  FiHeart,
  FiMessageCircle,
  FiShare2,
  FiBookmark,
  FiBell,
} from "react-icons/fi";

const initialPosts = [
  {
    id: 1,
    author: { name: "김서희", avatar: "https://i.pravatar.cc/100?img=47" },
    time: "2시간 전",
    image: food1,
    tags: ["매우 쉬운 요리", "어린이 요리", "건강한 음식"],
    text: "인생 첫 베이킹 도전! 🧑‍🍳 오븐 사용법이 어려워서 셰프얌이 도와줬어요...",
    likes: 12,
    liked: false,
  },
  {
    id: 2,
    author: { name: "이혜란", avatar: "https://i.pravatar.cc/100?img=12" },
    time: "3시간 전",
    image: food2,
    tags: ["카레라이스", "아이맘미", "채소 가득 음식"],
    text:
      "제가 만든 소고기 덮밥 보세요! 🥢 완벽탄단지에 다양한 채소가 들어갔고 아빠가 엄지 맛있다고 하셨어요! ✨",
    likes: 24,
    liked: false,
  },
  {
    id: 3,
    author: { name: "심재민", avatar: "https://i.pravatar.cc/100?img=5" },
    time: "6시간 전",
    image: food3,
    tags: ["라면보다 쉬움", "건강 식사", "간단해요"],
    text: "비 갠 뒤에 쌀쌀~ 날에는 고기국수 🍜 생각보다 조리법이 간단해요.",
    likes: 18,
    liked: false,
  },
];

export default function Community() {
  const [posts, setPosts] = useState(initialPosts);
  const nav = useNavigate(); // ✅ 네비게이터

  const toggleLike = (id) => {
    setPosts((prev) =>
      prev.map((p) =>
        p.id === id
          ? { ...p, liked: !p.liked, likes: p.liked ? p.likes - 1 : p.likes + 1 }
          : p
      )
    );
  };

  // ✅ 개인 피드로 이동 (state로 프로필 정보 전달)
  const goPersonal = (author) => {
    nav("/personal", {
      state: {
        profile: {
          name: author.name,
          avatar: author.avatar,
          handle: "@chef_yum",
          posts: 9,
          followers: "1.2K",
          following: 856,
        },
      },
    });
  };

  return (
    <div className="cm-wrap">
      {/* Top bar */}
      <div className="cm-top">
        <img src={topLogo} alt="CHEF YUM" className="cm-logo" />
        <div className="cm-actions">
          <FiSearch />
          <FiHeart />
          <FiBell />
        </div>
      </div>

      {/* Feed */}
      <div className="cm-feed">
        {posts.map((p) => (
          <article key={p.id} className="post-card">
            <header className="post-header">
              <img
                className="avatar"
                src={p.author.avatar}
                alt={p.author.name}
                onClick={() => goPersonal(p.author)}        // ✅ 클릭 이동
                style={{ cursor: "pointer" }}
              />
              <div
                className="meta"
                onClick={() => goPersonal(p.author)}        // ✅ 이름/시간 클릭도 이동
                style={{ cursor: "pointer" }}
              >
                <div className="name">{p.author.name}</div>
                <div className="time">{p.time}</div>
              </div>
            </header>

            <div className="post-photo">
              <img src={p.image} alt="post" />
            </div>

            <div className="post-actions">
              <button
                className={`icon-btn ${p.liked ? "liked" : ""}`}
                onClick={() => toggleLike(p.id)}
                aria-label="좋아요"
                title="좋아요"
              >
                <FiHeart />
                <span>{p.likes}</span>
              </button>
              <button className="icon-btn" title="댓글">
                <FiMessageCircle />
              </button>
              <button className="icon-btn" title="공유">
                <FiShare2 />
              </button>
              <div className="spacer" />
              <button className="icon-btn" title="저장">
                <FiBookmark />
              </button>
            </div>

            <div className="post-tags">
              {p.tags.map((t, i) => (
                <span key={i} className={`tag tag-${(i % 5) + 1}`}>
                  #{t}
                </span>
              ))}
            </div>

            <p className="post-text">{p.text}</p>
          </article>
        ))}
      </div>
    </div>
  );
}
