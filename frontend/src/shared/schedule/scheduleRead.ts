// 일정 저장소의 읽기 쪽: 서버에서 읽어 바꾸기(바뀌지 않은 액티비티 객체는 그대로)와 쓰기 줄의 차례 값.
import type { StoreApi } from 'zustand';
import { ApiError } from '../api';
import * as sapi from './scheduleApi';
import type { ScheduleView } from './scheduleApi';
import type { ScheduleState } from './scheduleStore';

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
export const errorText = (e: unknown) => (e instanceof ApiError ? e.message : '요청을 처리하지 못했습니다.');

/** 바뀌지 않은 액티비티는 앞의 객체를 그대로 쓴다(그 행은 다시 그리지 않는다). */
function share(prev: ScheduleView | null, next: ScheduleView): ScheduleView {
  if (!prev || prev.id !== next.id) return next;
  const old = new Map(prev.activities.map((a) => [a.id, a]));
  const activities = next.activities.map((a) => {
    const o = old.get(a.id);
    return o && same(o, a) ? o : a;
  });
  return { ...next, activities };
}

export type SetState = StoreApi<ScheduleState>['setState'];
export type GetState = () => ScheduleState;

/** 쓰기 줄과 읽기 차례. epoch 가 바뀌면(reset) 줄 서 있던 쓰기는 보내지 않고, 늦게 온 답은 버린다. */
export interface Queue {
  chain: Promise<unknown>;
  epoch: number;
  loadSeq: number;
  tickets: number;
  /** 409 가 나면 그때까지 줄 선 쓰기(표 번호 ≤ cutoff)도 보내지 않는다 — 다시 불러온 일정 위에 옛 고침을 얹지 않게. */
  cutoff: number;
  loading: Promise<void> | null;
}

/** 서버에서 읽어 바꾸기. 읽는 중에 또 부르면 그 요청을 같이 기다린다. */
export function reader(id: number, get: GetState, set: SetState, q: Queue) {
  function apply(next: ScheduleView) {
    set((s) => {
      const view = share(s.view, next);
      const keep = s.selected && view.activities.some((a) => a.id === s.selected);
      return { view, loadError: null, ...(keep ? {} : { selected: null, selectedBy: null }) };
    });
  }

  async function fetchView() {
    const seq = ++q.loadSeq;
    try {
      const view = await sapi.getSchedule(id);
      if (seq !== q.loadSeq) return;
      if ((get().view?.version ?? 0) > view.version) return; // 그 사이 쓰기가 더 새 버전을 줬다 — 옛 답으로 덮지 않는다
      apply(view);
      set({ lastChange: null }); // 다시 읽은 일정(409·다른 곳의 고침)에는 이 창 고침의 지연 알림을 두지 않는다
    } catch (e) {
      if (seq !== q.loadSeq) return;
      // 보던 일정이 있으면 그대로 두고 알림만, 없으면 화면에 오류를 보인다.
      if (get().view) set({ notice: { tone: 'error', text: errorText(e) } });
      else set({ loadError: errorText(e) });
    }
  }

  function load() {
    q.loading ??= fetchView().finally(() => (q.loading = null));
    return q.loading;
  }

  return { apply, fetchView, load };
}
