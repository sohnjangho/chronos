// 여러 명에게 한 번에(Task 103) — 창의 보내기·결과 확인과, 결과를 모르는 요청의 저장(BatchSendDialog 가 쓴다).
// 보내기는 POST …/outreach/batches(요청 하나 잠금). 결과 확인은 GET …/batches/by-key — **확인은 보내지 않는다**.
// 결과를 모르는 요청은 이 탭의 sessionStorage 에 일정마다 {request, user_id, saved_at} 로 두고(번호 없음 — 연락처 id·글·요청 번호),
// 같은 사람·30분 안의 것만 쓴다(아니면 지운다).
import { useRef, useState } from 'react';
import { useSession } from '../../os/session';
import { api, ApiError } from '../api';
import { SEND_UNKNOWN, type Label } from './labels';
import { sendOutcomeUnknown, type Outcome } from './outreachApi';

export interface Result { contact_id: number; name: string; outcome: Outcome }
export interface Sent { batch_id: number; replayed: boolean; in_progress?: boolean; results: Result[] }
export type BatchRequest = { request_key: string; contact_ids: number[] } & Record<string, unknown>;

const ASK_AGAIN = '보냈는지 확인하지 못했습니다 — [결과 다시 받기]는 같은 요청 번호로 다시 묻습니다(이미 받은 요청이면 다시 보내지 않고 결과만 받습니다).';
export const NOT_REACHED = '이 묶음은 서버에 닿지 않았습니다 — 보내지 않았습니다';
const PENDING_MAX_MS = 30 * 60_000; // 저장한 요청을 쓰는 시간
const pendingKey = (sid: number) => `chronos.batchPending.${sid}`;
const me = () => useSession.getState().session?.user.id ?? null;

/** 결과를 모르는 요청(이 일정·이 사람·30분 안). 아니거나 꼴이 틀리면 지우고 null. */
function readPending(sid: number): BatchRequest | null {
  try {
    const v = JSON.parse(sessionStorage.getItem(pendingKey(sid)) ?? 'null') as { request?: BatchRequest; user_id?: unknown; saved_at?: unknown } | null;
    const req = v?.request;
    const fresh = typeof v?.saved_at === 'number' && Date.now() - v.saved_at <= PENDING_MAX_MS;
    if (req && typeof req.request_key === 'string' && Array.isArray(req.contact_ids) && v?.user_id === me() && me() !== null && fresh) return req;
    sessionStorage.removeItem(pendingKey(sid));
  } catch {
    /* 저장소를 쓸 수 없음 */
  }
  return null;
}
function writePending(sid: number, req: BatchRequest | null) {
  try {
    if (req) sessionStorage.setItem(pendingKey(sid), JSON.stringify({ request: req, user_id: me(), saved_at: Date.now() }));
    else sessionStorage.removeItem(pendingKey(sid));
  } catch {
    /* 저장소를 쓸 수 없으면 창 안에서만 기억한다 */
  }
}

/** 보내기 하나(요청 하나 잠금). 답을 모르면 같은 요청을 남겨 두고, 결과를 받거나 서버가 거절하면 지운다. */
export function useSender(scheduleId: number) {
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState<Sent | null>(null);
  const [note, setNote] = useState<Label | null>(null);
  const [asked, setAsked] = useState(false);
  const [last, setLast] = useState<BatchRequest | null>(null);
  const [pending, setPending] = useState(() => readPending(scheduleId));
  const [missing, setMissing] = useState<BatchRequest | null>(null); // 찾아보니 서버에 닿지 않은 요청
  const lock = useRef(false);
  const got = (s: Sent) => {
    setSent(s);
    setAsked(false);
    setNote(null);
    setPending(null);
    if (!s.in_progress) writePending(scheduleId, null);
  };
  const run = async (work: () => Promise<void>) => {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    try {
      await work();
    } finally {
      lock.current = false;
      setBusy(false);
    }
  };
  /** 보내기(새 묶음이거나, 방금 답을 못 받은 같은 요청 다시). */
  const submit = (req: BatchRequest) => run(async () => {
    setLast(req);
    setMissing(null);
    setPending((p) => (p && p.request_key === req.request_key ? p : null)); // 새 묶음을 보내면 앞의 것은 저장소에서도 바뀐다
    writePending(scheduleId, req);
    try {
      got(await api<Sent>(`/api/schedules/${scheduleId}/outreach/batches`, send(req)));
    } catch (e) {
      const unknown = sendOutcomeUnknown(e);
      setAsked(unknown);
      if (!unknown) writePending(scheduleId, null);
      setNote(unknown ? { text: ASK_AGAIN, tone: 'warn' } : { text: e instanceof ApiError ? e.message : SEND_UNKNOWN, tone: 'bad' });
    }
  });
  /** 결과 확인만 — 그 요청 번호로 저장된 묶음을 찾는다. 보내지 않는다. */
  const check = (req: BatchRequest) => run(async () => {
    setLast(req);
    try {
      got(await api<Sent>(`/api/schedules/${scheduleId}/outreach/batches/by-key?request_key=${encodeURIComponent(req.request_key)}`, { cache: 'no-store' }));
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        writePending(scheduleId, null);
        setPending(null);
        setMissing(req);
        setNote({ text: NOT_REACHED, tone: 'warn' });
      } else setNote({ text: e instanceof ApiError && e.status !== 0 ? e.message : '결과를 확인하지 못했습니다 — 잠시 뒤 다시 눌러 주세요.', tone: 'warn' });
    }
  });
  const forget = () => {
    setMissing(null);
    setNote(null);
  };
  return { busy, sent, note, asked, last, pending, missing, submit, check, forget, unresolved: asked || sent?.in_progress === true };
}

export const newKey = (): string =>
  globalThis.crypto?.randomUUID?.() ?? `k${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`;
const send = (body: unknown) => ({ method: 'POST', body: JSON.stringify(body) });

