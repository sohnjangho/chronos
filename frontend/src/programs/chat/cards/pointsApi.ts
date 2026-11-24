// 관리 포인트 API(계획 5 Task 5 — backend/app/programs/points/router.py). 모양은 서버 그대로, 날짜·여유는 서버 계산값.
// 번호는 어느 응답에도 없다.
import { api, ApiError } from '../../../shared/api';
import type { Json } from '../thread';

/** 근거 문장 상태(app.points.card.quote_json). 멈춘 찾는 중은 서버가 failed(error_code "stale")로 준다. */
export interface QuoteState {
  status: 'pending' | 'ready' | 'failed';
  message: string;
  error_code: string | null;
  quotes: { text: string; url: string; title: string }[];
}

/** GET /api/schedules/{id}/points 의 화면이 쓰는 칸. card = points_changed 카드 꼴(바뀜이 없으면 null). */
export interface PointsView {
  schedule_id: number;
  version: number;
  what_if: boolean;
  basis: { tf_days: number; window_weeks: number };
  points: { activity_id: string; name: string; critical: boolean; tf: number; es: string; ef: string }[];
  risk_status: string;
  quotes: Record<string, QuoteState | null>;
  card: Json | null;
}

export interface Person {
  contact_id: number;
  name: string;
  role_title: string | null;
  company: string | null;
  trade: string | null;
  do_not_contact: boolean;
  channels: ('sms' | 'call')[];
}

export type Channel = 'sms' | 'call';
export type Preview = { preview: true; channel: 'sms'; body: string } | { preview: true; channel: 'call'; purpose: string; questions: string[] };

const post = (body: unknown): RequestInit => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
const base = (sid: number, aid: string) => `/api/schedules/${sid}/points/${encodeURIComponent(aid)}`;

export const getPoints = (sid: number, whatIf: boolean) => api<PointsView>(`/api/schedules/${sid}/points?what_if=${whatIf}`);

/** 「주의할 일정」과 같은 차례: 열린 지연 사건이 있으면 그 가정 포인트(없으면 404 → 버전 포인트), 없으면 지금 버전 포인트. */
export async function getLatestPoints(sid: number): Promise<PointsView> {
  const delays = await api<{ events: { status: string }[] }>(`/api/schedules/${sid}/delays`).catch(() => null);
  if (delays?.events.some((e) => e.status === 'open')) {
    try {
      return await getPoints(sid, true);
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 404)) throw e;
    }
  }
  return getPoints(sid, false);
}

/** 「2027-06-03」 → 「06.03」(시안과 같은 월.일). 꼴이 다르면 그대로. */
export const monthDay = (v: unknown) => (typeof v === 'string' ? v.replace(/^\d{4}-(\d{2})-(\d{2})$/, '$1.$2') : '');

/** 실패(멈춘 것 포함)한 외부 영향 찾기를 다시(사람의 「다시 찾기」) → 조회와 같은 꼴. 실패가 아니면 409. */
export const retryRisks = (sid: number, whatIf: boolean) => api<PointsView>(`/api/schedules/${sid}/points/risks/retry`, post({ what_if: whatIf }));

/** [근거 문장 보기]·「다시 찾기」(retry). 찾기는 서버가 뒤에서 한다. */
export const findQuote = (sid: number, aid: string, kind: string, whatIf: boolean, retry: boolean) =>
  api<QuoteState>(`${base(sid, aid)}/quotes/${encodeURIComponent(kind)}`, post({ what_if: whatIf, retry }));

export const getPeople = (sid: number, aid: string, whatIf: boolean) =>
  api<{ activity_id: string; name: string; people: Person[] }>(`${base(sid, aid)}/contact?what_if=${whatIf}`);

export const previewContact = (sid: number, aid: string, contactId: number, channel: Channel, whatIf: boolean) =>
  api<Preview>(`${base(sid, aid)}/contact`, post({ contact_id: contactId, channel, what_if: whatIf, preview: true }));

/** 초안만 만든다(보내지 않음) → 기존 초안 카드 꼴(outreach_draft · outreach_call_draft). */
export const draftContact = (sid: number, aid: string, contactId: number, channel: Channel, whatIf: boolean) =>
  api<{ preview: false; card: Json }>(`${base(sid, aid)}/contact`, post({ contact_id: contactId, channel, what_if: whatIf, preview: false }));

export const errorText = (e: unknown, fallback: string) => (e instanceof ApiError && e.message ? e.message : fallback);
