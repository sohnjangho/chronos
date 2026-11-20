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
  useDock.getState().unpin('chat', ['chat', 'schedule']);
  expect(useDock.getState().pinned).toEqual(['schedule']);
});
