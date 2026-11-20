// 질문과 함께 보낼 화면 맥락(ui)과 그 이름. 맥락은 OS 저장소(os/uiContext)에 창이 알린 것을 읽는다.
import { useEffect, useMemo, useState } from 'react';
import { useCurrentSchedule, type CurrentSchedule } from '../../os/currentSchedule';
import { getProgram } from '../../os/registry';
import { frontVisibleWindow, useUiContext, type UiContext } from '../../os/uiContext';
import { useWindows } from '../../os/windowStore';
import { activityNamesOf, listSchedules, type ScheduleItem, type UiIn } from './chatApi';

/**
 * 보낼 ui: 맨 앞에 보이는 다른 창이 알린 맥락. 아무것도 알리지 않은 창이면 그 프로그램만.
 * schedule_id 는 알린 값, 없으면 OS 의 지금 일정.
 */
export function effectiveUi(published: UiContext | undefined, frontProgram: string | null, current: CurrentSchedule | null): UiIn {
  const program = published?.program ?? frontProgram;
  const scheduleId = published?.schedule_id ?? current?.id;
  const activity = published?.selected_activity;
  return {
    ...(program && { program }),
    ...(typeof scheduleId === 'number' && { schedule_id: scheduleId }),
    ...(activity && { selected_activity: activity }),
  };
}

/** 보내는 순간의 ui(store 가 부른다). */
export function currentUi(): UiIn {
  const front = frontVisibleWindow(useWindows.getState().wins, 'chat');
  const published = front ? useUiContext.getState().byWindow[front.id] : undefined;
  return effectiveUi(published, front?.programId ?? null, useCurrentSchedule.getState().current);
}

/** 지금 보낼 ui. 창을 끌어도(맨 앞 창이 그대로면) 다시 그리지 않도록 좁은 값만 구독한다. */
export function useEffectiveUi(): UiIn {
  const frontId = useWindows((s) => frontVisibleWindow(s.wins, 'chat')?.id ?? null);
  const frontProgram = useWindows((s) => frontVisibleWindow(s.wins, 'chat')?.programId ?? null);
  const published = useUiContext((s) => (frontId ? s.byWindow[frontId] : undefined));
  const current = useCurrentSchedule((s) => s.current);
  return useMemo(() => effectiveUi(published, frontProgram, current), [published, frontProgram, current]);
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
