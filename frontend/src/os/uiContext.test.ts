import { lazy } from 'react';
import { beforeEach, expect, test, vi } from 'vitest';
import { register } from './registry';
import { resetShellState } from './shellReset';
import { frontVisibleWindow, useUiContext } from './uiContext';
import { useWindows, type Win } from './windowStore';

const s = () => useUiContext.getState();
const win = (id: string, programId: string, z: number, more: Partial<Win> = {}): Win => ({
  id, programId, title: programId, x: 0, y: 48, w: 600, h: 400, z, minimized: false, maximized: false, ...more,
});

beforeEach(() => {
  vi.stubGlobal('innerWidth', 1920);
  vi.stubGlobal('innerHeight', 1080);
  useWindows.getState().reset();
  s().reset();
  for (const id of ['schedule', 'chat']) register({ id, name: id, icon: null, kind: 'work', defaultSize: { w: 600, h: 400 }, component: lazy(() => import('./Placeholder')) });
});

test('a window publishes its context and clears it', () => {
  s().publish('w2', { program: 'schedule', schedule_id: 1, selected_activity: 'A2020' });
  expect(s().byWindow.w2).toEqual({ program: 'schedule', schedule_id: 1, selected_activity: 'A2020' });
  s().publish('w2', { program: 'schedule', schedule_id: 1, selected_activity: null });
  expect(s().byWindow.w2.selected_activity).toBeNull();
  s().clear('w2');
  expect(s().byWindow).toEqual({});
  s().clear('w2');
  expect(s().byWindow).toEqual({});
});

test('closing a window drops what it published; other windows keep theirs', () => {
  const a = useWindows.getState().open('schedule');
  const b = useWindows.getState().open('chat');
  s().publish(a, { program: 'schedule', schedule_id: 1 });
  s().publish(b, { program: 'chat' });
  useWindows.getState().close(a);
  expect(Object.keys(s().byWindow)).toEqual([b]);
  useWindows.getState().closeAll();
  expect(s().byWindow).toEqual({});
});

test('resetShellState forgets every published context', () => {
  const a = useWindows.getState().open('schedule');
  s().publish(a, { program: 'schedule', schedule_id: 1 });
  resetShellState();
  expect(s().byWindow).toEqual({});
});

test('frontVisibleWindow skips the asking program and minimized windows; a maximized asker hides the rest', () => {
  const chat = win('w1', 'chat', 5);
  const schedule = win('w2', 'schedule', 3);
  const settings = win('w3', 'settings', 4, { minimized: true });
  expect(frontVisibleWindow([chat, schedule, settings], 'chat')?.id).toBe('w2');
  expect(frontVisibleWindow([{ ...chat, maximized: true }, schedule], 'chat')).toBeNull();
  expect(frontVisibleWindow([chat, { ...schedule, maximized: true, z: 9 }], 'chat')?.id).toBe('w2');
  expect(frontVisibleWindow([chat], 'chat')).toBeNull();
});
