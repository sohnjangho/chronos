// Plan 막대 끌기(R8). 오른쪽 끝 → OD(그 막대의 근무일/날 비율로 정수 근무일), 막대 → 시작 하한(SNET, 새 시작 자리의 날).
// 화면은 날짜를 계산해 저장하지 않는다 — OD 수나 SNET 날만 일정 저장소의 쓰기 줄로 보내고, 날짜는 서버가 다시 계산한다.
import { useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';
import { addDays, barRect, type Scale } from '../../shared/gantt/scale';
import { dot } from '../../shared/schedule/format';
import type { Activity } from '../../shared/schedule/scheduleApi';
import type { ScheduleState } from '../../shared/schedule/scheduleStore';
import { useScheduleStore, useWindowId } from '../../shared/schedule/scope';
import { planOf } from './model';

export type DragMode = 'move' | 'od' | 'click';

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

/** 끈 거리 → 새 OD. 이 막대의 폭이 OD 근무일이므로 같은 비율로 정수 근무일(최소 1). */
export function draggedOd(a: Activity, dx: number, scale: Scale): number {
  const p = planOf(a)!;
  const w = barRect(scale, p.start, p.finish).w;
  return Math.max(1, Math.round(a.od + (dx * a.od) / w));
}

/** 끈 거리 → 새 시작 자리의 날(하루 단위로 맞춤). */
export const draggedStart = (a: Activity, dx: number, scale: Scale) => addDays(planOf(a)!.start, Math.round(dx / scale.pxPerDay));

/** 끌기 중 막대 옆에 보일 글. */
export function dragLabel(a: Activity, d: DragState, scale: Scale): string {
  return d.mode === 'od' ? `OD ${a.od} → ${draggedOd(a, d.dx, scale)}` : `SNET ${dot(draggedStart(a, d.dx, scale))}`;
}

const EARLIER = 'SNET 제약은 시작을 늦추기만 합니다. 더 이르게 하려면 선행 관계나 다른 제약을 고치세요.';

/** 놓았을 때: 보낼 것이 있으면 일정 저장소의 쓰기 줄로 보낸다(그 줄이 base_version·409·422 를 맡는다). */
function drop(store: ScheduleState, by: string, a: Activity, mode: DragMode, dx: number, scale: Scale): Promise<unknown> | null {
  store.select(a.id, by);
  if (mode === 'click' || Math.abs(dx) < 3) return null;
  if (mode === 'od') {
    const od = draggedOd(a, dx, scale);
    return od === a.od ? null : store.patchActivity(a.id, { od });
  }
  const date = draggedStart(a, dx, scale);
  const snet = a.constraint?.type === 'SNET' ? a.constraint.date : null;
  if (date === snet) return null;
  if (!snet && date <= planOf(a)!.start) {
    store.setNotice({ tone: 'info', text: EARLIER });
    return null;
  }
  return store.patchActivity(a.id, { constraint: { type: 'SNET', date } });
}

/** 누른 막대를 창 전체의 pointermove·pointerup 으로 따라간다. 보내는 동안에는 점선 자리를 남긴다. */
export function useDrag(scale: Scale) {
  const store = useScheduleStore();
  const windowId = useWindowId();
  const [drag, setDrag] = useState<DragState | null>(null);
  const token = useRef(0);
  const begin = (e: ReactPointerEvent, a: Activity, rowKey: string, mode: DragMode) => {
    if (e.button !== 0) return;
    e.stopPropagation();
    e.preventDefault(); // 끄는 동안 글이 선택되지 않게
    const x0 = e.clientX;
    const mine = ++token.current;
    const move = (ev: PointerEvent) => {
      const dx = ev.clientX - x0;
      if (mode !== 'click') setDrag(Math.abs(dx) >= 3 ? { aid: a.id, rowKey, mode, dx } : null);
    };
    const up = (ev: PointerEvent) => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      const sent = drop(store.getState(), windowId, a, mode, ev.clientX - x0, scale);
      if (!sent) setDrag(null);
      else void sent.finally(() => token.current === mine && setDrag(null));
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };
  return { drag, begin };
}
