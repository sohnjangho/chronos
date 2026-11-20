// 일정 창 안에서 쓰는 일정 저장소. 프로그램 창(ScheduleFrame)이 그 창의 일정 저장소와 창 id 를 넘긴다.
import { createContext, useCallback, useContext } from 'react';
import { useStore } from 'zustand';
import type { ScheduleState, ScheduleStore } from './scheduleStore';

export interface Scope {
  store: ScheduleStore;
  windowId: string;
}

export const ScheduleScope = createContext<Scope | null>(null);

function useScope(): Scope {
  const scope = useContext(ScheduleScope);
  if (!scope) throw new Error('일정 창(ScheduleFrame) 밖에서는 일정 저장소를 쓸 수 없습니다.');
  return scope;
}

/** 이 창이 보는 일정의 저장소(이벤트 처리기에서 getState() 로 쓴다). */
export const useScheduleStore = (): ScheduleStore => useScope().store;

/** 이 창의 id. */
export const useWindowId = (): string => useScope().windowId;

/** 이 창이 보는 일정 저장소에서 고른 값(바뀌면 다시 그린다). */
export function useSchedule<T>(selector: (s: ScheduleState) => T): T {
  return useStore(useScope().store, selector);
}

/** 이 창에만 보일 안내(창 안의 동작에서 난 것). 서버가 거절한 것은 저장소가 모든 창에 보인다. */
export function useNotify(): (tone: 'error' | 'info', text: string) => void {
  const { store, windowId } = useScope();
  return useCallback((tone: 'error' | 'info', text: string) => store.getState().setNotice({ tone, text, windowId }), [store, windowId]);
}

/** 이 창에서 고르기. 같은 일정을 보는 다른 창은 그 줄로 따라간다. */
export function useSelect(): (aid: string | null) => void {
  const { store, windowId } = useScope();
  return useCallback((aid: string | null) => store.getState().select(aid, windowId), [store, windowId]);
}
