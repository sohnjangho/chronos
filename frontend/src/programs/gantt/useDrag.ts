// Plan 막대 끌기(R8). 오른쪽 끝 → OD, 막대 → 시작 하한(SNET, 새 시작 자리의 날).
// 화면은 날짜를 저장하지 않는다 — OD 수나 SNET 날만 일정 저장소의 쓰기 줄로 보내고, 날짜는 서버가 다시 계산한다.
// OD 는 끈 구간의 날마다 서버 근무 달력(주 근무일 수·그 액티비티 태그의 작업 금지 기간)으로 쉬는 날을 빼고 센 어림이다
// (공휴일은 서버가 주지 않아 모른다 — 놓은 뒤 서버가 계산한 막대가 진짜).
import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';
import { addDays, barRect, type Scale } from '../../shared/gantt/scale';
import { dot } from '../../shared/schedule/format';
import type { Activity, ScheduleView } from '../../shared/schedule/scheduleApi';
import type { ScheduleState } from '../../shared/schedule/scheduleStore';
import { useScheduleStore, useWindowId } from '../../shared/schedule/scope';
import { planOf } from './model';

export type DragMode = 'move' | 'od' | 'click';
export type Calendar = ScheduleView['calendar'];

export interface DragState {
  aid: string;
  rowKey: string;
  mode: 'move' | 'od';
  dx: number;
}

/** 이 막대를 끌어 고칠 수 있는가. 시작·끝난 액티비티는 표에서 RD·Actual 을 고친다. FNLT 는 SNET 으로 바꾸지 않는다. Plan 막대가 없으면 못 끈다. */
export function dragRules(a: Activity, editable: boolean) {
  const open = editable && !a.actual_start && !a.actual_finish && planOf(a) !== null;
  return {
    move: open && a.constraint?.type !== 'FNLT',
    resize: open && a.kind === 'task' && a.od > 0 && a.rd === null,
  };
}

/** 그날이 이 액티비티의 근무일인가: 주 근무일 수(5 = 토·일 쉼, 6 = 일 쉼, 7 = 없음)와 그 태그의 작업 금지 기간(서버 값). */
function workday(iso: string, a: Activity, cal: Calendar): boolean {
  const dow = new Date(`${iso}T00:00:00Z`).getUTCDay();
  const perWeek = cal?.days_per_week ?? 5;
  if ((perWeek <= 5 && (dow === 0 || dow === 6)) || (perWeek === 6 && dow === 0)) return false;
  return !(cal?.blocked ?? []).some((b) => a.tags.includes(b.tag) && b.start <= iso && iso <= b.finish);
}

const daysOf = (dx: number, scale: Scale) => Math.round(dx / scale.pxPerDay);

/** 끈 거리 → 새 OD: 늘리면 Plan 끝 다음 날부터, 줄이면 Plan 끝 날부터 거꾸로, 끈 날 가운데 근무일만 더하고 뺀다(최소 1). */
export function draggedOd(a: Activity, dx: number, scale: Scale, cal: Calendar): number {
  const finish = planOf(a)!.finish;
  const days = daysOf(dx, scale);
  let n = 0;
  for (let i = 1; i <= Math.abs(days); i += 1) if (workday(addDays(finish, days > 0 ? i : 1 - i), a, cal)) n += 1;
  return Math.max(1, a.od + Math.sign(days) * n);
}

/** 끄는 중 OD 점선 막대의 자리(Plan 시작 ~ 끈 날 끝). */
export function draggedOdRect(a: Activity, dx: number, scale: Scale): { x: number; w: number } {
  const p = planOf(a)!;
  const r = barRect(scale, p.start, addDays(p.finish, daysOf(dx, scale)));
  return { x: r.x, w: Math.max(r.w, scale.pxPerDay) };
}

/** 끈 거리 → 새 시작 자리의 날(하루 단위로 맞춤). */
export const draggedStart = (a: Activity, dx: number, scale: Scale) => addDays(planOf(a)!.start, daysOf(dx, scale));

/** 끌기 중 막대 옆에 보일 글. */
export function dragLabel(a: Activity, d: DragState, scale: Scale, cal: Calendar): string {
  return d.mode === 'od' ? `OD ${a.od} → ${draggedOd(a, d.dx, scale, cal)}` : `SNET ${dot(draggedStart(a, d.dx, scale))}`;
}

const EARLIER = 'SNET 제약은 시작을 늦추기만 합니다. 더 이르게 하려면 선행 관계나 다른 제약을 고치세요.';

interface DropCtx {
  store: ScheduleState;
  windowId: string;
  scale: Scale;
  cal: Calendar;
}

/** 놓았을 때: 보낼 것이 있으면 일정 저장소의 쓰기 줄로 보낸다(그 줄이 base_version·409·422 를 맡는다). 안내는 이 창에만. */
function drop({ store, windowId, scale, cal }: DropCtx, a: Activity, mode: DragMode, dx: number): Promise<unknown> | null {
  store.select(a.id, windowId);
  if (mode === 'click' || Math.abs(dx) < 3) return null;
  if (mode === 'od') {
    const od = draggedOd(a, dx, scale, cal);
    return od === a.od ? null : store.patchActivity(a.id, { od });
  }
  const date = draggedStart(a, dx, scale);
  const snet = a.constraint?.type === 'SNET' ? a.constraint.date : null;
  if (date === snet || date === planOf(a)!.start) return null; // 시작 날이 그대로면 보내지도 알리지도 않는다
  if (!snet && date < planOf(a)!.start) {
    store.setNotice({ tone: 'info', text: EARLIER, windowId });
    return null;
  }
  return store.patchActivity(a.id, { constraint: { type: 'SNET', date } });
}

/**
 * 누른 막대를 창 전체의 pointermove·pointerup 으로 따라간다. 보내는 동안에는 점선 자리를 남긴다.
 * pointercancel·Esc 면 아무것도 보내지 않고 멈추고, 창이 닫히면(언마운트) 창 전체 듣기를 지운다.
 */
export function useDrag(scale: Scale, cal: Calendar) {
  const store = useScheduleStore();
  const windowId = useWindowId();
  const [drag, setDrag] = useState<DragState | null>(null);
  const token = useRef(0);
  const stopRef = useRef<(() => void) | null>(null);
  useEffect(() => () => stopRef.current?.(), []);
  const begin = (e: ReactPointerEvent, a: Activity, rowKey: string, mode: DragMode) => {
    if (e.button !== 0) return;
    e.stopPropagation();
    e.preventDefault(); // 끄는 동안 글이 선택되지 않게
    stopRef.current?.();
    const x0 = e.clientX;
    const mine = ++token.current;
    const move = (ev: PointerEvent) => {
      const dx = ev.clientX - x0;
      if (mode !== 'click') setDrag(Math.abs(dx) >= 3 ? { aid: a.id, rowKey, mode, dx } : null);
    };
    const stop = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      window.removeEventListener('pointercancel', cancel);
      window.removeEventListener('keydown', key);
      stopRef.current = null;
    };
    const cancel = () => {
      stop();
      setDrag(null);
    };
    const key = (ev: KeyboardEvent) => ev.key === 'Escape' && cancel();
    function up(ev: PointerEvent) {
      stop();
      const sent = drop({ store: store.getState(), windowId, scale, cal }, a, mode, ev.clientX - x0);
      if (!sent) setDrag(null);
      else void sent.finally(() => token.current === mine && setDrag(null));
    }
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
    window.addEventListener('pointercancel', cancel);
    window.addEventListener('keydown', key);
    stopRef.current = stop;
  };
  return { drag, begin };
}
