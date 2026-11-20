import { create } from 'zustand';
import { getProgram } from './registry';

export interface Win {
  id: string;
  programId: string;
  title: string;
  x: number;
  y: number;
  w: number;
  h: number;
  z: number;
  minimized: boolean;
  maximized: boolean;
  params?: Record<string, string>;
}

interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export const MENUBAR_H = 44;
export const MIN_W = 360;
export const MIN_H = 240;
/** 확대한 창이 Dock 을 가리지 않게 화면 아래에 남기는 높이. */
export const DOCK_SPACE = 96;
const CASCADE = 32;
const START = { x: 24, y: MENUBAR_H + 20 };
const FALLBACK_SIZE = { w: 800, h: 600 };

const screenSize = () => ({ w: window.innerWidth, h: window.innerHeight });
const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(v, hi));

/** 창을 메뉴바 아래, 화면 안으로. */
function clampPos(x: number, y: number, w: number, h: number) {
  const s = screenSize();
  return { x: clamp(x, 0, s.w - w), y: clamp(y, MENUBAR_H, s.h - h) };
}

/** 최소 크기 이상, 화면 오른쪽·아래 끝을 넘지 않게. */
function sizeWithin(win: Rect, w: number, h: number) {
  const s = screenSize();
  return { w: clamp(Math.round(w), MIN_W, s.w - win.x), h: clamp(Math.round(h), MIN_H, s.h - win.y) };
}

function fitSize(size: { w: number; h: number }) {
  const s = screenSize();
  return { w: clamp(size.w, MIN_W, s.w), h: clamp(size.h, MIN_H, s.h - MENUBAR_H) };
}

/** 앞에 새로 연 창에서 32px 오른쪽·아래. 화면을 벗어나면 왼쪽 위로 돌아간다. */
function cascadeFrom(last: { x: number; y: number } | null, w: number, h: number) {
  const s = screenSize();
  const next = last ? { x: last.x + CASCADE, y: last.y + CASCADE } : START;
  const fits = next.x + w <= s.w && next.y + h <= s.h;
  const at = fits ? next : START;
  return clampPos(at.x, at.y, w, h);
}

/** 확대한 창이 차지하는 자리. */
export function workArea(): Rect {
  const s = screenSize();
  return { x: 0, y: MENUBAR_H, w: s.w, h: Math.max(MIN_H, s.h - MENUBAR_H - DOCK_SPACE) };
}

/** 최소화하지 않은 창 가운데 맨 앞. */
export function topWindow(wins: Win[]): Win | null {
  let top: Win | null = null;
  for (const w of wins) if (!w.minimized && (!top || w.z > top.z)) top = w;
  return top;
}

interface WindowState {
  wins: Win[];
  topZ: number;
  seq: number;
  lastOpen: { x: number; y: number } | null;
  /** 이미 열려 있으면 앞으로 가져오고(최소화 풀기) params 를 바꾼다. 창 id 를 돌려준다. */
  open(programId: string, params?: Record<string, string>): string;
  close(id: string): void;
  focus(id: string): void;
  move(id: string, x: number, y: number): void;
  resize(id: string, w: number, h: number): void;
  minimize(id: string): void;
  toggleMaximize(id: string): void;
  activeProgramId(): string | null;
  reset(): void;
}

const initial = { wins: [] as Win[], topZ: 0, seq: 0, lastOpen: null };

/** 새 창: 프로그램 기본 크기(화면에 맞춤), 계단식 자리, 맨 앞. */
function newWindow(
  s: Pick<WindowState, 'wins' | 'topZ' | 'seq' | 'lastOpen'>,
  programId: string,
  params?: Record<string, string>,
): Win {
  const program = getProgram(programId);
  const size = fitSize(program?.defaultSize ?? FALLBACK_SIZE);
  const pos = cascadeFrom(s.wins.length ? s.lastOpen : null, size.w, size.h);
  return {
    id: `w${s.seq + 1}`,
    programId,
    title: program?.name ?? programId,
    ...pos,
    ...size,
    z: s.topZ + 1,
    minimized: false,
    maximized: false,
    ...(params ? { params } : {}),
  };
}

export const useWindows = create<WindowState>((set, get) => {
  const patch = (id: string, change: (w: Win) => Partial<Win>) =>
    set((s) => ({ wins: s.wins.map((w) => (w.id === id ? { ...w, ...change(w) } : w)) }));
  const raise = (id: string, extra: (w: Win) => Partial<Win> = () => ({})) =>
    set((s) => ({
      topZ: s.topZ + 1,
      wins: s.wins.map((w) => (w.id === id ? { ...w, ...extra(w), z: s.topZ + 1 } : w)),
    }));

  return {
    ...initial,
    open(programId, params) {
      const found = get().wins.find((w) => w.programId === programId);
      if (found) {
        raise(found.id, () => ({ minimized: false, ...(params ? { params } : {}) }));
        return found.id;
      }
      const s = get();
      const win = newWindow(s, programId, params);
      set({ seq: s.seq + 1, topZ: win.z, lastOpen: { x: win.x, y: win.y }, wins: [...s.wins, win] });
      return win.id;
    },
    close(id) {
      set((s) => ({ wins: s.wins.filter((w) => w.id !== id) }));
    },
    focus(id) {
      raise(id, () => ({ minimized: false }));
    },
    move(id, x, y) {
      patch(id, (w) => clampPos(Math.round(x), Math.round(y), w.w, w.h));
    },
    resize(id, w, h) {
      patch(id, (win) => sizeWithin(win, w, h));
    },
    minimize(id) {
      patch(id, () => ({ minimized: true }));
    },
    toggleMaximize(id) {
      raise(id, (w) => ({ maximized: !w.maximized }));
    },
    activeProgramId() {
      return topWindow(get().wins)?.programId ?? null;
    },
    reset() {
      set(initial);
    },
  };
});
