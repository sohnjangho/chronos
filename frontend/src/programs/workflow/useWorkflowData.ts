// 실행 목록·고른 실행의 상세. 고른 실행이 도는 동안 2초마다 상세와 목록을 다시 읽고, 끝나거나 창을 닫으면 멈춘다.
import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '../../shared/api';
import { wfApi, type RunDetail, type RunItem } from './wfApi';

export const POLL_MS = 2000;
const message = (e: unknown) => (e instanceof ApiError ? e.message : '실행 기록을 읽을 수 없습니다.');

/** id 실행이 도는 동안(id 가 null 이 아님) 2초마다 상세와 목록을 다시 읽는다. 끝나거나 언마운트하면 멈춘다. */
function usePolling(id: number | null, loadRun: (id: number) => Promise<void>, loadRuns: () => Promise<void>) {
  useEffect(() => {
    if (id === null) return;
    const timer = setInterval(() => {
      void loadRun(id);
      void loadRuns();
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [id, loadRun, loadRuns]);
}

export function useWorkflowData(paramRun: string | undefined) {
  const [runs, setRuns] = useState<RunItem[] | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [run, setRun] = useState<RunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const current = useRef<number | null>(null);

  const loadRuns = useCallback(async () => {
    try {
      setRuns(await wfApi.runs());
    } catch (e) {
      setError(message(e));
    }
  }, []);

  /** 고른 실행만 받아 둔다(늦게 온 앞 실행의 응답은 버림). */
  const loadRun = useCallback(async (id: number) => {
    try {
      const r = await wfApi.run(id);
      if (current.current === id) {
        setRun(r);
        setError(null);
      }
    } catch (e) {
      if (current.current === id) setError(message(e));
    }
  }, []);

  useEffect(() => void loadRuns(), [loadRuns]);
  useEffect(() => {
    if (paramRun) setSelected(Number(paramRun));
  }, [paramRun]);
  useEffect(() => {
    if (selected === null && !paramRun && runs?.length) setSelected(runs[0].id);
  }, [runs, selected, paramRun]);
  useEffect(() => {
    current.current = selected;
    if (selected !== null) void loadRun(selected);
  }, [selected, loadRun]);

  usePolling(run !== null && run.id === selected && run.status === 'running' ? selected : null, loadRun, loadRuns);

  return { runs, selected, select: setSelected, run: run?.id === selected ? run : null, error };
}
