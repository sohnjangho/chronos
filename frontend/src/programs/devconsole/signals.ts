// 11-23 에 더한 단계 신호: 서버(devconsole/service.py _step_signals)가 기록된 단계·호출로만 켠다.
// label = 신호 줄, short = 그림 배지, place = 그림에서 붙는 칸(도구 실행 · 조건 점검).
export type SignalPlace = 'tool' | 'check';

export interface SignalInfo {
  label: string;
  short: string;
  place: SignalPlace;
  /** 막았거나 멈춘 신호(빨강·주황 배지). */
  warn?: true;
}

export const STEP_SIGNALS: Record<string, SignalInfo> = {
  info_used: { label: '정보 API 조회', short: '정보 API', place: 'tool' },
  evidence_reused: { label: '저장된 근거 다시 씀', short: '저장된 근거', place: 'tool' },
  evidence_fresh: { label: '새 근거 검색 (Liner)', short: '새 검색', place: 'tool' },
  vision_tool: { label: '도구가 그림 읽기 모델을 부름', short: '그림 읽기', place: 'tool' },
  role_blocked: { label: '역할 규칙으로 도구 거절', short: '역할 거절', place: 'tool', warn: true },
  import_confirmed: { label: '가져오기 단추로 확인', short: '단추 확인', place: 'check' },
  import_refused: { label: '같은 가져오기 되풀이 거절', short: '되풀이 거절', place: 'check', warn: true },
  repair_stopped: { label: '같은 위반 반복 → 고치기 멈춤', short: '반복 위반 멈춤', place: 'check', warn: true },
};

/** 거절 신호 — 실행 추적의 결과 칸이 「실패」 대신 「거절」로 까닭을 보인다. */
export const REFUSAL_SIGNALS = new Set(['role_blocked', 'import_refused']);

export const signalsAt = (lit: string[], place: SignalPlace) => lit.filter((f) => STEP_SIGNALS[f]?.place === place);
