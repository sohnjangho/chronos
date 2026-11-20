import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { useDock } from './dockStore';
import { useTheme } from './theme';
import { useZoom } from './zoom';

beforeEach(() => localStorage.clear());
afterEach(() => {
  vi.restoreAllMocks();
  useZoom.getState().load(null);
  useTheme.getState().load(null);
  useDock.getState().load(null);
});

test('stored zoom levels outside the menu steps are dropped (100%)', () => {
  localStorage.setItem('chronos.zoom.1', JSON.stringify({ schedule: 33, chat: 'x', explorer: 150, settings: 999, workflow: 67 }));
  useZoom.getState().load(1);
  expect(useZoom.getState().levels).toEqual({ explorer: 150, workflow: 67 });
  localStorage.setItem('chronos.zoom.1', '[1,2]');
  useZoom.getState().load(1);
  expect(useZoom.getState().levels).toEqual({});
});

test('theme, Dock and zoom work in memory when storage throws', () => {
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
    throw new Error('denied');
  });
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new Error('denied');
  });
  useTheme.getState().load(1);
  expect(useTheme.getState().theme).toBe('light');
  useTheme.getState().toggle();
  expect(document.documentElement).toHaveAttribute('data-theme', 'dark');
  useZoom.getState().load(1);
  useZoom.getState().zoomIn('schedule');
  expect(useZoom.getState().levels.schedule).toBe(110);
  useDock.getState().load(1);
  useDock.getState().unpin('chat', ['chat', 'schedule-table']);
  expect(useDock.getState().pinned).toEqual(['schedule-table']);
});

// 일정판(schedule)은 스케줄·간트차트·CPM·공정률로 나뉘었다. 저장된 Dock 차례의 그 자리에 넷이 들어간다(이미 있는 것은 그대로).
test('a stored Dock order with the old schedule board gets its four tool programs in that place, once', () => {
  localStorage.setItem('chronos.dock.1', JSON.stringify(['chat', 'schedule', 'conditions', 'gantt']));
  useDock.getState().load(1);
  const migrated = ['chat', 'schedule-table', 'cpm', 'progress', 'conditions', 'gantt'];
  expect(useDock.getState().pinned).toEqual(migrated);
  expect(JSON.parse(localStorage.getItem('chronos.dock.1')!)).toEqual(migrated);
  useDock.getState().load(1);
  expect(useDock.getState().pinned).toEqual(migrated);
  localStorage.setItem('chronos.dock.2', JSON.stringify(['chat', 'conditions']));
  useDock.getState().load(2);
  expect(useDock.getState().pinned).toEqual(['chat', 'conditions']);
});
