import { create } from 'zustand';
import { cascadeBoxes, gridBoxes, splitBoxes, type Box } from './arrange';
import { getProgram, resolveProgram } from './registry';
import { clearMotionTimers, isClosing, motionActions, startMotion, type Motion } from './windowMotion';

export { ARRANGE_GAP } from './arrange';

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
  /** 오른쪽 패널 때문에 좁혀지기 전 자리(beforeInset)와 좁힌 자리(insetRect). 패널을 닫을 때 그대로면 되돌린다. */
  beforeInset?: Rect;
  insetRect?: Rect;
  /** 움직이는 중이면 그 움직임(windowMotion.ts). 닫히는 중인 창은 없는 창으로 친다. fromDock: Dock 아이콘에서 열었다. */
  motion?: Motion;
  fromDock?: boolean;
}

/** 창 자리와 크기(px). */
export type Rect = Box;

/** 크기 조절 손잡이: 네 가장자리와 네 모서리. */
export type Edge = 'n' | 's' | 'e' | 'w' | 'ne' | 'nw' | 'se' | 'sw';

export const MENUBAR_H = 48;
export const MIN_W = 360;
export const MIN_H = 240;
/** 정렬할 때 Dock 몫으로 아래에 남기는 높이(Dock 74 + 아래 12 + 틈 8). 확대한 창은 Dock 이 숨으므로 아래 끝까지 찬다. */
export const DOCK_RESERVE = 94;
const CASCADE = 32;
const START = { x: 24, y: MENUBAR_H + 20 };
const FALLBACK_SIZE = { w: 800, h: 600 };
const LIMITS = { minW: MIN_W, minH: MIN_H };

/** 창이 쓸 수 있는 화면. 오른쪽에 붙은 패널(Context 패널) 폭만큼 좁다. */
const screenSize = () => ({ w: window.innerWidth - useWindows.getState().insetRight, h: window.innerHeight });
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
  return { w: clamp(Math.round(size.w), MIN_W, s.w), h: clamp(Math.round(size.h), MIN_H, s.h - MENUBAR_H) };
}

/**
 * 지금 화면에 맞춘 자리. 화면보다 크면 줄이고, 메뉴바 아래·화면 안으로 옮긴다.
 * 화면이 최소 크기보다 작으면 왼쪽 위(0, 44)에 붙여 신호등 단추가 늘 보이게 한다.
 */
function fitRect(r: Rect): Rect {
  const size = fitSize(r);
  return { ...clampPos(Math.round(r.x), Math.round(r.y), size.w, size.h), ...size };
}

/** 손잡이 edge 를 (dx, dy) 만큼 끈 결과. 반대쪽 가장자리는 그대로, 최소 크기·화면 안을 지킨다. */
export function resizeRect(start: Rect, edge: Edge, dx: number, dy: number): Rect {
  const s = screenSize();
  const right = start.x + start.w;
  const bottom = start.y + start.h;
  const r = { ...start };
  if (edge.includes('e')) r.w = clamp(start.w + dx, MIN_W, s.w - start.x);
  if (edge.includes('s')) r.h = clamp(start.h + dy, MIN_H, s.h - start.y);
  if (edge.includes('w')) {
    r.x = clamp(start.x + dx, 0, right - MIN_W);
    r.w = right - r.x;
  }
  if (edge.includes('n')) {
    r.y = clamp(start.y + dy, MENUBAR_H, bottom - MIN_H);
    r.h = bottom - r.y;
  }
  return r;
}

/** 앞에 새로 연 창에서 32px 오른쪽·아래. 화면을 벗어나면 왼쪽 위로 돌아간다. */
function cascadeFrom(last: { x: number; y: number } | null, w: number, h: number) {
  const s = screenSize();
  const next = last ? { x: last.x + CASCADE, y: last.y + CASCADE } : START;
  const fits = next.x + w <= s.w && next.y + h <= s.h;
  const at = fits ? next : START;
  return clampPos(at.x, at.y, w, h);
}

/** 확대한 창이 차지하는 자리: 메뉴바 아래부터 화면 아래 끝까지(그동안 Dock 은 숨는다). */
export function workArea(): Rect {
  const s = screenSize();
  return { x: 0, y: MENUBAR_H, w: s.w, h: Math.max(MIN_H, s.h - MENUBAR_H) };
}

/** 정렬 영역: 메뉴바 아래, Dock 몫을 뺀 곳. */
function arrangeArea(): Rect {
  const s = screenSize();
  return { x: 0, y: MENUBAR_H, w: s.w, h: Math.max(MIN_H, s.h - MENUBAR_H - DOCK_RESERVE) };
}

/** 최소화하지 않은 창 가운데 맨 앞. */
export function topWindow(wins: Win[]): Win | null {
  let top: Win | null = null;
  for (const w of wins) if (!w.minimized && !isClosing(w) && (!top || w.z > top.z)) top = w;
  return top;
}

/** 활성 창: 바탕화면 빈 곳을 눌러 활성을 풀었으면 없다. */
export function activeWindow(s: { wins: Win[]; deactivated: boolean }): Win | null {
  return s.deactivated ? null : topWindow(s.wins);
}

export type ArrangeKind = 'split' | 'grid' | 'cascade';

/** 보이는 창을 정렬한 새 목록. 활성 창(없으면 맨 앞 창)이 첫 칸이다. 정렬한 창은 확대를 푼다. */
function arranged(s: { wins: Win[]; deactivated: boolean }, kind: ArrangeKind): Win[] {
  const lead = activeWindow(s) ?? topWindow(s.wins);
  const shown = s.wins.filter((w) => !w.minimized && !isClosing(w)).sort((a, b) => (a === lead ? -1 : b === lead ? 1 : a.z - b.z));
  const area = arrangeArea();
  const boxes =
    kind === 'split'
      ? splitBoxes(shown.length, area, LIMITS)
      : kind === 'grid'
        ? gridBoxes(shown.length, area, LIMITS)
        : cascadeBoxes(shown, area, LIMITS);
  const byId = new Map(shown.map((w, i) => [w.id, boxes[i]]));
  return s.wins.map((w) => (byId.has(w.id) ? { ...w, ...byId.get(w.id)!, maximized: false } : w));
}

type Params = Record<string, string>;
type SetState = (partial: Partial<WindowState> | ((s: WindowState) => Partial<WindowState>)) => void;

interface WindowState {
  wins: Win[];
  topZ: number;
  seq: number;
  lastOpen: { x: number; y: number } | null;
  /** 바탕화면 빈 곳을 눌러 활성 창을 풀었다. 창을 앞으로 가져오면 다시 false. */
  deactivated: boolean;
  /** 오른쪽에 붙은 패널 폭(px). 창은 그만큼 좁은 화면에 맞춘다. */
  insetRight: number;
  /**
   * 이미 열려 있으면 앞으로 가져오고(최소화 풀기) params 를 바꾼다. 창 id 를 돌려준다. from: 연 곳(움직임 원점).
   * 없어진 프로그램 id(옛 일정판 schedule)는 지금 프로그램으로 연다(registry.resolveProgram).
   */
  open(programId: string, params?: Params, from?: 'dock'): string;
  close(id: string): void;
  focus(id: string): void;
  move(id: string, x: number, y: number): void;
  resize(id: string, w: number, h: number): void;
  /** 자리와 크기를 한 번에(왼쪽·위 가장자리 크기 조절). 화면 안으로 맞춘다. */
  setBounds(id: string, rect: Rect): void;
  /** 창 제목 줄과 aria-label 만 바뀐다. 메뉴바는 프로그램 이름을 그대로 보인다. */
  setTitle(id: string, title: string): void;
  /** 브라우저 크기가 바뀌면 모든 창을 화면 안으로 다시 맞춘다. */
  fitToScreen(): void;
  minimize(id: string): void;
  toggleMaximize(id: string): void;
  activeProgramId(): string | null;
  /** 활성 창을 푼다(바탕화면 빈 곳 누름). */
  clearActive(): void;
  /** 보이는 창을 정렬하고 그 수를 돌려준다. */
  arrange(kind: ArrangeKind): number;
  minimizeAll(): number;
  closeAll(): number;
  closeActive(): void;
  /** 맨 뒤의 보이는 창을 앞으로(누를 때마다 모든 창을 차례로 돈다). */
  nextWindow(): void;
  setInsetRight(px: number): void;
  reset(): void;
}

const initial = { wins: [] as Win[], topZ: 0, seq: 0, lastOpen: null, deactivated: false, insetRight: 0 };

/** 새 창: 프로그램 기본 크기(화면에 맞춤), 계단식 자리, 맨 앞. */
function newWindow(
  s: Pick<WindowState, 'wins' | 'topZ' | 'seq' | 'lastOpen'>,
  programId: string,
  params?: Params,
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

const sameRect = (a: Rect, b: Rect) => a.x === b.x && a.y === b.y && a.w === b.w && a.h === b.h;
const rectOf = (w: Rect): Rect => ({ x: w.x, y: w.y, w: w.w, h: w.h });

/** 패널이 넓어져 창을 좁힐 때: 바뀐 창은 원래 자리를 기억한다. */
function narrowed(w: Win): Win {
  const fitted = fitRect(w);
  if (sameRect(fitted, w)) return w;
  return { ...w, ...fitted, beforeInset: w.beforeInset ?? rectOf(w), insetRect: fitted };
}

/** 패널이 좁아지거나 닫힐 때: 좁힌 뒤 손대지 않은 창은 원래 자리로(지금 화면에 맞춰) 되돌린다. */
function widened(w: Win): Win {
  const { beforeInset, insetRect, ...rest } = w;
  const untouched = beforeInset && insetRect && sameRect(w, insetRect);
  return { ...rest, ...fitRect(untouched ? beforeInset : rest) };
}

const patcher = (set: SetState) => (id: string, change: (w: Win) => Partial<Win>) =>
  set((s) => ({ wins: s.wins.map((w) => (w.id === id ? { ...w, ...change(w) } : w)) }));

// 앞으로 가져올 때(열기·복귀·누름) 지금 화면에 맞추고 활성 해제를 끝낸다.
const raiser = (set: SetState) => (id: string, extra: (w: Win) => Partial<Win> = () => ({})) =>
  set((s) => ({
    topZ: s.topZ + 1,
    deactivated: false,
    wins: s.wins.map((w) => (w.id === id ? { ...w, ...fitRect(w), ...extra(w), z: s.topZ + 1 } : w)),
  }));

/** 윈도우 메뉴의 정렬·일괄 명령. */
function bulkActions(set: SetState, get: () => WindowState) {
  const raise = raiser(set);
  const shown = () => get().wins.filter((w) => !w.minimized && !isClosing(w));
  return {
    clearActive: () => set({ deactivated: true }),
    arrange(kind: ArrangeKind) {
      const n = shown().length;
      if (n) set((s) => ({ wins: arranged(s, kind), deactivated: false }));
      return n;
    },
    closeActive() {
      const active = activeWindow(get());
      if (active) get().close(active.id);
    },
    nextWindow() {
      const back = shown().sort((a, b) => a.z - b.z)[0];
      if (back) raise(back.id);
    },
    setInsetRight(px: number) {
      const growing = px > get().insetRight;
      set({ insetRight: px });
      set((s) => ({ wins: s.wins.map((w) => (growing ? narrowed(w) : widened(w))) }));
    },
  };
}

export const useWindows = create<WindowState>((set, get) => {
  const patch = patcher(set);
  const raise = raiser(set);
  // 닫기·최소화·확대·복귀(+ 모두 최소화·모두 닫기)는 움직임과 함께 windowMotion 이 한다.
  const { restore, ...withMotion } = motionActions(set, get, raise);
  return {
    ...initial,
    ...bulkActions(set, get),
    ...withMotion,
    open(requested, requestedParams, from) {
      const { id: programId, params } = resolveProgram(requested, requestedParams);
      const found = get().wins.find((w) => w.programId === programId && !isClosing(w));
      if (found) {
        restore(found.id, params ? { params } : {});
        return found.id;
      }
      const s = get();
      const win = newWindow(s, programId, params);
      set({ seq: s.seq + 1, topZ: win.z, lastOpen: { x: win.x, y: win.y }, wins: [...s.wins, win], deactivated: false });
      startMotion(set, win.id, 'open', from === 'dock' ? { fromDock: true } : {});
      return win.id;
    },
    focus: (id) => restore(id),
    move: (id, x, y) => patch(id, (w) => clampPos(Math.round(x), Math.round(y), w.w, w.h)),
    resize: (id, w, h) => patch(id, (win) => sizeWithin(win, w, h)),
    setBounds: (id, rect) => patch(id, () => fitRect(rect)),
    setTitle: (id, title) => patch(id, () => ({ title })),
    fitToScreen: () => set((s) => ({ wins: s.wins.map((w) => ({ ...w, ...fitRect(w) })) })),
    activeProgramId: () => activeWindow(get())?.programId ?? null,
    reset() {
      clearMotionTimers();
      set(initial);
    },
  };
});
