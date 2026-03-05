export const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";
export const WS_BASE = import.meta.env.VITE_WS_BASE_URL ?? "";

const ensureLeadingSlash = (path = "") =>
  path.startsWith("/") ? path : `/${path}`;

const buildUrl = (base, path) => {
  const normalized = ensureLeadingSlash(path || "");
  if (!base) return normalized;
  return `${base.replace(/\/$/, "")}${normalized}`;
};

/**
 * REST 호출을 위한 기본 URL 생성기.
 * 사용 예: fetch(api("/assistant/openai-realtime/session"))
 */
export const api = (path = "") => buildUrl(API_BASE, path);

/**
 * WebSocket 전용 URL 생성기. 환경 변수가 없으면 현재 Origin을 사용한다.
 */
export const ws = (path = "") =>
  WS_BASE ? buildUrl(WS_BASE, path) : ensureLeadingSlash(path);

/**
 * 간단한 GET 래퍼. 인증 쿠키 포함(fetch default 옵션 통일 목적).
 */
export async function get(path, init) {
  const r = await fetch(api(path), { ...(init || {}), credentials: "include" });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

/**
 * JSON body를 포함한 POST 래퍼.
 */
export async function post(path, body, init) {
  const r = await fetch(api(path), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...((init && init.headers) || {}),
    },
    credentials: "include",
    body: JSON.stringify(body),
    ...(init || {}),
  });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}
