// 스마트폰 전용 MobileShell(폭 <= 768px 자동 전환) 단위 시험.
import { act, cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeAll, beforeEach, expect, test, vi } from 'vitest';
import { registerPrograms } from '../programs';
import { signInAsDemo, stubFetch } from '../test-helpers';
import App from './App';
import { useApprovals } from './approvals';
import { useSession } from './session';
import { resetShellState } from './shellReset';
import { detectClientDevice, useDeviceMode } from './useIsMobile';
import { useWindows } from './windowStore';

beforeAll(() => registerPrograms());

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal('innerWidth', 390);
  vi.stubGlobal('innerHeight', 844);
  signInAsDemo('user', '김현장', 'field-user', 2);
  stubFetch({
    '/api/approvals/count': { pending: 3 },
    '/api/schedules': [],
    '/api/chat/sessions': [],
  });
});

afterEach(() => {
  cleanup();
  resetShellState();
  vi.unstubAllGlobals();
  useWindows.getState().reset();
  useApprovals.setState({ pending: 0 });
  useSession.getState().logout();
});

test('renders MobileShell on <=768px and switches tabs, schedule sub-tabs, and more grid by role', async () => {
  render(<App />);
  expect(screen.getByTestId('mobile-shell')).toBeVisible();
  expect(screen.queryByTestId('desktop-surface')).toBeNull();

  const nav = screen.getByRole('navigation', { name: '모바일 탐색' });
  expect(within(nav).getByRole('button', { name: /대화/ })).toBeVisible();
  expect(within(nav).getByRole('button', { name: /일정/ })).toBeVisible();
  expect(within(nav).getByRole('button', { name: /승인/ })).toBeVisible();
  expect(within(nav).getByRole('button', { name: /자료함/ })).toBeVisible();
  expect(within(nav).getByRole('button', { name: /전체/ })).toBeVisible();

  // 일정 탭 → 5개 세그먼트(스케줄·간트·공정률·지연·현장 점검)
  await userEvent.click(within(nav).getByRole('button', { name: /일정/ }));
  const sub = screen.getByRole('tablist', { name: '일정 보기 전환' });
  expect(within(sub).getByRole('tab', { name: '스케줄' })).toHaveAttribute('aria-selected', 'true');
  await userEvent.click(within(sub).getByRole('tab', { name: '공정률' }));
  expect(within(sub).getByRole('tab', { name: '공정률' })).toHaveAttribute('aria-selected', 'true');
  expect(within(sub).getByRole('tab', { name: '현장 점검' })).toBeVisible();

  // 전체 탭 → 일반 사용자는 개발 콘솔이 보이지 않는다
  await userEvent.click(within(nav).getByRole('button', { name: /전체/ }));
  const main = screen.getByRole('main');
  expect(within(main).getByRole('button', { name: '자료함' })).toBeVisible();
  expect(within(main).queryByRole('button', { name: '개발 콘솔' })).toBeNull();

  // useWindows.open('library') 호출 시 자료함 탭으로 자동 이동
  act(() => {
    useWindows.getState().open('library');
  });
  expect(within(nav).getByRole('button', { name: /자료함/ })).toHaveAttribute('aria-current', 'page');

  // 화면 형태 전환(태블릿 → PC 창)
  await userEvent.click(screen.getByRole('button', { name: '태블릿' }));
  expect(screen.getByTestId('mobile-shell')).toHaveAttribute('data-device', 'tablet');
  await userEvent.click(screen.getByRole('button', { name: 'PC 창' }));
  expect(screen.getByTestId('desktop-surface')).toBeVisible();
});

test('auto device detection classifies phone, tablet, and desktop by User-Agent, touch, and viewport', () => {
  expect(detectClientDevice(390, 844)).toBe('phone');
  expect(detectClientDevice(820, 1180)).toBe('tablet');
  expect(detectClientDevice(1024, 1366)).toBe('tablet');
  expect(detectClientDevice(1440, 900)).toBe('desktop');

  const origUa = navigator.userAgent;
  const origTouch = navigator.maxTouchPoints;
  Object.defineProperty(navigator, 'userAgent', { value: 'Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X)', configurable: true });
  expect(detectClientDevice(1280, 900)).toBe('tablet');

  Object.defineProperty(navigator, 'userAgent', { value: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)', configurable: true });
  expect(detectClientDevice(1280, 900)).toBe('phone');

  Object.defineProperty(navigator, 'userAgent', { value: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)', configurable: true });
  Object.defineProperty(navigator, 'maxTouchPoints', { value: 5, configurable: true });
  expect(detectClientDevice(1180, 820)).toBe('tablet');

  Object.defineProperty(navigator, 'userAgent', { value: origUa, configurable: true });
  Object.defineProperty(navigator, 'maxTouchPoints', { value: origTouch, configurable: true });
  useDeviceMode.getState().setMode('auto');
});
