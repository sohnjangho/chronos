// 지금 다루는 일정(메뉴바 현장 선택). OS 상태라서 프로그램이 읽어도 된다. 사용자별로 기억한다.
import { create } from 'zustand';
import { loadPref, savePref } from './prefs';

export interface CurrentSchedule {
  id: number;
  name: string;
}

interface CurrentScheduleState {
  /** 누구의 현장인지(저장 열쇠 chronos.schedule.<id>). 로그인 전이면 null(메모리에만). */
  userId: number | null;
  current: CurrentSchedule | null;
  setCurrent(current: CurrentSchedule | null): void;
  /** 그 사용자의 저장된 현장을 읽는다(셸이 사용자가 바뀔 때 그리기 전에 부른다). */
  load(userId: number | null): void;
}

function valid(raw: unknown): CurrentSchedule | null {
  const r = raw as CurrentSchedule | null;
  return r && typeof r.id === 'number' && typeof r.name === 'string' ? { id: r.id, name: r.name } : null;
}

export const useCurrentSchedule = create<CurrentScheduleState>((set, get) => ({
  userId: null,
  current: null,
  setCurrent(current) {
    savePref('schedule', get().userId, current);
    set({ current });
  },
  load(userId) {
    set({ userId, current: valid(loadPref('schedule', userId)) });
  },
}));
