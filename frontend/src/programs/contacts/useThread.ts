// 한 사람과의 대화를 읽고 15초마다 다시 읽는다. 열린 대화 칸 하나에 타이머 하나 — 칸이 사라지면(다른 사람·다른 프로젝트·창 닫기)
// 멈추고, 브라우저 탭이 가려지면 멈췄다가 다시 보이면 곧바로 읽고, 최소화한 창(hidden)에서는 그 차례를 건너뛴다.
// 다시 읽기에 실패해도 보이던 대화는 그대로 두고(stale) 처음 읽기에 실패했을 때만 오류를 보인다.
// 받은 글이 읽지 않은 채 있으면 읽음으로 바꾸고(주소록 API) 주소록을 다시 읽게 한다.
import { useCallback, useEffect, useRef, useState, type RefObject } from 'react';
import { outreachApi, type ContactBrief, type Message } from '../../shared/outreach/outreachApi';
import { mergeNewest, prependOlder } from './thread';

export const POLL_MS = 15_000;

export interface ThreadState {
  /** 오래된 것부터. null = 아직 읽지 못함 */
  messages: Message[] | null;
  contact: ContactBrief | null;
  hasMore: boolean;
  /** 처음 읽기 실패의 까닭 */
  error: string | null;
  /** 다시 읽기에 실패함(보이는 것은 마지막으로 읽은 대화) */
  stale: boolean;
  loadingOlder: boolean;
  olderError: string | null;
}

export interface ThreadHandle extends ThreadState {
  /** 가장 새 쪽을 다시 읽는다(실패해도 던지지 않는다). */
  reload: () => Promise<void>;
  /** before(지금 보이는 첫 줄의 id)보다 앞의 것을 더 읽는다. */
  loadOlder: (before: number) => Promise<void>;
  /** 동작(보내기·취소·고치기)의 응답이 준 줄로 같은 id 의 줄을 바꾼다 — 다시 읽기가 닿지 않는 앞쪽 줄도 서버의 답대로 보이게. */
  apply: (row: Message) => void;
  /** 지운 줄(204)을 뺀다. */
  drop: (id: number) => void;
}

const EMPTY: ThreadState = { messages: null, contact: null, hasMore: false, error: null, stale: false, loadingOlder: false, olderError: null };
const text = (e: unknown, fallback: string) => (e instanceof Error && e.message ? e.message : fallback);

export function useThread(scheduleId: number, contactId: number, root: RefObject<HTMLElement | null>, onChanged: () => void): ThreadHandle {
  const [state, setState] = useState<ThreadState>(EMPTY);
  const alive = useRef(true);
  const seq = useRef(0);
  const changed = useRef(onChanged);
  useEffect(() => {
    changed.current = onChanged;
  }, [onChanged]);

  const reload = useCallback(async () => {
    const mine = ++seq.current;
    const current = () => alive.current && mine === seq.current; // 사라진 칸·더 늦게 떠난 읽기가 있으면 이 답은 버린다
    try {
      const res = await outreachApi.thread(scheduleId, contactId);
      if (!current()) return;
      setState((prev) => {
        const had = prev.messages ?? [];
        const keepsOlder = res.messages.length > 0 && had.some((m) => m.id < res.messages[0].id);
        return { ...prev, messages: mergeNewest(had, res.messages), contact: res.contact, hasMore: keepsOlder ? prev.hasMore : res.has_more, error: null, stale: false };
      });
      if (res.contact.unread > 0) {
        // 읽음 처리에 실패해도 대화는 읽은 것이다 — 다음 읽기에서 다시 해 본다.
        await outreachApi.markRead(scheduleId, contactId).then(() => alive.current && changed.current(), () => undefined);
      }
    } catch (e) {
      if (!current()) return;
      setState((prev) => (prev.messages === null ? { ...prev, error: text(e, '대화를 읽을 수 없습니다.') } : { ...prev, stale: true }));
    }
  }, [scheduleId, contactId]);

  const loadOlder = useCallback(
    async (before: number) => {
      setState((prev) => ({ ...prev, loadingOlder: true, olderError: null }));
      try {
        const res = await outreachApi.thread(scheduleId, contactId, { before });
        if (!alive.current) return;
        setState((prev) => ({ ...prev, messages: prependOlder(prev.messages ?? [], res.messages), hasMore: res.has_more, loadingOlder: false }));
      } catch (e) {
        if (alive.current) setState((prev) => ({ ...prev, loadingOlder: false, olderError: text(e, '이전 대화를 읽을 수 없습니다.') }));
      }
    },
    [scheduleId, contactId],
  );

  // 다시 읽기는 새 쪽 50개만 덮는다(mergeNewest) — 「이전 대화 더 보기」로 읽은 줄은 동작의 응답으로만 바뀐다.
  const apply = useCallback((row: Message) => {
    if (alive.current) setState((prev) => (prev.messages ? { ...prev, messages: prev.messages.map((m) => (m.id === row.id ? row : m)) } : prev));
  }, []);
  const drop = useCallback((id: number) => {
    if (alive.current) setState((prev) => (prev.messages ? { ...prev, messages: prev.messages.filter((m) => m.id !== id) } : prev));
  }, []);

  useEffect(() => {
    alive.current = true;
    let timer: ReturnType<typeof setInterval> | null = null;
    const tick = () => {
      if (!root.current?.closest('[hidden]')) void reload();
    };
    const start = () => {
      if (timer === null) timer = setInterval(tick, POLL_MS);
    };
    const stop = () => {
      if (timer !== null) clearInterval(timer);
      timer = null;
    };
    const onVisibility = () => {
      if (document.visibilityState === 'hidden') return stop();
      void reload();
      start();
    };
    void reload();
    if (document.visibilityState !== 'hidden') start();
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      alive.current = false;
      stop();
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [reload, root]);

  return { ...state, reload, loadOlder, apply, drop };
}
