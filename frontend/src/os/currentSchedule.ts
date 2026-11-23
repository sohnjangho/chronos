// 지금 다루는 일정(메뉴바 프로젝트/일정 선택). OS 상태라서 프로그램이 읽어도 된다. 사용자별로 기억한다.
import { create } from 'zustand';
import { loadPref, savePref } from './prefs';
import { useWindows } from './windowStore';

export interface CurrentSchedule {
  id: number;
  name: string;
}

export type NewProjectModalMode = 'closed' | 'direct' | 'ai';

interface CurrentScheduleState {
  /** 누구의 현장인지(저장 열쇠 chronos.schedule.<id>). 로그인 전이면 null(메모리에만). */
  userId: number | null;
  current: CurrentSchedule | null;
  /** 새 프로젝트가 생성·승인될 때마다 증가해 ScheduleSelector 목록을 새로 읽는다. */
  reloadToken: number;
  /** 지연 기록 창에서 사건이 바뀔 때마다 증가해 간트·공정률 창의 「기록된 지연」 띠가 다시 센다(일정은 다시 읽지 않는다). */
  delaysToken: number;
  /** 새 프로젝트 만들기 모달 상태. */
  newProjectModal: NewProjectModalMode;
  /** 새 프로젝트 생성 격리 모드(기존 일정과 분리). */
  creatingNewProject: boolean;
  setCurrent(current: CurrentSchedule | null): void;
  /** 그 사용자의 저장된 현장을 읽는다(셸이 사용자가 바뀔 때 그리기 전에 부른다). */
  load(userId: number | null): void;
  bumpReload(): void;
  bumpDelays(): void;
  openNewProjectModal(mode?: 'direct' | 'ai'): void;
  closeNewProjectModal(): void;
  setCreatingNewProject(on: boolean): void;
  enterNewProjectMode(): void;
}

function valid(raw: unknown): CurrentSchedule | null {
  const r = raw as CurrentSchedule | null;
  return r && typeof r.id === 'number' && typeof r.name === 'string' ? { id: r.id, name: r.name } : null;
}

export const useCurrentSchedule = create<CurrentScheduleState>((set, get) => ({
  userId: null,
  current: null,
  reloadToken: 0,
  delaysToken: 0,
  newProjectModal: 'closed',
  creatingNewProject: false,
  setCurrent(current) {
    const prevId = get().current?.id ?? null;
    const nextId = current?.id ?? null;
    savePref('schedule', get().userId, current);
    set({
      current,
      ...(current !== null ? { creatingNewProject: false } : {}),
    });
    if (prevId !== nextId) {
      useWindows.getState().syncSchedule?.(nextId);
    }
  },
  load(userId) {
    set({ userId, current: valid(loadPref('schedule', userId)), creatingNewProject: false });
  },
  bumpReload() {
    set((s) => ({ reloadToken: s.reloadToken + 1 }));
  },
  bumpDelays() {
    set((s) => ({ delaysToken: s.delaysToken + 1 }));
  },
  openNewProjectModal(mode = 'direct') {
    set({ newProjectModal: mode });
  },
  closeNewProjectModal() {
    set({ newProjectModal: 'closed' });
  },
  setCreatingNewProject(on) {
    set({ creatingNewProject: on });
  },
  enterNewProjectMode() {
    savePref('schedule', get().userId, null);
    const prevId = get().current?.id ?? null;
    set({ current: null, creatingNewProject: true, newProjectModal: 'closed' });
    const winState = useWindows.getState();
    if (prevId !== null) winState.syncSchedule?.(null);
    winState.minimizeScheduleWindows?.();
  },
}));
