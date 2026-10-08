import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import "./Welcome2.css";
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

const initialSkills = {
  fire_skill: "with_help",
  knife_skill: "with_help",
  scissors_skill: "with_help",
  peeler_skill: "with_help",
};

export default function Welcome2() {
  // 회원가입 직후 전달된 userId를 우선 사용하고, 새로고침 시 localStorage 값을 사용한다.
  const navigate = useNavigate();
  const location = useLocation();
  const userId =
    location.state?.userId || localStorage.getItem("user_id") || "";
  const [step, setStep] = useState(1);
  const [submitting, setSubmitting] = useState(false);
  const [toolsList, setToolsList] = useState([]);
  const [selectedTools, setSelectedTools] = useState(new Set());
  const [profile, setProfile] = useState({
    name: "",
    cooking_level: 1,
    age_group: "unspecified",
    supervision_level: "sometimes_help",
    ...initialSkills,
    avatar_type: "preset",
    avatar_value: "baby1",
    photo_consent_confirmed: false,
    allergy_status: "unknown",
    allergies: [],
    dietary_restrictions: [],
    disliked_ingredients: [],
  });
  const [dislikedText, setDislikedText] = useState("");

  // 공개 도구 목록은 인증 없이 불러오며, 선택 결과 저장에는 access token을 사용한다.
  useEffect(() => {
    if (userId) localStorage.setItem("user_id", String(userId));
    fetch(api("/tools"))
      .then((res) => (res.ok ? res.json() : []))
      .then(setToolsList)
      .catch(console.error);
  }, [userId]);

  const update = (key, value) =>
    setProfile((current) => ({ ...current, [key]: value }));
  const toggleProfileList = (key, value) =>
    update(key, toggleListValue(profile[key], value));
  const isChild = ["under_8", "8_13"].includes(profile.age_group);

  const next = () => {
    // 단계별 필수값만 검사해 긴 단일 폼에서 오는 입력 부담을 줄인다.
    if (step === 1 && !profile.name.trim())
      return alert("닉네임을 입력해주세요.");
    if (
      step === 3 &&
      profile.allergy_status === "has" &&
      profile.allergies.length === 0
    ) {
      return alert(
        "알레르기 항목을 선택하거나 ‘잘 모르겠어요’를 선택해주세요.",
      );
    }
    setStep((value) => Math.min(4, value + 1));
  };

  const submitProfile = async () => {
    // 프로필과 보유 도구를 모두 저장한 뒤에만 온보딩을 완료한다.
    if (!userId || !localStorage.getItem("access_token")) {
      alert("로그인 정보가 없습니다. 다시 로그인해주세요.");
      navigate("/welcome1");
      return;
    }
    setSubmitting(true);
    try {
      const payload = {
        ...profile,
        name: profile.name.trim(),
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

      const toolPayload = [...selectedTools].map((tool_id) => ({ tool_id }));
      const toolsResponse = await authFetch("/users/tools", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(toolPayload),
      });
      if (!toolsResponse.ok)
        throw await responseError(toolsResponse, "조리도구 저장 실패");
      localStorage.setItem("user_name", profile.name.trim());
      localStorage.setItem("profile_level", String(profile.cooking_level));
      navigate("/home");
    } catch (error) {
      console.error(error);
      alert(error.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="w2-page">
      <header className="w2-header">
        <div className="w2-progress" aria-label={`4단계 중 ${step}단계`}>
          {[1, 2, 3, 4].map((value) => (
            <span key={value} className={value <= step ? "active" : ""} />
          ))}
        </div>
        <h1>
          {
            [
              "나를 소개해 주세요",
              "안전하게 요리해요",
              "먹거리 정보를 알려주세요",
              "조리도구를 골라주세요",
            ][step - 1]
          }
        </h1>
        <p>
          필수 정보만 먼저 설정하고 나머지는 프로필에서 언제든 바꿀 수 있어요.
        </p>
      </header>

      {/* 1단계: 기본 프로필과 사용자가 직접 정하는 요리 레벨 */}
      {step === 1 && (
        <section className="w2-card">
          <div className="w2-hero">
            <img
              className="w2-avatar"
              src={presetAvatar(profile.avatar_value)}
              alt="선택한 아바타"
            />
            <input
              className="w2-name"
              value={profile.name}
              maxLength={20}
              placeholder="닉네임"
              onChange={(e) => update("name", e.target.value)}
            />
          </div>
          <div className="w2-card-title">아바타 선택</div>
          <div className="w2-avatar-grid">
            {AVATARS.map((avatar) => (
              <button
                type="button"
                key={avatar.value}
                className={
                  profile.avatar_value === avatar.value ? "selected" : ""
                }
                onClick={() => update("avatar_value", avatar.value)}
              >
                <img src={avatar.src} alt={avatar.label} />
              </button>
            ))}
          </div>
          <label className="w2-field">
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
          <div className="w2-card-title">
            내가 생각하는 요리 레벨: Lv.{profile.cooking_level}
          </div>
          <div className="w2-level-grid">
            {Array.from({ length: 10 }, (_, index) => index + 1).map(
              (level) => (
                <button
                  type="button"
                  key={level}
                  className={profile.cooking_level === level ? "selected" : ""}
                  onClick={() => update("cooking_level", level)}
                >
                  {level}
                </button>
              ),
            )}
          </div>
        </section>
      )}

      {/* 2단계: 보호 수준과 위험 도구별 안전 수준 */}
      {step === 2 && (
        <section className="w2-card">
          <label className="w2-field">
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
          <p className="w2-note">
            각 도구를 얼마나 안전하게 사용할 수 있는지 선택하세요. 일괄 선택은
            안전을 위해 제공하지 않아요.
          </p>
          {SAFETY_TOOLS.map(([key, icon, label]) => (
            <div className="w2-safety-row" key={key}>
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
          {isChild && (
            <p className="w2-note emphasis">
              실제 사진 등록은 보호자 확인 후 프로필 수정 화면에서 할 수 있어요.
            </p>
          )}
        </section>
      )}

      {/* 3단계: 알레르기·식이 제한·비선호 재료 */}
      {step === 3 && (
        <section className="w2-card">
          <div className="w2-card-title">알레르기가 있나요?</div>
          <div className="w2-choice-row">
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
            <div className="w2-chip-options">
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
          <div className="w2-card-title spaced">
            식이 제한 <small>(선택)</small>
          </div>
          <div className="w2-chip-options">
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
          <label className="w2-field">
            먹고 싶지 않은 재료 <small>(쉼표로 구분, 선택)</small>
            <input
              value={dislikedText}
              onChange={(e) => setDislikedText(e.target.value)}
              placeholder="예: 가지, 오이"
            />
          </label>
        </section>
      )}

      {/* 4단계: 선택 사항인 보유 조리도구 */}
      {step === 4 && (
        <section className="w2-card">
          <div className="w2-toolbar">
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
          <p className="w2-note">
            선택하지 않고 완료해도 나중에 프로필에서 설정할 수 있어요.
          </p>
          <div className="w2-grid-3">
            {toolsList.map((tool) => (
              <button
                type="button"
                key={tool.tool_id}
                className={`w2-appliance ${selectedTools.has(tool.tool_id) ? "selected" : ""}`}
                onClick={() =>
                  setSelectedTools((current) => {
                    const nextSet = new Set(current);
                    nextSet.has(tool.tool_id)
                      ? nextSet.delete(tool.tool_id)
                      : nextSet.add(tool.tool_id);
                    return nextSet;
                  })
                }
              >
                {tool.name}
              </button>
            ))}
          </div>
        </section>
      )}

      <div className="w2-actions">
        {step > 1 && (
          <button
            type="button"
            className="w2-back"
            onClick={() => setStep((value) => value - 1)}
          >
            이전
          </button>
        )}
        {step < 4 ? (
          <button type="button" className="w2-submit" onClick={next}>
            다음
          </button>
        ) : (
          <button
            type="button"
            className="w2-submit"
            disabled={submitting}
            onClick={submitProfile}
          >
            {submitting ? "저장 중..." : "설정 완료"}
          </button>
        )}
      </div>
    </div>
  );
}
