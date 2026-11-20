// 최근 요청 목록과 고른 요청의 상세. 고른 요청이 실행 중이면 1초마다 상세를 다시 읽고, 끝나거나 창을 닫으면 멈춘다.
import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '../../shared/api';
import { devApi, type Turn, type TurnDetail } from './devApi';

export const POLL_MS = 1000;
const message = (e: unknown) => (e instanceof ApiError ? e.message : '실행 추적을 읽을 수 없습니다.');

/**
 * 앞 읽기가 끝난 뒤 1초를 기다려 다음을 읽는다(겹치지 않음). 읽은 요청이 끝났으면(load 가 false) 그 자리에서 멈추고,
 * id 가 null 이 되거나 언마운트해도 멈춘다.
 */
function usePolling(id: number | null, load: (id: number) => Promise<boolean>) {
  useEffect(() => {
    if (id === null) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      const again = await load(id);
      if (again && !stopped) timer = setTimeout(() => void tick(), POLL_MS);
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
  const current = useRef<number | null>(null);

  const loadTurns = useCallback(async () => {
    try {
      setTurns(await devApi.turns());
    } catch (e) {
      setError(message(e));
    }
  }, []);

  /** 고른 요청의 응답만 받아 둔다(늦게 온 앞 요청의 응답은 버림). 아직 실행 중이면(또는 읽지 못했으면) true. */
  const loadDetail = useCallback(async (id: number) => {
    try {
      const d = await devApi.turn(id);
      if (current.current === id) {
        setDetail(d);
        setError(null);
      }
      return d.turn.status === 'running';
    } catch (e) {
      if (current.current === id) setError(message(e));
      return true;
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

  const shown = detail?.turn.turn_id === selected ? detail : null;
  usePolling(shown?.turn.status === 'running' ? selected : null, loadDetail);

  return { turns, detail: shown, select: setSelected, reloadTurns: loadTurns, error };
}
