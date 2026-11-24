// 관리 포인트 창의 자료: 포인트 조회(GET …/points — 열린 지연이 있으면 그 가정, 사람이 고르면 저장한 버전)와 바뀜 기록을 함께 읽고, 일정 버전이 바뀌거나
// (에이전트 도구·승인·되돌리기 — 일정 창들과 같은 일정 저장소를 잡아 따라간다) 지연 기록이 바뀌면(delaysToken) 둘 다 다시 읽는다.
// 바깥 위험이나 근거 문장을 찾는 중이면 POLL_MS 마다 포인트 조회만 다시 읽되, 버전이 바뀌면 그만두고(둘 다 다시 읽음)
// POLL_CAP_MS 가 지나면 멈추고 「오래 걸려 … 다시 불러오기」를 보인다(상한은 둘 다 다시 읽을 때마다 — 새 버전·새 지연·다시 불러오기 —
// 새로 잰다). 다시 읽기가 실패하면 한 번 더 해 보고, 또 실패하면 같은 줄로 알린다. 내가 누른 근거 문장 상태는 그 버전에서만,
// 서버가 그 열쇠를 줄 때만 쓴다.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useStore } from 'zustand';
import { useCurrentSchedule } from '../../os/currentSchedule';
import { holdSchedule, scheduleStore } from '../../shared/schedule/scheduleStore';
import { ApiError } from '../../shared/api';
import { errorText, getHistory, getView, retryRisks, type History, type PointsView, type QuoteState } from './pointsApi';

export const POLL_MS = 3000;
export const POLL_CAP_MS = 15 * 60_000;
export const STALE_CAP = '오래 걸려 다시 읽기를 멈췄습니다';
export const STALE_READ = '다시 읽지 못했습니다';

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

const keyOf = (v: PointsView) => `${v.version}/${v.what_if === true}`;

/** 바뀜 기록을 먼저 읽고, 열린 지연의 가정 줄이 있으면(주의할 일정과 같은 규칙 — 서버가 preview 로 준다) 가정 포인트를, 아니면
 * 저장한 버전 포인트를 읽는다. 가정 조회가 404(그새 사라짐)면 저장한 버전으로. */
async function readBoth(sid: number, savedOnly: boolean): Promise<[PointsView, History]> {
  const h = await getHistory(sid);
  if (savedOnly || h.preview === null) return [await getView(sid), h];
  try {
    return [await getView(sid, true), h];
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return [await getView(sid), h];
    throw e;
  }
}

const prefer = (server: QuoteState | null, mine: QuoteState | undefined) => (server && server.status !== 'pending' ? server : mine ?? server);

export function useBoard(sid: number, owner: string) {
  const version = useScheduleVersion(sid, owner);
  const delaysToken = useCurrentSchedule((s) => s.delaysToken);
  const [view, setView] = useState<PointsView | null>(null);
  const hasView = useRef(false);
  hasView.current = view !== null;
  const retryTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const [hist, setHist] = useState<History | null>(null);
  const [error, setError] = useState('');
  const [again, setAgain] = useState(0); // 폴링이 새 버전을 보면 둘 다 다시 읽는다
  const [mine, setMine] = useState<{ key: string; quotes: Record<string, QuoteState> }>({ key: '', quotes: {} });
  const [savedOnly, setSavedOnly] = useState(false); // 사람이 「저장된 버전 보기」를 골랐다
  const [bump, setBump] = useState(0); // 처음 읽은 뒤 일정 버전이 바뀔 때마다
  const last = useRef<number | null>(null);
  const since = useRef<number | null>(null); // 폴링을 시작한 때(둘 다 다시 읽으면 비운다)
  const retried = useRef(false);
  const [stalled, setStalled] = useState<string | null>(null);
  const [tick, setTick] = useState(0); // 폴링 한 번이 실패하면 다음 차례를 다시 잡는다
  useEffect(() => {
    if (version === null) return;
    if (last.current !== null && last.current !== version) setBump((n) => n + 1);
    last.current = version;
  }, [version]);
  useEffect(() => {
    let live = true;
    readBoth(sid, savedOnly)
      .then(([v, h]) => {
        if (!live) return;
        since.current = null; // 새로 읽었다 — 폴링 상한을 새로 잰다
        retried.current = false;
        setStalled(null);
        setView(v);
        setHist(h);
        setError('');
      })
      .catch((e) => {
        if (!live) return;
        if (!hasView.current) return setError(errorText(e, '관리 포인트를 읽지 못했습니다.'));
        if (retried.current) return setStalled(STALE_READ);
        retried.current = true;
        retryTimer.current = setTimeout(() => setAgain((n) => n + 1), POLL_MS); // 다음 차례에 한 번 더
      });
    return () => {
      live = false;
    };
  }, [sid, bump, delaysToken, again, savedOnly]);
  useEffect(() => () => clearTimeout(retryTimer.current), []);

  const quotes = useMemo(() => {
    const server = view?.quotes ?? {};
    const out: Record<string, QuoteState | null> = { ...server };
    if (view && mine.key === keyOf(view))
      for (const [k, q] of Object.entries(mine.quotes)) if (k in server) out[k] = prefer(server[k], q);
    return out;
  }, [view, mine]);

  const waiting = view !== null && (view.risk_status === 'looking' || Object.values(quotes).some((q) => q?.status === 'pending'));
  useEffect(() => {
    if (!waiting || !view) {
      since.current = null;
      return;
    }
    since.current ??= Date.now();
    if (Date.now() - since.current >= POLL_CAP_MS) return setStalled(STALE_CAP); // 너무 오래 — 멈추고 다시 불러오기를 보인다
    const at = view.version;
    const whatIf = view.what_if === true;
    let live = true;
    const t = setTimeout(() => {
      getView(sid, whatIf)
        .then((next) => {
          if (!live) return;
          if (next.version !== at) setAgain((n) => n + 1); // 새 버전 — 폴링을 그만두고 기록까지 다시 읽는다
          else setView(next);
        })
        .catch(() => live && setTick((n) => n + 1)); // 이번 차례만 실패 — 다음 차례를 다시 잡는다(상한 안에서)
    }, POLL_MS);
    return () => {
      live = false;
      clearTimeout(t);
    };
  }, [waiting, view, sid, tick]);

  const onQuote = useCallback(
    (key: string, q: QuoteState) => setMine((m) => (view && m.key === keyOf(view) ? { ...m, quotes: { ...m.quotes, [key]: q } } : { key: view ? keyOf(view) : '', quotes: { [key]: q } })),
    [view],
  );
  /** 「다시 찾기」(사람이 누를 때만): 실패한 바깥 위험 찾기를 다시 띄운다 → 조회 꼴. 오류 글은 부른 쪽이 보인다. */
  const whatIf = view?.what_if === true;
  const onRetry = useCallback(async () => setView(await retryRisks(sid, whatIf)), [sid, whatIf]);
  /** 「다시 불러오기」: 둘 다 다시 읽고 폴링 상한을 새로 잰다(바깥 찾기를 새로 하지 않는다). */
  const reload = useCallback(() => setAgain((n) => n + 1), []);
  /** 가정(열린 지연 반영)과 저장한 버전 사이를 오간다. 가정 줄이 없으면 늘 저장한 버전. */
  const showSaved = useCallback((on: boolean) => setSavedOnly(on), []);
  return { view, hist, error, quotes, onQuote, onRetry, stalled, reload, whatIf, savedOnly, showSaved };
}
