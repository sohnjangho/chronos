// 고른 배경은 데스크톱·태블릿·스마트폰 셸 모두에 깔리는 한 장의 고정 층이다. 로그인 화면은 그대로.
import { act, render, screen } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, expect, test, vi } from 'vitest';
import { registerPrograms } from '../programs';
import { json, signInAsDemo, stubFetch } from '../test-helpers';
import App from './App';
import { useSession } from './session';
import { resetShellState } from './shellReset';
import { useTheme } from './theme';
import { useDeviceMode, type DeviceMode } from './useIsMobile';
import { useWallpaper } from './wallpaperStore';
import { useWindows } from './windowStore';

beforeAll(() => registerPrograms());
beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal('innerWidth', 1920);
  vi.stubGlobal('innerHeight', 1080);
  stubFetch({
    '/api/approvals/count': { pending: 0 },
    '/api/schedules': [],
    '/api/chat/sessions': [],
    '/api/me/ui-state': {},
    'PUT /api/me/ui-state/appearance': () => json(200, { mode: 'appearance', updated_at: new Date().toISOString() }),
  });
});
afterEach(() => {
  resetShellState();
  useSession.getState().logout();
  useWindows.getState().reset();
  vi.unstubAllGlobals();
});

for (const mode of ['desktop', 'tablet', 'phone'] as DeviceMode[]) {
  test(`${mode} 셸에 고른 배경 층이 하나 깔린다`, async () => {
    signInAsDemo('user');
    act(() => {
      useDeviceMode.getState().setMode(mode);
      useWallpaper.getState().choose('drafting-grid');
      useTheme.getState().setTheme('dark');
    });
    render(<App />);
    const layers = await screen.findAllByTestId('wallpaper-layer');
    expect(layers).toHaveLength(1);
    expect(layers[0].style.backgroundImage).toContain('drafting-grid-dark');
    expect(layers[0]).toHaveAttribute('aria-hidden', 'true');
    act(() => useWallpaper.getState().choose('default'));
    expect(screen.getByTestId('wallpaper-layer').style.backgroundImage).toBe('');
    act(() => useTheme.getState().setTheme('light'));
  });
}

test('로그인 화면에는 배경 층이 없다(영상 그대로)', () => {
  render(<App />);
  expect(screen.queryByTestId('wallpaper-layer')).toBeNull();
});
