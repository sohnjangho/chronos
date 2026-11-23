import { api } from '../api';

// 알림 연결 상한(Task 70 계약 LimitsOut). 설정 「알림 연결」과 개발 콘솔이 같은 길을 쓴다.
const path = (connectionId: number) => `/api/notify/connections/${connectionId}/limits`;

/** values: 지금 쓰이는 값 · defaults: 기본값 · ranges: 칸마다 받는 [최소, 최대](양 끝 포함). 칸 이름은 서버의 것 그대로. */
export interface LimitsOut {
  values: Record<string, number>;
  defaults: Record<string, number>;
  ranges: Record<string, [number, number]>;
}

export const limitsApi = {
  get: (connectionId: number) => api<LimitsOut>(path(connectionId)),
  /** 바꿀 칸만 보낸다. 검사는 서버 한 곳(422 invalid_limits, detail {칸: 까닭}). */
  put: (connectionId: number, changes: Record<string, number>) =>
    api<LimitsOut>(path(connectionId), { method: 'PUT', body: JSON.stringify(changes) }),
  /** 바꾼 칸을 모두 지워 기본값으로. */
  reset: (connectionId: number) => api<LimitsOut>(`${path(connectionId)}/reset`, { method: 'POST' }),
};
