import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeAll, beforeEach, expect, test, vi } from 'vitest';
import { registerPrograms } from '../programs';
import { signInAsDemo, stubFetch } from '../test-helpers';
import Desktop from './Desktop';
import { useDock } from './dockStore';
import { useSession } from './session';
import { useShell } from './shell';
import { useWindows } from './windowStore';
import { resetShellState } from './shellReset';

const drawer = () => screen.getByRole('dialog', { name: '앱 목록' });
const dockNames = () =>
  within(screen.getByRole('toolbar', { name: '프로그램 막대' }))
    .getAllByRole('button')
    .map((b) => b.getAttribute('aria-label')!.split(',')[0]);
const orderNames = () => within(screen.getByRole('list', { name: 'Dock 차례' })).getAllByRole('listitem').map((li) => li.textContent);

beforeAll(() => registerPrograms());
beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal('innerWidth', 1920);
  vi.stubGlobal('innerHeight', 1080);
  signInAsDemo('user', '김민지');
  stubFetch({ '/api/approvals/count': { pending: 0 }, '/api/schedules': [] });
});
afterEach(() => {
  resetShellState();
  vi.unstubAllGlobals();
  useWindows.getState().reset();
  useShell.setState({ drawer: 'closed' });
  useDock.getState().load(null);
  useSession.getState().logout();
});

test('the logo menu opens the drawer with every program and a focused search box', async () => {
  render(<Desktop />);
  await userEvent.click(screen.getByRole('button', { name: 'ChronOS 메뉴' }));
  await userEvent.click(screen.getByRole('menuitem', { name: '앱 목록' }));
  expect(within(drawer()).getAllByRole('button', { name: /^.+ 열기$/ })).toHaveLength(17);
  const search = within(drawer()).getByRole('searchbox', { name: '프로그램 찾기' });
  expect(search).toHaveFocus();
  await userEvent.type(search, '스케줄');
  expect(within(drawer()).getAllByRole('button', { name: /^.+ 열기$/ }).map((b) => b.textContent)).toEqual(['스케줄']);
  await userEvent.keyboard('{Enter}');
  expect(useWindows.getState().activeProgramId()).toBe('schedule-table');
  expect(screen.queryByRole('dialog', { name: '앱 목록' })).toBeNull();
});

test('clicking a program opens it; Escape closes the drawer', async () => {
  render(<Desktop />);
  act(() => useShell.getState().setDrawer('open'));
  await userEvent.click(within(drawer()).getByRole('button', { name: '탐색기 열기' }));
  expect(useWindows.getState().activeProgramId()).toBe('explorer');
  act(() => useShell.getState().setDrawer('open'));
  await userEvent.keyboard('{Escape}');
  expect(screen.queryByRole('dialog', { name: '앱 목록' })).toBeNull();
});

test('edit mode adds and removes Dock programs and reorders them by drag or keyboard; saved per user', async () => {
  render(<Desktop />);
  act(() => useShell.getState().setDrawer('open'));
  await userEvent.click(within(drawer()).getByRole('button', { name: '편집' }));
  const keep = within(drawer()).getByRole('checkbox', { name: '질문지 Dock에 두기' });
  expect(keep).toBeChecked();
  await userEvent.click(keep);
  expect(dockNames()).not.toContain('질문지');
  expect(orderNames()).not.toContain('질문지');
  const item = (name: string) => within(screen.getByRole('list', { name: 'Dock 차례' })).getByText(name).closest('li')!;
  fireEvent.dragStart(item('스케줄'));
  fireEvent.dragOver(item('에이전트 대화'));
  fireEvent.drop(item('에이전트 대화'));
  expect(orderNames()[0]).toBe('스케줄');
  item('스케줄').focus();
  await userEvent.keyboard('{Alt>}{ArrowRight}{/Alt}');
  expect(orderNames().slice(0, 2)).toEqual(['에이전트 대화', '스케줄']);
  expect(item('스케줄')).toHaveFocus();
  expect(dockNames().slice(0, 3)).toEqual(['앱 목록', '에이전트 대화', '스케줄']);
  expect(JSON.parse(localStorage.getItem('chronos.dock.1')!).slice(0, 2)).toEqual(['chat', 'schedule-table']);
  await userEvent.click(within(drawer()).getByRole('checkbox', { name: '질문지 Dock에 두기' }));
  expect(dockNames().at(-1)).toBe('질문지');
  await userEvent.click(within(drawer()).getByRole('button', { name: '완료' }));
  expect(within(drawer()).queryByRole('list', { name: 'Dock 차례' })).toBeNull();
});

test('edit mode supports move/remove icon buttons and 기본 순서 복원', async () => {
  render(<Desktop />);
  act(() => useShell.getState().setDrawer('edit'));
  expect(screen.getByRole('button', { name: '기본 순서 복원' })).toBeDisabled();

  await userEvent.click(screen.getByRole('button', { name: '에이전트 대화 오른쪽으로 이동' }));
  expect(orderNames().slice(0, 2)).toEqual(['질문지', '에이전트 대화']);
  await userEvent.click(screen.getByRole('button', { name: '에이전트 대화 왼쪽으로 이동' }));
  expect(orderNames().slice(0, 2)).toEqual(['에이전트 대화', '질문지']);

  await userEvent.click(screen.getByRole('button', { name: '질문지 Dock에서 빼기' }));
  expect(orderNames()).not.toContain('질문지');
  expect(dockNames()).not.toContain('질문지');
  expect(screen.getByRole('button', { name: '기본 순서 복원' })).toBeEnabled();

  await userEvent.click(screen.getByRole('button', { name: '기본 순서 복원' }));
  expect(orderNames()).toContain('질문지');
  expect(dockNames()).toContain('질문지');
  expect(localStorage.getItem('chronos.dock.1')).toBeNull();
});

test('완료 closes the drawer when it was opened straight into edit mode (settings · Dock menu) (B3)', async () => {
  render(<Desktop />);
  act(() => useShell.getState().setDrawer('edit'));
  await userEvent.click(within(drawer()).getByRole('button', { name: '완료' }));
  expect(screen.queryByRole('dialog', { name: '앱 목록' })).toBeNull();
  expect(useShell.getState().drawer).toBe('closed');
});

test('an explicit 닫기 (✕) button closes the drawer in browse and edit mode (B3)', async () => {
  render(<Desktop />);
  act(() => useShell.getState().setDrawer('open'));
  await userEvent.click(within(drawer()).getByRole('button', { name: '닫기' }));
  expect(screen.queryByRole('dialog', { name: '앱 목록' })).toBeNull();
  act(() => useShell.getState().setDrawer('edit'));
  await userEvent.click(within(drawer()).getByRole('button', { name: '닫기' }));
  expect(screen.queryByRole('dialog', { name: '앱 목록' })).toBeNull();
});
