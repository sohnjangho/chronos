// 지연 기록 창의 자료: 지연 목록(서버 계산) + 일정(액티비티 고르기·창 제목). 일정이 바뀌면 창이 새로 그려진다(key).
import { useEffect, useState } from 'react';
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
  useEffect(() => {
    let live = true;
    getDelays(scheduleId).then(
      (d) => live && setData(d),
      (e: unknown) => live && setLoadError(errText(e, '지연 기록을 읽을 수 없습니다.')),
    );
    getSchedule(scheduleId).then(
      (v) => live && setView(v),
      (e: unknown) => live && setViewError(errText(e, '일정을 읽을 수 없습니다.')),
    );
    return () => {
      live = false;
    };
  }, [scheduleId]);
  return { data, setData, loadError, view, viewError };
}

/** 지연 기록 창이 건 미리 보기만 지운다(조건·규칙 창이 건 것은 그대로). */
export function clearDelayPreview(scheduleId: number) {
  const s = useSchedulePreview.getState();
  if (s.previews[scheduleId]?.source === 'delays') s.clear(scheduleId);
}
