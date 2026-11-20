// 최근 요청 목록과 고른 요청의 상세. 고른 요청이 실행 중이면 1초마다 상세를 다시 읽고, 끝나거나 창을 닫으면 멈춘다.
// 읽기가 거절되면(4xx: 권한·없음) 멈추고 그 안내를 보인다. 그 밖의 실패(연결·서버)는 1초 → 2초 → 5초(그 뒤 5초)로 늦춰 다시 읽는다.
import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '../../shared/api';
import { devApi, type Turn, type TurnDetail } from './devApi';

export const POLL_MS = 1000;
/** 연속 실패 n번째 뒤 기다리는 시간. */
const RETRY_MS = [1000, 2000, 5000];
const message = (e: unknown) => (e instanceof ApiError ? e.message : '실행 추적을 읽을 수 없습니다.');
const refusedError = (e: unknown) => e instanceof ApiError && e.status >= 400 && e.status < 500;

/** 상세 읽기 결과: 아직 실행 중 · 끝남 · 거절(4xx) · 실패(연결·서버). */
type Read = 'running' | 'over' | 'refused' | 'failed';

/**
 * 앞 읽기가 끝난 뒤 기다렸다 다음을 읽는다(겹치지 않음). 끝났거나 거절되면 그 자리에서 멈추고(렌더를 기다리지 않음),
 * 실패면 RETRY_MS 로 늦춘다. id 가 null 이 되거나 언마운트해도 멈춘다.
 */
function usePolling(id: number | null, load: (id: number) => Promise<Read>) {
  useEffect(() => {
    if (id === null) return;
    let stopped = false;
    let failures = 0;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      const read = await load(id);
      if (stopped || read === 'over' || read === 'refused') return;
      failures = read === 'failed' ? failures + 1 : 0;
      const wait = failures ? RETRY_MS[Math.min(failures, RETRY_MS.length) - 1] : POLL_MS;
      timer = setTimeout(() => void tick(), wait);
    };
    timer = setTimeout(() => void tick(), POLL_MS);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [id, load]);
}

export function useTurnData() {
  const [turns, setTurns] = useState<Turn[] | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [detail, setDetail] = useState<TurnDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  /** 거절되어 다시 읽기를 멈췄는가. */
  const [halted, setHalted] = useState(false);
  /** 마지막으로 상세를 읽은 때(이 화면 시계). */
  const [checkedAt, setCheckedAt] = useState<number | null>(null);
  const current = useRef<number | null>(null);

  const loadTurns = useCallback(async () => {
    try {
      setTurns(await devApi.turns());
    } catch (e) {
      setError(message(e));
    }
  }, []);

  /** 고른 요청의 응답만 받아 둔다(늦게 온 앞 요청의 응답은 버림). */
  const loadDetail = useCallback(async (id: number): Promise<Read> => {
    try {
      const d = await devApi.turn(id);
      if (current.current === id) {
        setDetail(d);
        setError(null);
        setHalted(false);
        setCheckedAt(Date.now());
      }
      return d.turn.status === 'running' ? 'running' : 'over';
    } catch (e) {
      const refused = refusedError(e);
      if (current.current === id) {
        setError(message(e));
        if (refused) setHalted(true);
      }
      return refused ? 'refused' : 'failed';
    }
  }, []);

  useEffect(() => void loadTurns(), [loadTurns]);
  useEffect(() => {
    if (selected === null && turns?.length) setSelected(turns[0].turn_id);
  }, [turns, selected]);
  useEffect(() => {
    current.current = selected;
    if (selected !== null) void loadDetail(selected);
  }, [selected, loadDetail]);

  /** 같은 요청을 다시 고르면 다시 읽는다(멈춘 폴링도 성공하면 다시 돈다). */
  const select = useCallback(
    (id: number) => {
      if (id === current.current) void loadDetail(id);
      else setSelected(id);
    },
    [loadDetail],
  );

  const shown = detail?.turn.turn_id === selected ? detail : null;
  usePolling(shown?.turn.status === 'running' && !halted ? selected : null, loadDetail);

  return { turns, detail: shown, select, reloadTurns: loadTurns, error, halted, checkedAt };
}
