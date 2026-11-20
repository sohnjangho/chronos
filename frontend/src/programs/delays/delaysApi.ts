// 지연 기록 API(Task 33, backend/app/programs/delays/schemas.py). 날짜는 YYYY-MM-DD, 일수는 근무일, 금액은 원.
// 영향·합계·준공 날짜는 모두 서버(app/core) 계산값이다. 화면은 날짜를 계산하지 않는다.
import { api } from '../../shared/api';
import type { MovedActivity, PreviewView } from '../../os/schedulePreview';

export type Responsibility = 'owner' | 'ours' | 'force' | 'undecided';

export interface Named {
  id: string;
  name: string;
}

export interface Impact {
  /** 일정에 넣었는가(끝난 작업·마일스톤·없는 액티비티면 false, 까닭은 note). */
  applied: boolean;
  note: string | null;
  finish_before: string;
  finish_after: string;
  finish_delta: number;
  /** 여유로 흡수된 근무일. */
  absorbed: number;
  milestones: { activity_id: string; name: string; before: string; after: string; delta: number }[];
  critical_added: Named[];
  critical_removed: Named[];
  affected: string[];
  new_clashes: { resource_id: string; name: string; first: string; days: number; over: number }[];
  /** finish_delta × 하루 금액(하루 금액이 없으면 null). */
  cost: number | null;
}

export interface DelayEvent {
  id: number;
  activity_id: string;
  activity_name: string;
  start_date: string;
  days: number;
  cause: string;
  responsibility: Responsibility;
  daily_cost: number | null;
  evidence: string;
  source: 'user' | 'chat' | 'actual';
  status: 'open' | 'reflected';
  impact: Impact | null;
  analyzed_version: number | null;
  reflected_version: number | null;
  /** 응답에서는 늘 false(GET 이 먼저 다시 분석한다) — 화면은 쓰지 않는다. */
  stale: boolean;
  created_by: string;
  created_at: string;
}

export interface Totals {
  finish_impact: number;
  by_responsibility: Record<Responsibility, number>;
  absorbed: number;
  absorbed_events: number;
  cost: number | null;
  open_count: number;
}

export interface Finish {
  /** Plan: 지금 버전을 실적·기록한 지연 없이 계산한 준공(지연은 Plan 을 옮기지 않는다). */
  plan: string | null;
  current: string;
  /** 열린 사건까지 넣은 준공. */
  with_open: string;
  deadline: string | null;
  /** 근무일(with_open → deadline), 늦으면 음수. */
  deadline_float: number | null;
}

export interface DelaysData {
  schedule_id: number;
  version: number;
  events: DelayEvent[];
  totals: Totals;
  finish: Finish;
}

/** 새 사건. source 'actual'(실적 입력에서 감지 — 이미 일정에 들어감)이면 before_version 이 있어야 한다. */
export interface DelayBody {
  activity_id: string;
  start_date: string;
  days: number;
  cause: string;
  responsibility: Responsibility;
  daily_cost: number | null;
  evidence: string;
  source?: 'actual';
  before_version?: number;
}

/** 고치기: 바뀐 칸만 보낸다(같은 값도 잠긴 칸 변경으로 본다). daily_cost 만 null 로 비운다. */
export type DelayPatch = Partial<Omit<DelayBody, 'source' | 'before_version'>>;

export interface PreviewData {
  view: PreviewView;
  moved: MovedActivity[];
}

const base = (id: number) => `/api/schedules/${id}/delays`;
const send = (method: string, body: unknown) => ({ method, body: JSON.stringify(body) });

export const getDelays = (id: number) => api<DelaysData>(base(id));
export const postDelay = (id: number, body: DelayBody) => api<DelaysData>(base(id), send('POST', body));
export const patchDelay = (id: number, eid: number, patch: DelayPatch) => api<DelaysData>(`${base(id)}/${eid}`, send('PATCH', patch));
export const analyzeDelays = (id: number) => api<DelaysData>(`${base(id)}/analyze`, { method: 'POST' });
export const makeScenario = (id: number) => api<{ scenario_id: number }>(`${base(id)}/scenario`, send('POST', {}));
export const getDelayPreview = (id: number) => api<PreviewData>(`${base(id)}/preview`);
