import { lazy } from 'react';
import { beforeEach, expect, test, vi } from 'vitest';
import { register } from './registry';
import { MENUBAR_H, resizeRect, useWindows, type Win } from './windowStore';

const program = (id: string, w: number, h: number) =>
  register({ id, name: id, icon: null, kind: 'work', defaultSize: { w, h }, component: lazy(() => import('./Placeholder')) });
const screenIs = (w: number, h: number) => {
  vi.stubGlobal('innerWidth', w);
  vi.stubGlobal('innerHeight', h);
};
const insideScreen = (w: Win, sw: number, sh: number) => {
  expect(w.x).toBeGreaterThanOrEqual(0);
  expect(w.y).toBeGreaterThanOrEqual(MENUBAR_H);
  expect(w.x + w.w).toBeLessThanOrEqual(sw);
  expect(w.y + w.h).toBeLessThanOrEqual(sh);
};

const s = () => useWindows.getState();
const win = (id: string): Win => s().wins.find((w) => w.id === id)!;
const top = (): Win => [...s().wins].sort((a, b) => b.z - a.z)[0];

beforeEach(() => {
  vi.stubGlobal('innerWidth', 1920);
  vi.stubGlobal('innerHeight', 1080);
  s().reset();
});

test('open twice focuses the same window', () => {
  const a = s().open('schedule');
  s().open('chat');
  const b = s().open('schedule', { tab: 'gantt' });
  expect(b).toBe(a);
  expect(top().id).toBe(a);
  expect(win(a).params).toEqual({ tab: 'gantt' });
});

test('focus raises z above all', () => {
  const a = s().open('a');
  const b = s().open('b');
  s().focus(a);
  expect(win(a).z).toBeGreaterThan(win(b).z);
});

test('move is clamped below the menubar and inside the screen', () => {
  const a = s().open('a');
  s().move(a, -500, -500);
  expect(win(a).y).toBeGreaterThanOrEqual(44);
  expect(win(a).x).toBeGreaterThan(-win(a).w);
  s().move(a, 5000, 5000);
  expect(win(a).x + win(a).w).toBeLessThanOrEqual(1920);
  expect(win(a).y + win(a).h).toBeLessThanOrEqual(1080);
});

test('resize has a minimum', () => {
  const a = s().open('a');
  s().resize(a, 10, 10);
  expect(win(a)).toMatchObject({ w: 360, h: 240 });
});

test('minimized window is not active', () => {
  const a = s().open('a');
  s().minimize(a);
  expect(s().activeProgramId()).toBeNull();
});

test('active program is the top window that is not minimized', () => {
  s().open('a');
  const b = s().open('b');
  expect(s().activeProgramId()).toBe('b');
  s().minimize(b);
  expect(s().activeProgramId()).toBe('a');
});

test('opening a minimized program restores it and keeps its params', () => {
  const a = s().open('a', { id: '7' });
  s().minimize(a);
  expect(s().open('a')).toBe(a);
  expect(win(a)).toMatchObject({ minimized: false, params: { id: '7' } });
  expect(s().activeProgramId()).toBe('a');
});

test('close removes the window', () => {
  const a = s().open('a');
  s().close(a);
  expect(s().wins).toEqual([]);
  expect(s().activeProgramId()).toBeNull();
});

test('toggleMaximize flips the flag and raises the window', () => {
  const a = s().open('a');
  const b = s().open('b');
  s().toggleMaximize(a);
  expect(win(a).maximized).toBe(true);
  expect(win(a).z).toBeGreaterThan(win(b).z);
  s().toggleMaximize(a);
  expect(win(a).maximized).toBe(false);
});

test('new windows cascade 32px and wrap to the top-left', () => {
  const ids = Array.from({ length: 20 }, (_, i) => s().open(`p${i}`));
  const first = win(ids[0]);
  expect(first.y).toBeGreaterThanOrEqual(MENUBAR_H);
  expect(win(ids[1])).toMatchObject({ x: first.x + 32, y: first.y + 32 });
  const wrapped = ids.findIndex((id, i) => i > 0 && win(id).x === first.x && win(id).y === first.y);
  expect(wrapped).toBeGreaterThan(1);
  const before = win(ids[wrapped - 1]);
  expect(before.y + 32 + before.h > 1080 || before.x + 32 + before.w > 1920).toBe(true);
  for (const id of ids) {
    const w = win(id);
    expect(w.y).toBeGreaterThanOrEqual(MENUBAR_H);
    expect(w.y + w.h).toBeLessThanOrEqual(1080);
    expect(w.x + w.w).toBeLessThanOrEqual(1920);
  }
});

test('default size comes from the program and is clamped to the screen', () => {
  program('huge', 4000, 3000);
  screenIs(1280, 720);
  const a = s().open('huge');
  expect(win(a)).toMatchObject({ x: 0, y: MENUBAR_H, w: 1280, h: 720 - MENUBAR_H });
});

test('setTitle changes only the title', () => {
  const a = s().open('a');
  s().setTitle(a, '일정판 — 5층 사무동 신축');
  expect(win(a)).toMatchObject({ title: '일정판 — 5층 사무동 신축', programId: 'a' });
});

test('fitToScreen keeps every window inside a smaller screen', () => {
  program('big', 1600, 900);
  s().open('big');
  const b = s().open('b');
  s().move(b, 1500, 900);
  screenIs(1280, 720);
  s().fitToScreen();
  for (const w of s().wins) insideScreen(w, 1280, 720);
});

test('on a screen below the minimum size the title bar stays reachable', () => {
  const a = s().open('a');
  s().move(a, 900, 400);
  screenIs(300, 200);
  s().fitToScreen();
  expect(win(a)).toMatchObject({ x: 0, y: MENUBAR_H });
});

test('restore and focus clamp the window to the current screen', () => {
  const a = s().open('a');
  s().move(a, 1100, 450);
  s().minimize(a);
  screenIs(1024, 600);
  s().open('a');
  insideScreen(win(a), 1024, 600);
  screenIs(1920, 1080);
  s().move(a, 1100, 450);
  screenIs(1024, 600);
  s().focus(a);
  insideScreen(win(a), 1024, 600);
});

test('resizeRect from the left and top keeps the opposite edge fixed', () => {
  const r = { x: 100, y: 100, w: 800, h: 600 };
  expect(resizeRect(r, 'w', 100, 0)).toEqual({ x: 200, y: 100, w: 700, h: 600 });
  expect(resizeRect(r, 'w', 700, 0)).toEqual({ x: 540, y: 100, w: 360, h: 600 });
  expect(resizeRect(r, 'w', -500, 0)).toEqual({ x: 0, y: 100, w: 900, h: 600 });
  expect(resizeRect(r, 'n', 0, -100)).toEqual({ x: 100, y: MENUBAR_H, w: 800, h: 656 });
  expect(resizeRect(r, 'se', 50, -500)).toEqual({ x: 100, y: 100, w: 850, h: 240 });
  expect(resizeRect(r, 'nw', 10, 10)).toEqual({ x: 110, y: 110, w: 790, h: 590 });
});

test('setBounds keeps the window inside the screen and above the minimum', () => {
  const a = s().open('a');
  s().setBounds(a, { x: -50, y: 0, w: 100, h: 5000 });
  expect(win(a)).toMatchObject({ x: 0, y: MENUBAR_H, w: 360, h: 1080 - MENUBAR_H });
});
