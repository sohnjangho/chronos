// 비교판 API. 모양은 서버 app/programs/scenarios/schemas.py 그대로(Task 34 비교·요약, Task 26 복사본 제출·버리기).
// 날짜(YYYY-MM-DD)·차이(근무일)·기한·위반 수는 모두 서버 계산값이다. 화면은 날짜를 계산하지 않는다.
import { api, ApiError } from '../../shared/api';

/** 안: current · plan · v:<n> · s:<복사본 id>. 서버와 같은 꼴만 받는다. */
export const REF = /^(current|plan|v:[1-9]\d{0,9}|s:[1-9]\d{0,9})$/;
export const validRef = (s: string | undefined) => (s && REF.test(s) ? s : null);

export interface Peak {
  resource_id: string;
  name: string;
  need: number;
  capacity: number;
  when: string;
}

export interface SideOut {
  ref: string;
  label: string;
  version: number;
  finish: string;
  /** Plan 준공 → 이 안 준공(근무일). Plan 이 계산되지 않으면 null. */
  plan_delta: number | null;
  /** 켜진 finish_by 가운데 가장 이른 기한(YYYY-MM-DD). 없으면 null. */
  deadline: string | null;
  /** 이 안 준공 → 그 기한(근무일, 늦으면 음수). 없으면 null. */
  deadline_float: number | null;
  critical_count: number;
  violations: number;
  /** 자동 점검 안 된 조건 수. */
  uncheckable: number;
  peak: Peak | null;
  changes: string[];
  /** 복사본이 떠 온 버전이 지금 버전이 아님. 반영된(applied) 복사본은 늘 true. */
  stale: boolean;
  /** 복사본의 상태(open·submitted·applied·discarded). 복사본이 아니면 null. */
  status: string | null;
  /** 당김 효과(계획 5 Task 9): 당긴 일수·그 가운데 준공 반영·다음 결정 줄. 당김이 없는 안은 null. */
  accel?: Accel | null;
  /** 당김을 다른 고침과 섞어 따로 셀 수 없을 때의 까닭(그때 accel 은 null). */
  accel_reason?: string | null;
}

export interface Accel {
  pulled_days: number;
  finish_gain: number;
  warn: boolean;
  next_chain: { activity_id: string; name: string; point: boolean }[];
}

export interface RowCell {
  start: string;
  finish: string;
  od: number;
}

export type Change = 'pulled' | 'pushed' | 'same' | 'added' | 'removed' | 'duration';

export interface RowOut {
  activity_id: string;
  name: string;
  wbs: string;
  base: RowCell | null;
  other: RowCell | null;
  /** 근무일(기준 쪽 달력), other − base. 한쪽에만 있으면 null. */
  start_delta: number | null;
  finish_delta: number | null;
  change: Change;
}

export interface CompareOut {
  base: SideOut;
  other: SideOut;
  rows: RowOut[];
  changed_count: number;
}

export interface VersionItem {
  n: number;
  note: string;
  by_kind: string;
  by_name: string;
  is_plan: boolean;
  created_at: string;
}

/** 복사본 id(s:<id> 일 때만). */
export const scenarioId = (ref: string) => (ref.startsWith('s:') ? Number(ref.slice(2)) : null);

// ref 는 REF 꼴만 넘어오므로 그대로 붙인다(주소에 s:4 처럼 보이게).
export const getCompare = (id: number, base: string, other: string) =>
  api<CompareOut>(`/api/schedules/${id}/compare?base=${base}&other=${other}`);
export const getSummary = (id: number) => api<{ sides: SideOut[] }>(`/api/schedules/${id}/compare/summary`);
export const getVersions = (id: number) => api<VersionItem[]>(`/api/schedules/${id}/versions`);
export const submitScenario = (id: number, sid: number, title: string) =>
  api<{ approval_id: number; applied: boolean; status: string }>(`/api/schedules/${id}/scenarios/${sid}/submit`, {
    method: 'POST',
    body: JSON.stringify({ title }),
  });
export const discardScenario = (id: number, sid: number) => api<{ status: string }>(`/api/schedules/${id}/scenarios/${sid}`, { method: 'DELETE' });

/** 오류 글: 서버 글 그대로. */
export const messageOf = (e: unknown) => (e instanceof ApiError ? e.message : '요청을 처리할 수 없습니다.');
