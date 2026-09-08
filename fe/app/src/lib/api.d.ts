/** JavaScript URL helper의 TypeScript 계약. 구현은 기존 api.js를 그대로 사용한다. */
export const API_BASE: string;
export const WS_BASE: string;
export function api(path?: string): string;
export function ws(path?: string): string;
export function get(path: string, init?: RequestInit): Promise<any>;
export function post(path: string, body: unknown, init?: RequestInit): Promise<any>;
