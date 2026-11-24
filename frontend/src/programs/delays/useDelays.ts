// 지연 기록 창의 자료: 지연 목록(서버 계산) + 일정(액티비티 고르기·창 제목). 일정이 바뀌면 창이 새로 그려진다(key).
// 지연이 바뀌면(delaysToken — 에이전트 지연 도구·이 창의 고침) 목록을 다시 읽는다. reload 는 목록만 다시 읽는다.
import { useCallback, useEffect, useRef, useState } from 'react';
import { useCurrentSchedule } from '../../os/currentSchedule';
import { useSchedulePreview } from '../../os/schedulePreview';
import { ApiError } from '../../shared/api';
import { getSchedule, type ScheduleView } from '../../shared/schedule/scheduleApi';
import { getDelays, type DelaysData } from './delaysApi';

export const errText = (e: unknown, fallback: string) => (e instanceof ApiError ? e.message : fallback);

export function useDelays(scheduleId: number) {
  const [data, setData] = useState<DelaysData | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [view, setView] = useState<ScheduleView | null>(null);
  const [viewError, setViewError] = useState<string | null>(null);
  const delaysToken = useCurrentSchedule((s) => s.delaysToken);
  const [again, setAgain] = useState(0);
  const own = useRef<number | null>(null); // 이 창의 쓰기가 곧 올릴 delaysToken — 답으로 이미 새 목록을 받았으니 다시 읽지 않는다
  useEffect(() => {
    if (own.current === delaysToken) return;
    let live = true;
    getDelays(scheduleId).then(
      (d) => {
        if (!live) return;
        setData(d);
        setLoadError(null);
      },
      (e: unknown) => live && setLoadError(errText(e, '지연 기록을 읽을 수 없습니다.')),
    );
    return () => {
      live = false;
    };
  }, [scheduleId, delaysToken, again]);
  useEffect(() => {
    let live = true;
    getSchedule(scheduleId).then(
      (v) => live && setView(v),
      (e: unknown) => live && setViewError(errText(e, '일정을 읽을 수 없습니다.')),
    );
    return () => {
      live = false;
    };
  }, [scheduleId]);
  const reload = useCallback(() => setAgain((n) => n + 1), []);
  /** 이 창의 쓰기 답(새 목록)을 둔다. 뒤따르는 bumpDelays 로는 다시 읽지 않는다. */
  const setOwn = useCallback((d: DelaysData) => {
    own.current = useCurrentSchedule.getState().delaysToken + 1;
    setData(d);
  }, []);
  return { data, setData: setOwn, loadError, view, viewError, reload };
}

/** 지연 기록 창이 건 미리 보기만 지운다(조건·규칙 창이 건 것은 그대로). */
export function clearDelayPreview(scheduleId: number) {
  const s = useSchedulePreview.getState();
  if (s.previews[scheduleId]?.source === 'delays') s.clear(scheduleId);
}
