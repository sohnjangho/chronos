// 관리 포인트 창의 자료: 포인트 조회(GET …/points)와 바뀜 기록(GET …/points/history)을 함께 읽고, 일정 버전이 바뀌거나
// (에이전트 도구·승인·되돌리기 — 일정 창들과 같은 일정 저장소를 잡아 따라간다) 지연 기록이 바뀌면(delaysToken) 둘 다 다시 읽는다.
// 바깥 위험이나 근거 문장을 찾는 중이면 POLL_MS 마다 포인트 조회만 다시 읽되, 버전이 바뀌면 그만두고(둘 다 다시 읽음)
// 같은 버전에서 POLL_CAP_MS 가 지나면 멈춘다. 내가 누른 근거 문장 상태는 그 버전에서만, 서버가 그 열쇠를 줄 때만 쓴다.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useStore } from 'zustand';
import { useCurrentSchedule } from '../../os/currentSchedule';
import { holdSchedule, scheduleStore } from '../../shared/schedule/scheduleStore';
import { errorText, getHistory, getView, retryRisks, type History, type PointsView, type QuoteState } from './pointsApi';

export const POLL_MS = 3000;
export const POLL_CAP_MS = 15 * 60_000;

/** 그 일정의 지금 버전(일정 저장소를 잡고 처음 한 번 읽는다 — 에이전트 도구·reloadToken 이 다시 읽게 한다). */
function useScheduleVersion(sid: number, owner: string): number | null {
  const store = useMemo(() => scheduleStore(sid), [sid]);
  useEffect(() => {
    const release = holdSchedule(store, owner);
    if (!store.getState().view) void store.getState().load();
    const stop = useCurrentSchedule.subscribe((s, prev) => {
      if (s.reloadToken > prev.reloadToken) void store.getState().load();
    });
    return () => {
      stop();
      release();
    };
  }, [store, owner]);
  return useStore(store, (s) => s.view?.version ?? null);
}

const prefer = (server: QuoteState | null, mine: QuoteState | undefined) => (server && server.status !== 'pending' ? server : mine ?? server);

export function useBoard(sid: number, owner: string) {
  const version = useScheduleVersion(sid, owner);
  const delaysToken = useCurrentSchedule((s) => s.delaysToken);
  const [view, setView] = useState<PointsView | null>(null);
  const [hist, setHist] = useState<History | null>(null);
  const [error, setError] = useState('');
  const [again, setAgain] = useState(0); // 폴링이 새 버전을 보면 둘 다 다시 읽는다
  const [mine, setMine] = useState<{ version: number; quotes: Record<string, QuoteState> }>({ version: -1, quotes: {} });
  const [bump, setBump] = useState(0); // 처음 읽은 뒤 일정 버전이 바뀔 때마다
  const last = useRef<number | null>(null);
  useEffect(() => {
    if (version === null) return;
    if (last.current !== null && last.current !== version) setBump((n) => n + 1);
    last.current = version;
  }, [version]);
  useEffect(() => {
    let live = true;
    Promise.all([getView(sid), getHistory(sid)])
      .then(([v, h]) => {
        if (!live) return;
        setView(v);
        setHist(h);
        setError('');
      })
      .catch((e) => live && setError(errorText(e, '관리 포인트를 읽지 못했습니다.')));
    return () => {
      live = false;
    };
  }, [sid, bump, delaysToken, again]);

  const quotes = useMemo(() => {
    const server = view?.quotes ?? {};
    const out: Record<string, QuoteState | null> = { ...server };
    if (view && mine.version === view.version)
      for (const [k, q] of Object.entries(mine.quotes)) if (k in server) out[k] = prefer(server[k], q);
    return out;
  }, [view, mine]);

  const waiting = view !== null && (view.risk_status === 'looking' || Object.values(quotes).some((q) => q?.status === 'pending'));
  const since = useRef<{ version: number; at: number } | null>(null);
  useEffect(() => {
    if (!waiting || !view) {
      since.current = null;
      return;
    }
    if (since.current?.version !== view.version) since.current = { version: view.version, at: Date.now() };
    if (Date.now() - since.current.at >= POLL_CAP_MS) return; // 너무 오래 — 멈춘다(사람이 다시 열면 다시 읽는다)
    const at = view.version;
    let live = true;
    const t = setTimeout(() => {
      getView(sid)
        .then((next) => {
          if (!live) return;
          if (next.version !== at) setAgain((n) => n + 1); // 새 버전 — 폴링을 그만두고 기록까지 다시 읽는다
          else setView(next);
        })
        .catch(() => undefined);
    }, POLL_MS);
    return () => {
      live = false;
      clearTimeout(t);
    };
  }, [waiting, view, sid]);

  const onQuote = useCallback(
    (key: string, q: QuoteState) => setMine((m) => (view && m.version === view.version ? { ...m, quotes: { ...m.quotes, [key]: q } } : { version: view?.version ?? -1, quotes: { [key]: q } })),
    [view],
  );
  /** 「다시 찾기」(사람이 누를 때만): 실패한 바깥 위험 찾기를 다시 띄운다 → 조회 꼴. 오류 글은 부른 쪽이 보인다. */
  const onRetry = useCallback(async () => setView(await retryRisks(sid)), [sid]);
  return { view, hist, error, quotes, onQuote, onRetry };
}
