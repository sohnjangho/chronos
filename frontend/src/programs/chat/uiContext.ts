// 「보는 중」과 컨텍스트 패널이 함께 쓰는 화면 맥락: 보낼 ui, 그 이름(프로그램·액티비티), 대상 일정 정보.
import { useEffect, useMemo, useState } from 'react';
import { useCurrentSchedule } from '../../os/currentSchedule';
import { getProgram } from '../../os/registry';
import { useWindows } from '../../os/windowStore';
import { activityNamesOf, listSchedules, type ScheduleItem, type UiIn } from './chatApi';
import { effectiveUi, useChat } from './chatStore';

/** 지금 보낼 ui(알린 맥락 → 맨 앞 다른 창 → OS 지금 일정). */
export function useEffectiveUi(): UiIn {
  const ctx = useChat((s) => s.uiContext);
  const wins = useWindows((s) => s.wins);
  const current = useCurrentSchedule((s) => s.current);
  return useMemo(() => effectiveUi(ctx, wins, current), [ctx, wins, current]);
}

/** 액티비티 이름. 아직 모르거나 일정에 없으면 null. */
function useActivityName(scheduleId?: number, activityId?: string): string | null {
  const [found, setFound] = useState<{ key: string; name: string | null } | null>(null);
  const key = `${scheduleId}:${activityId}`;
  useEffect(() => {
    if (scheduleId === undefined || !activityId) return;
    let live = true;
    activityNamesOf(scheduleId).then((names) => live && setFound({ key, name: names.get(activityId) ?? null }));
    return () => {
      live = false;
    };
  }, [key, scheduleId, activityId]);
  return found?.key === key ? found.name : null;
}

/** "일정판 · A2020 지상 1~5층 골조" — 프로그램은 이름, 액티비티는 코드와 이름. 볼 것이 없으면 빈 글. */
export function useSeeing(ui: UiIn): string {
  const name = useActivityName(ui.schedule_id, ui.selected_activity);
  const program = ui.program ? (getProgram(ui.program)?.name ?? ui.program) : null;
  const activity = ui.selected_activity ? [ui.selected_activity, name].filter(Boolean).join(' ') : null;
  return [program, activity].filter(Boolean).join(' · ');
}

/** 일정 목록에서 그 일정(이름·분야·정밀도·버전). refresh 가 바뀌면 다시 읽는다(턴이 일정을 바꿨을 수 있음). */
export function useScheduleItem(scheduleId: number | undefined, refresh: unknown): ScheduleItem | null {
  const [item, setItem] = useState<ScheduleItem | null>(null);
  useEffect(() => {
    if (scheduleId === undefined) return;
    let live = true;
    listSchedules().then(
      (list) => live && setItem(list.find((s) => s.id === scheduleId) ?? null),
      () => live && setItem(null),
    );
    return () => {
      live = false;
    };
  }, [scheduleId, refresh]);
  return scheduleId === undefined || item?.id !== scheduleId ? null : item;
}
