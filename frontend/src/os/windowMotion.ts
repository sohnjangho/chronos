/**
 * 창 움직임(맥OS 처럼 짧게): 열기·닫기·최소화·복귀·확대. transform·opacity 만 Web Animations API 로 움직인다.
 * - 언제 움직이고 언제 끝나는지는 store 가 정한다(`Win.motion` 을 붙이고 시간이 지나면 걷는다. 닫기는 그때 창을 지운다).
 * - 창(Window.tsx)은 `Win.motion` 이 바뀌면 그 움직임을 그리기만 한다.
 * - 동작 줄이기(prefers-reduced-motion)이거나 시험 스위치가 꺼져 있으면 움직임 없이 바로 바뀐다.
 */
import type { Win } from './windowStore';

export type Motion = 'open' | 'close' | 'minimize' | 'restore' | 'zoom';

interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}
interface Pt {
  x: number;
  y: number;
}

export const MOTION_MS: Record<Motion, number> = { open: 220, close: 160, minimize: 260, restore: 260, zoom: 200 };

const EASE_OUT = 'cubic-bezier(0.22, 1, 0.36, 1)';
const EASING: Record<Motion, string> = {
  open: EASE_OUT,
  close: 'cubic-bezier(0.4, 0, 1, 1)', // ease-in
  minimize: 'cubic-bezier(0.32, 0.72, 0, 1)', // 부드러운 스르륵 곡선
  restore: 'cubic-bezier(0.22, 1, 0.36, 1)',
  zoom: EASE_OUT,
};

// 시험(jsdom)에서는 기본으로 끈다. 움직임을 보는 시험만 setWindowMotion(true) 로 켠다.
let enabled = import.meta.env.MODE !== 'test';

/** 시험용 스위치. */
export function setWindowMotion(on: boolean): void {
  enabled = on;
}

export const prefersReducedMotion = () =>
  typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

export const motionOn = () => enabled && !prefersReducedMotion();

// ── store 쪽: 움직임 표시를 붙이고 시간이 지나면 걷는다 ──

type WinsSet = (fn: (s: { wins: Win[] }) => { wins: Win[] }) => void;
const timers = new Map<string, ReturnType<typeof setTimeout>>();

export const isClosing = (w: Win) => w.motion === 'close';

function withoutMotion(w: Win): Win {
  const rest = { ...w };
  delete rest.motion;
  delete rest.fromDock;
  return rest;
}

/** 끝난 움직임을 걷는다. 닫기면 그 창을 지운다. 그사이 다른 움직임으로 바뀌었으면 그대로 둔다. */
function endMotion(wins: Win[], id: string, kind: Motion): Win[] {
  if (kind === 'close') return wins.filter((w) => w.id !== id || !isClosing(w));
  return wins.map((w) => (w.id === id && w.motion === kind ? withoutMotion(w) : w));
}

/** 창 id 에 움직임 kind 를 붙이고 MOTION_MS 뒤에 걷는다. 움직임이 꺼져 있으면 아무것도 하지 않고 false. */
export function startMotion(set: WinsSet, id: string, kind: Motion, extra: Partial<Win> = {}): boolean {
  if (!motionOn()) return false;
  set((s) => ({ wins: s.wins.map((w) => (w.id === id ? { ...w, ...extra, motion: kind } : w)) }));
  clearTimeout(timers.get(id));
  const end = () => {
    timers.delete(id);
    set((s) => ({ wins: endMotion(s.wins, id, kind) }));
  };
  timers.set(id, setTimeout(end, MOTION_MS[kind]));
  return true;
}

/** 걸린 움직임 시계를 모두 지운다(로그아웃 등 store 를 비울 때). */
export function clearMotionTimers(): void {
  timers.forEach(clearTimeout);
  timers.clear();
}

type Raise = (id: string, extra?: (w: Win) => Partial<Win>) => void;

/**
 * 창 store 의 움직임이 있는 동작. 움직임이 꺼져 있으면 예전처럼 바로 바뀐다.
 * 닫히는 중인 창(close 움직임)은 없는 창으로 쳐서 다시 닫거나·앞으로 가져오거나·줄이거나·키우지 않는다.
 */
export function motionActions(set: WinsSet, get: () => { wins: Win[] }, raise: Raise) {
  const find = (id: string) => get().wins.find((w) => w.id === id);
  const closing = (id: string) => find(id)?.motion === 'close';
  const actions = {
    /** 앞으로 가져오며 최소화를 푼다. 최소화돼 있었으면 Dock 아이콘에서 돌아오는 움직임. */
    restore(id: string, extra: Partial<Win> = {}) {
      if (closing(id)) return;
      const wasMinimized = find(id)?.minimized;
      raise(id, () => ({ minimized: false, ...extra }));
      if (wasMinimized) startMotion(set, id, 'restore');
    },
    /** 닫히는 움직임이 끝난 뒤 지운다. 최소화한 창은 보일 것이 없어 바로 지운다. */
    close(id: string) {
      const w = find(id);
      if (!w || isClosing(w) || (!w.minimized && startMotion(set, id, 'close'))) return;
      set((s) => ({ wins: s.wins.filter((x) => x.id !== id) }));
    },
    /** store 에서는 바로 최소화(활성 창이 바로 바뀐다). 창은 Dock 아이콘으로 줄어든 뒤 숨는다. */
    minimize(id: string) {
      const w = find(id);
      if (!w || w.minimized || isClosing(w)) return;
      set((s) => ({ wins: s.wins.map((x) => (x.id === id ? { ...x, minimized: true } : x)) }));
      startMotion(set, id, 'minimize');
    },
    toggleMaximize(id: string) {
      if (closing(id)) return;
      raise(id, (w) => ({ maximized: !w.maximized }));
      const w = find(id);
      if (w && w.motion !== 'open') startMotion(set, id, 'zoom'); // 막 열리는 창은 열기 움직임 그대로
    },
    minimizeAll() {
      const shown = get().wins.filter((w) => !w.minimized && !isClosing(w));
      shown.forEach((w) => actions.minimize(w.id));
      return shown.length;
    },
    closeAll() {
      const live = get().wins.filter((w) => !isClosing(w));
      live.forEach((w) => actions.close(w.id));
      return live.length;
    },
  };
  return actions;
}

// ── Dock 아이콘 자리 ──

const anchors = new Map<string, HTMLElement>();
/** Dock 타일 가운데에서 화면 아래 끝까지(아래 12 + 테두리 1 + 안쪽 8 + 실행 점 4 + 틈 4 + 타일 반 24). */
const ICON_FROM_BOTTOM = 53;

/**
 * Dock 이 프로그램 타일을 그릴 때 부른다. ref 가 null 로 풀릴 때 지우지 않는다: Dock 은 그릴 때마다 ref 를
 * 풀었다 다시 거는데, 다시 거는 때가 창의 움직임(layout effect)보다 늦다. 빠진 타일은 문서에서 떨어져 나가 무시된다.
 */
export function setDockAnchor(programId: string, el: HTMLElement): void {
  anchors.set(programId, el);
}

/** 그 프로그램 Dock 아이콘의 가운데(화면 px). Dock 이 아래로 숨어 있으면(확대한 창) 보일 때의 높이로 친다. */
export function dockIconCenter(programId: string): Pt | null {
  const el = anchors.get(programId);
  const r = el?.isConnected ? el.getBoundingClientRect() : null;
  if (!r || !r.width) return null;
  return { x: r.left + r.width / 2, y: Math.min(r.top + r.height / 2, window.innerHeight - ICON_FROM_BOTTOM) };
}

const bottomCenter = (): Pt => ({ x: window.innerWidth / 2, y: window.innerHeight });

// ── 움직임 모양(keyframes) ──

const px = (v: number) => `${Math.round(v * 100) / 100}px`;
const num = (v: number) => Math.round(v * 10000) / 10000;
const TOP_LEFT = '0px 0px';
const ICON_SIZE = 48;

/** 열기: 원점(아이콘 또는 화면 가운데 아래) 쪽에서 0.6 → 1 로 커지며 나타난다. */
export function openFrames(rect: Box, origin: Pt): Keyframe[] {
  const transformOrigin = `${px(origin.x - rect.x)} ${px(origin.y - rect.y)}`;
  return [
    { transformOrigin, transform: 'scale(0.6)', opacity: 0 },
    { transformOrigin, transform: 'scale(1)', opacity: 1 },
  ];
}

/** 닫기: 그 자리에서 살짝 작아지며 사라진다. */
export function closeFrames(): Keyframe[] {
  return [
    { transform: 'scale(1)', opacity: 1 },
    { transform: 'scale(0.92)', opacity: 0 },
  ];
}

/** 최소화(크기 조절 효과): 아이콘 크기로 줄며 아이콘 가운데로 들어간다. 끝 무렵에 흐려진다. */
export function minimizeFrames(rect: Box, icon: Pt): Keyframe[] {
  const s = ICON_SIZE / Math.max(rect.w, rect.h);
  const tx = icon.x - rect.x - (rect.w * s) / 2;
  const ty = icon.y - rect.y - (rect.h * s) / 2;
  return [
    { transformOrigin: TOP_LEFT, transform: 'translate(0px, 0px) scale(1)', opacity: 1 },
    { offset: 0.6, opacity: 1 },
    { transformOrigin: TOP_LEFT, transform: `translate(${px(tx)}, ${px(ty)}) scale(${num(s)})`, opacity: 0 },
  ];
}

/** 확대·복귀: 새 자리에 그린 창을 옛 자리 모양에서 새 자리로(FLIP). 레이아웃은 한 번만 바뀐다. */
export function zoomFrames(from: Box, to: Box): Keyframe[] {
  const start = `translate(${px(from.x - to.x)}, ${px(from.y - to.y)}) scale(${num(from.w / to.w)}, ${num(from.h / to.h)})`;
  return [
    { transformOrigin: TOP_LEFT, transform: start },
    { transformOrigin: TOP_LEFT, transform: 'translate(0px, 0px) scale(1, 1)' },
  ];
}

export interface MotionTarget {
  kind: Motion;
  /** 지금 그린 창 자리. */
  rect: Box;
  /** 바로 앞에 그린 창 자리(확대·복귀의 출발점). */
  from: Box;
  programId: string;
  fromDock: boolean;
}

function framesFor(t: MotionTarget): Keyframe[] {
  const icon = () => dockIconCenter(t.programId) ?? bottomCenter();
  if (t.kind === 'open') return openFrames(t.rect, t.fromDock ? icon() : bottomCenter());
  if (t.kind === 'close') return closeFrames();
  if (t.kind === 'zoom') return zoomFrames(t.from, t.rect);
  return minimizeFrames(t.rect, icon());
}

/** 창 요소에 움직임 하나를 건다. 끝난 모양을 store 가 걷을 때까지 붙들어 둔다(fill forwards). */
export function playMotion(el: HTMLElement, t: MotionTarget): Animation {
  return el.animate(framesFor(t), {
    duration: MOTION_MS[t.kind],
    easing: EASING[t.kind],
    fill: 'forwards',
    ...(t.kind === 'restore' ? { direction: 'reverse' as const } : {}),
  });
}
