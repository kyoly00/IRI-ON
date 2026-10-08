import baby1 from "../assets/baby1.png";
import baby2 from "../assets/baby2.png";
import baby3 from "../assets/baby3.png";
import baby4 from "../assets/baby4.png";

export const AVATARS = [
  { value: "baby1", label: "보라 머리 캐릭터", src: baby1 },
  { value: "baby2", label: "주황 모자 셰프", src: baby2 },
  { value: "baby3", label: "토끼 모자 캐릭터", src: baby3 },
  { value: "baby4", label: "곰 모자 캐릭터", src: baby4 },
];

export const AGE_GROUPS = [
  ["unspecified", "선택 안 함"],
  ["under_8", "7세 이하"],
  ["8_13", "8–13세"],
  ["14_18", "14–18세"],
  ["19_34", "19–34세"],
  ["35_49", "35–49세"],
  ["50_64", "50–64세"],
  ["65_plus", "65세 이상"],
];

export const SUPERVISION_LEVELS = [
  ["always_together", "항상 다른 사람과 함께 요리"],
  ["sometimes_help", "위험한 작업만 도움받기"],
  ["independent", "혼자 요리 가능"],
];

export const SKILL_LEVELS = [
  ["not_used", "사용하지 않음"],
  ["with_help", "도움받아 사용"],
  ["independent", "혼자 사용"],
];

export const SAFETY_TOOLS = [
  ["fire_skill", "🔥", "불"],
  ["knife_skill", "🔪", "칼"],
  ["scissors_skill", "✂️", "가위"],
  ["peeler_skill", "🥕", "필러"],
];

export const ALLERGY_OPTIONS = [
  "우유",
  "계란",
  "땅콩",
  "새우",
  "밀",
  "호두",
  "메밀",
  "대두",
  "복숭아",
];
export const DIET_OPTIONS = [
  "채식",
  "비건",
  "유제품 제외",
  "돼지고기 제외",
  "소고기 제외",
  "저염식",
];

export const presetAvatar = (value) =>
  AVATARS.find((item) => item.value === value)?.src || baby1;

export const toggleListValue = (values, value) =>
  values.includes(value)
    ? values.filter((item) => item !== value)
    : [...values, value];

export async function responseError(response, fallback) {
  let body = null;
  try {
    body = await response.json();
  } catch {
    /* response may not be JSON */
  }
  const detail = Array.isArray(body?.detail)
    ? body.detail.map((item) => item.msg || String(item)).join(", ")
    : body?.detail || body?.message || body?.error;
  const requestId = body?.request_id ? ` (요청 ID: ${body.request_id})` : "";
  return new Error(`${detail || fallback} [${response.status}]${requestId}`);
}
