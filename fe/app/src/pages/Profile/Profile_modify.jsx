import { useEffect, useState } from "react";
import "./Profile_modify.css";
import { api, authFetch } from "../../lib/api";
import {
  AGE_GROUPS,
  ALLERGY_OPTIONS,
  AVATARS,
  DIET_OPTIONS,
  SAFETY_TOOLS,
  SKILL_LEVELS,
  SUPERVISION_LEVELS,
  presetAvatar,
  responseError,
  toggleListValue,
} from "../../lib/profile-options";

const emptyProfile = {
  name: "셰프",
  cooking_level: 1,
  age_group: "unspecified",
  supervision_level: "sometimes_help",
  fire_skill: "with_help",
  knife_skill: "with_help",
  scissors_skill: "with_help",
  peeler_skill: "with_help",
  avatar_type: "preset",
  avatar_value: "baby1",
  avatar_url: null,
  photo_consent_confirmed: false,
  allergy_status: "unknown",
  allergies: [],
  dietary_restrictions: [],
  disliked_ingredients: [],
};

export default function ProfileModify() {
  // 서버 프로필을 단일 상태로 관리해 프리셋/업로드 아바타와 상세 설정을 함께 저장한다.
  const [profile, setProfile] = useState(emptyProfile);
  const [toolsList, setToolsList] = useState([]);
  const [selectedTools, setSelectedTools] = useState(new Set());
  const [dislikedText, setDislikedText] = useState("");
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [showToast, setShowToast] = useState(false);
  const update = (key, value) =>
    setProfile((current) => ({ ...current, [key]: value }));
  const toggleProfileList = (key, value) =>
    update(key, toggleListValue(profile[key], value));
  const isChild = ["under_8", "8_13"].includes(profile.age_group);
  const avatarSource =
    profile.avatar_type === "upload" && profile.avatar_url
      ? profile.avatar_url
      : presetAvatar(profile.avatar_value);

  useEffect(() => {
    // 화면 진입 시 공개 도구, 사용자 프로필, 사용자 보유 도구를 병렬로 불러온다.
    const load = async () => {
      try {
        const [toolsResponse, profileResponse, myToolsResponse] =
          await Promise.all([
            fetch(api("/tools")),
            authFetch("/users/profile"),
            authFetch("/users/tools"),
          ]);
        if (toolsResponse.ok) setToolsList(await toolsResponse.json());
        if (profileResponse.ok) {
          const loaded = await profileResponse.json();
          setProfile({ ...emptyProfile, ...loaded });
          setDislikedText((loaded.disliked_ingredients || []).join(", "));
        }
        if (myToolsResponse.ok) {
          const items = await myToolsResponse.json();
          setSelectedTools(
            new Set(
              items.map((item) =>
                typeof item === "number" ? item : item.tool_id,
              ),
            ),
          );
        }
      } catch (error) {
        console.error(error);
      }
    };
    load();
  }, []);

  const save = async () => {
    // avatar_url은 만료되는 표시용 URL이므로 저장 payload에서는 제외한다.
    if (!profile.name.trim()) return alert("닉네임을 입력해주세요.");
    setSaving(true);
    try {
      const payload = {
        ...profile,
        name: profile.name.trim(),
        avatar_url: undefined,
        disliked_ingredients: dislikedText
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
      };
      const profileResponse = await authFetch("/users/profile", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!profileResponse.ok)
        throw await responseError(profileResponse, "프로필 저장 실패");
      const toolsResponse = await authFetch("/users/tools", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          [...selectedTools].map((tool_id) => ({ tool_id })),
        ),
      });
      if (!toolsResponse.ok)
        throw await responseError(toolsResponse, "조리도구 저장 실패");
      localStorage.setItem("user_name", profile.name.trim());
      localStorage.setItem("profile_level", String(profile.cooking_level));
      setShowToast(true);
      setTimeout(() => setShowToast(false), 1600);
    } catch (error) {
      console.error(error);
      alert(error.message);
    } finally {
      setSaving(false);
    }
  };

  const uploadImage = async (event) => {
    // 실제 파일 검증·EXIF 제거·리사이즈는 신뢰 가능한 백엔드에서 다시 수행한다.
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (isChild && !profile.photo_consent_confirmed)
      return alert("보호자 확인에 동의한 뒤 사진을 등록해주세요.");
    setUploading(true);
    try {
      const form = new FormData();
      form.append("image", file);
      form.append("consent_confirmed", String(profile.photo_consent_confirmed));
      const response = await authFetch("/users/avatar", {
        method: "POST",
        body: form,
      });
      if (!response.ok) throw await responseError(response, "이미지 등록 실패");
      const data = await response.json();
      setProfile((current) => ({ ...current, ...data }));
    } catch (error) {
      console.error(error);
      alert(error.message);
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="pm-page">
      <header className="pm-header">
        <h1>요리 프로필 수정하기</h1>
        <p>안전 설정과 취향을 바꾸면 추천과 조리 안내에 반영돼요.</p>
      </header>

      {/* 아바타와 닉네임: 프리셋은 즉시 선택, 실제 사진은 별도 업로드 */}
      <section className="pm-card pm-profile-card">
        <img src={avatarSource} alt="프로필 아바타" className="pm-avatar-lg" />
        <input
          className="pm-name-input"
          value={profile.name}
          maxLength={20}
          onChange={(e) => update("name", e.target.value)}
        />
        <div className="pm-avatar-grid">
          {AVATARS.map((avatar) => (
            <button
              type="button"
              key={avatar.value}
              className={
                profile.avatar_type === "preset" &&
                profile.avatar_value === avatar.value
                  ? "selected"
                  : ""
              }
              onClick={() =>
                setProfile((current) => ({
                  ...current,
                  avatar_type: "preset",
                  avatar_value: avatar.value,
                  avatar_url: null,
                }))
              }
            >
              <img src={avatar.src} alt={avatar.label} />
            </button>
          ))}
        </div>
        {isChild && (
          <label className="pm-consent">
            <input
              type="checkbox"
              checked={profile.photo_consent_confirmed}
              onChange={(e) =>
                update("photo_consent_confirmed", e.target.checked)
              }
            />{" "}
            보호자가 실제 사진 등록을 확인했습니다.
          </label>
        )}
        <label className="pm-upload">
          {uploading ? "업로드 중..." : "내 사진 등록 (선택)"}
          <input
            type="file"
            accept="image/jpeg,image/png,image/webp"
            disabled={uploading}
            onChange={uploadImage}
          />
        </label>
        <small>사진 없이 캐릭터 아바타만 사용해도 됩니다. 최대 2MB.</small>
      </section>

      {/* 전 연령대와 요리 도움 수준 */}
      <section className="pm-card">
        <div className="pm-card-title">기본 설정</div>
        <label className="pm-field">
          연령대
          <select
            value={profile.age_group}
            onChange={(e) => update("age_group", e.target.value)}
          >
            {AGE_GROUPS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="pm-field">
          요리할 때 도움 수준
          <select
            value={profile.supervision_level}
            onChange={(e) => update("supervision_level", e.target.value)}
          >
            {SUPERVISION_LEVELS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
      </section>

      {/* 사용자가 직접 선택하는 요리 레벨 */}
      <section className="pm-card">
        <div className="pm-card-title">
          🎯 내가 생각하는 요리 레벨: Lv.{profile.cooking_level}
        </div>
        <div className="pm-level-number-grid">
          {Array.from({ length: 10 }, (_, i) => i + 1).map((level) => (
            <button
              type="button"
              key={level}
              className={profile.cooking_level === level ? "selected" : ""}
              onClick={() => update("cooking_level", level)}
            >
              {level}
            </button>
          ))}
        </div>
      </section>

      {/* 위험 도구는 일괄 선택하지 않고 도구별 수준을 명시한다. */}
      <section className="pm-card">
        <div className="pm-card-title">🛡️ 도구별 안전 수준</div>
        {SAFETY_TOOLS.map(([key, icon, label]) => (
          <div className="pm-safety-row" key={key}>
            <strong>
              {icon} {label}
            </strong>
            <div>
              {SKILL_LEVELS.map(([value, text]) => (
                <button
                  type="button"
                  key={value}
                  className={profile[key] === value ? "selected" : ""}
                  onClick={() => update(key, value)}
                >
                  {text}
                </button>
              ))}
            </div>
          </div>
        ))}
      </section>

      {/* 보유 조리도구는 편의를 위해 전체 선택과 선택 해제를 제공한다. */}
      <section className="pm-card">
        <div className="pm-toolbar">
          <span>보유 조리도구</span>
          <button
            type="button"
            onClick={() =>
              setSelectedTools(new Set(toolsList.map((tool) => tool.tool_id)))
            }
          >
            전체 선택
          </button>
          <button type="button" onClick={() => setSelectedTools(new Set())}>
            선택 해제
          </button>
        </div>
        <div className="pm-grid-3">
          {toolsList.map((tool) => (
            <button
              type="button"
              key={tool.tool_id}
              className={`pm-appliance ${selectedTools.has(tool.tool_id) ? "selected" : ""}`}
              onClick={() =>
                setSelectedTools((current) => {
                  const next = new Set(current);
                  next.has(tool.tool_id)
                    ? next.delete(tool.tool_id)
                    : next.add(tool.tool_id);
                  return next;
                })
              }
            >
              {tool.name}
            </button>
          ))}
        </div>
      </section>

      {/* 먹거리 안전 및 추천 개인화를 위한 선택 정보 */}
      <section className="pm-card">
        <div className="pm-card-title">알레르기</div>
        <div className="pm-choice-row">
          {[
            ["none", "없어요"],
            ["has", "있어요"],
            ["unknown", "잘 모르겠어요"],
          ].map(([value, label]) => (
            <button
              type="button"
              key={value}
              className={profile.allergy_status === value ? "selected" : ""}
              onClick={() => update("allergy_status", value)}
            >
              {label}
            </button>
          ))}
        </div>
        {profile.allergy_status === "has" && (
          <div className="pm-chip-options">
            {ALLERGY_OPTIONS.map((item) => (
              <button
                type="button"
                key={item}
                className={profile.allergies.includes(item) ? "selected" : ""}
                onClick={() => toggleProfileList("allergies", item)}
              >
                {item}
              </button>
            ))}
          </div>
        )}
        <div className="pm-card-title pm-spaced">식이 제한</div>
        <div className="pm-chip-options">
          {DIET_OPTIONS.map((item) => (
            <button
              type="button"
              key={item}
              className={
                profile.dietary_restrictions.includes(item) ? "selected" : ""
              }
              onClick={() => toggleProfileList("dietary_restrictions", item)}
            >
              {item}
            </button>
          ))}
        </div>
        <label className="pm-field">
          먹고 싶지 않은 재료
          <input
            value={dislikedText}
            onChange={(e) => setDislikedText(e.target.value)}
            placeholder="예: 가지, 오이 (쉼표로 구분)"
          />
        </label>
      </section>

      <button
        type="button"
        className="pm-submit"
        disabled={saving}
        onClick={save}
      >
        {saving ? "저장 중..." : "프로필 저장"}
      </button>
      {showToast && <div className="pm-save-toast">저장되었습니다.</div>}
    </div>
  );
}
