// 시스템 진단: 읽기만 하는 한 줄 「지금 접속 중 n명 · 기기 n대」(누가인지는 설정 → 계정). 예전 서버(칸 없음)는 그리지 않는다.
import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import DevConsole from './DevConsole';
import { mockHealth, setup } from './testKit';

beforeEach(() => {
  localStorage.clear();
  setup();
});
afterEach(() => vi.unstubAllGlobals());

test('the health tab shows how many people and devices are online now', async () => {
  mockHealth({ presence: { online_users: 2, online_devices: 3 } });
  render(<DevConsole windowId="w1" params={{ tab: 'health' }} />);
  expect(await screen.findByText('지금 접속 중 2명 · 기기 3대')).toBeVisible();
  expect(screen.queryByRole('button', { name: /로그아웃/ })).toBeNull();
});

test('an older server without the presence field shows no line', async () => {
  render(<DevConsole windowId="w1" params={{ tab: 'health' }} />);
  await screen.findByRole('region', { name: '핵심 인프라 진단' });
  expect(screen.queryByText(/지금 접속 중/)).toBeNull();
});
