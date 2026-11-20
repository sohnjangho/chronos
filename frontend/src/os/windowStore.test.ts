import { beforeEach, expect, test, vi } from 'vitest';
import { MENUBAR_H, useWindows, type Win } from './windowStore';

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
  vi.stubGlobal('innerWidth', 1280);
  vi.stubGlobal('innerHeight', 720);
  const a = s().open('a');
  expect(win(a).w).toBeLessThanOrEqual(1280);
  expect(win(a).y + win(a).h).toBeLessThanOrEqual(720);
});
