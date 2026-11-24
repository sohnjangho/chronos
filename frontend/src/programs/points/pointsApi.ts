// 「관리 포인트」 창의 서버 API(계획 5 Task 5·11 — backend/app/programs/points/router.py·board.py). 모양은 서버 그대로이고
// 날짜·여유·당김 효과는 모두 서버(app/core) 계산값이다. 화면은 날짜를 계산하지 않는다(문자열 비교와 자르기만). 번호는 어느 응답에도 없다.
import { api, ApiError } from '../../shared/api';

export interface Point {
  activity_id: string;
  name: string;
  critical: boolean;
  tf: number;
  es: string;
  ef: string;
}

/** 바깥 위험 한 줄(app.points.risk.Risk). status: ok(자료 있음) · none(자료 없음, 본문에 그대로) · skipped(건너뜀, 접어 둠). */
export interface Risk {
  activity_id: string;
  kind: string;
  line: string;
  as_of: string | null;
  source: string | null;
  status: string;
  why?: string;
}

/** 근거 문장 상태(app.points.card.quote_json). */
export interface QuoteState {
  status: 'pending' | 'ready' | 'failed';
  message: string;
  error_code: string | null;
  quotes: { text: string; url: string; title: string }[];
}

export interface Diff {
  added: Point[];
  removed: string[];
  tightened: [string, number, number][];
  became_critical: string[];
  before_tf: Record<string, number>;
}

/** GET /api/schedules/{id}/points. card 는 바뀜이 있을 때의 카드 꼴(담당 협력사 responsible 이 있으면 쓴다). */
export interface PointsView {
  schedule_id: number;
  version: number;
  basis: { tf_days: number; window_weeks: number };
  points: Point[];
  diff: Diff | null;
  risk_status: string;
  risk_message: string;
  risks: Risk[];
  quotes: Record<string, QuoteState | null>;
  card: { new?: { activity_id: string; responsible?: string[] }[]; tightened?: { activity_id: string; responsible?: string[] }[] } | null;
}

export interface Removed {
  activity_id: string;
  name: string;
  reason: string;
  label: string;
  before_tf?: number;
  tf?: number;
}

export interface Change {
  activity_id: string;
  name: string;
  tf: number;
  before_tf?: number;
  became_critical?: boolean;
}

/** 바뀜 기록 한 줄(버전 또는 열린 지연의 가정 what_if). recorded=false 면 차이를 적지 않은 버전(처음 계산 등). */
export interface HistoryEntry {
  version: number;
  what_if: boolean;
  saved_at: string | null;
  note: string;
  recorded: boolean;
  count: number | null;
  critical: number | null;
  new: Change[];
  more: number;
  tightened: Change[];
  removed: Removed[];
}

export interface FloatRow {
  version: number;
  tf: number | null;
  critical: boolean | null;
  point: boolean;
}

/** GET …/points/history — 보드 칸(window)·바뀜 기록·(activity 를 주면) 버전별 여유. */
export interface History {
  schedule_id: number;
  version: number;
  basis: { tf_days: number; window_weeks: number };
  window: { data_date: string; weeks: { start: string; end: string }[] };
  versions: HistoryEntry[];
  preview: HistoryEntry | null;
  float: FloatRow[] | null;
}

/** POST …/points/{activity_id}/accel — 도구 points.accel_check 와 같은 꼴(AccelCheckOut). */
export interface AccelResult {
  activity_id: string;
  name: string;
  od_before: number;
  od_after: number;
  pulled_days: number;
  reached_days: number;
  warn: boolean;
  warn_line: string | null;
  summary_line: string;
  finish_before: string;
  finish_after: string;
  next_chain: { activity_id: string; name: string; point: boolean }[];
  same_chain: boolean;
}

export interface Person {
  contact_id: number;
  name: string;
  role_title: string | null;
  company: string | null;
  trade: string | null;
  do_not_contact: boolean;
  channels: Channel[];
}

export type Channel = 'sms' | 'call';
export type Preview = { preview: true; channel: 'sms'; body: string } | { preview: true; channel: 'call'; purpose: string; questions: string[] };

const post = (body: unknown): RequestInit => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
const root = (sid: number) => `/api/schedules/${sid}/points`;
const one = (sid: number, aid: string) => `${root(sid)}/${encodeURIComponent(aid)}`;

export const getView = (sid: number) => api<PointsView>(root(sid));
export const getHistory = (sid: number, activity?: string) =>
  api<History>(`${root(sid)}/history${activity ? `?activity=${encodeURIComponent(activity)}` : ''}`);
export const postAccel = (sid: number, aid: string, days: number) => api<AccelResult>(`${one(sid, aid)}/accel`, post({ days }));
/** [근거 문장 보기]·「다시 찾기」(retry) — 사람이 누를 때만. 찾기는 서버가 뒤에서 한다. */
export const findQuote = (sid: number, aid: string, kind: string, retry: boolean) =>
  api<QuoteState>(`${one(sid, aid)}/quotes/${encodeURIComponent(kind)}`, post({ what_if: false, retry }));
/** 「다시 찾기」: 실패한 바깥 위험 찾기를 다시 띄운다 → 포인트 조회와 같은 꼴(실패가 아니면 409). */
export const retryRisks = (sid: number) => api<PointsView>(`${root(sid)}/risks/retry`, post({ what_if: false }));
export const getPeople = (sid: number, aid: string) => api<{ activity_id: string; name: string; people: Person[] }>(`${one(sid, aid)}/contact`);
export const previewContact = (sid: number, aid: string, contactId: number, channel: Channel) =>
  api<Preview>(`${one(sid, aid)}/contact`, post({ contact_id: contactId, channel, preview: true }));
/** 초안만 만든다(보내지 않음). */
export const draftContact = (sid: number, aid: string, contactId: number, channel: Channel) =>
  api<{ preview: false; card: Record<string, unknown> }>(`${one(sid, aid)}/contact`, post({ contact_id: contactId, channel, preview: false }));

export const errorText = (e: unknown, fallback: string) => (e instanceof ApiError && e.message ? e.message : fallback);
