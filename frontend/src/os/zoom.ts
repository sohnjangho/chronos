import { create } from 'zustand';
import { loadPref, savePref } from './prefs';

/** 창 본문 배율 단계(%). 50~200. */
export const ZOOM_STEPS = [50, 67, 75, 80, 90, 100, 110, 125, 150, 175, 200];

interface ZoomState {
  userId: number | null;
  /** 프로그램 id → 배율(%). 없으면 100. */
  levels: Record<string, number>;
  load(userId: number | null): void;
  zoomIn(programId: string): void;
  zoomOut(programId: string): void;
  reset(programId: string): void;
  resetAll(): void;
}

export const zoomOf = (levels: Record<string, number>, programId: string) => levels[programId] ?? 100;

function step(current: number, dir: 1 | -1): number {
  const i = ZOOM_STEPS.indexOf(current);
  const at = i < 0 ? ZOOM_STEPS.indexOf(100) : i;
  return ZOOM_STEPS[Math.max(0, Math.min(ZOOM_STEPS.length - 1, at + dir))];
}

/** 저장된 값 가운데 메뉴 단계에 있는 숫자만 받는다(나머지는 100%). */
function validLevels(saved: unknown): Record<string, number> {
  if (!saved || typeof saved !== 'object' || Array.isArray(saved)) return {};
  return Object.fromEntries(
    Object.entries(saved).filter((e): e is [string, number] => typeof e[1] === 'number' && ZOOM_STEPS.includes(e[1])),
  );
}

/** 프로그램마다 배율을 기억한다(사용자별 저장). */
export const useZoom = create<ZoomState>((set, get) => {
  const put = (programId: string, value: number) => {
    const levels = { ...get().levels, [programId]: value };
    savePref('zoom', get().userId, levels);
    set({ levels });
  };
  return {
    userId: null,
    levels: {},
    load(userId) {
      set({ userId, levels: validLevels(loadPref('zoom', userId)) });
    },
    zoomIn: (id) => put(id, step(zoomOf(get().levels, id), 1)),
    zoomOut: (id) => put(id, step(zoomOf(get().levels, id), -1)),
    reset: (id) => put(id, 100),
    resetAll() {
      savePref('zoom', get().userId, {});
      set({ levels: {} });
    },
  };
});
