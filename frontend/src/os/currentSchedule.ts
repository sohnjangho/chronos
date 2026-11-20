// 지금 다루는 일정(메뉴바 현장 선택). OS 상태라서 프로그램이 읽어도 된다.
import { create } from 'zustand';
import { loadJson, saveJson } from './storage';

export interface CurrentSchedule {
  id: number;
  name: string;
}

interface CurrentScheduleState {
  current: CurrentSchedule | null;
  setCurrent(current: CurrentSchedule | null): void;
}

const KEY = 'chronos.schedule';

function restore(): CurrentSchedule | null {
  const raw = loadJson(KEY) as CurrentSchedule | null;
  return raw && typeof raw.id === 'number' && typeof raw.name === 'string' ? { id: raw.id, name: raw.name } : null;
}

export const useCurrentSchedule = create<CurrentScheduleState>((set) => ({
  current: restore(),
  setCurrent(current) {
    saveJson(KEY, current);
    set({ current });
  },
}));
