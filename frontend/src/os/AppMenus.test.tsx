import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeAll, beforeEach, expect, test, vi } from 'vitest';
import { registerPrograms } from '../programs';
import { signInAs, stubFetch } from '../test-helpers';
import Desktop from './Desktop';
import { useSession } from './session';
import { useWindows } from './windowStore';
import { useZoom } from './zoom';

const menubar = () => screen.getByRole('banner');
const menuButton = (name: string | RegExp) => within(menubar()).getByRole('button', { name });
const item = (name: string | RegExp) => screen.getByRole('menuitem', { name });
const openMenu = async (name: string | RegExp) => userEvent.click(menuButton(name));
const key = (code: string, extra: Partial<KeyboardEventInit> = {}) =>
  fireEvent.keyDown(document.activeElement ?? document.body, { code, key: code, ctrlKey: true, altKey: true, ...extra });
const openProgram = (id: string) => act(() => void useWindows.getState().open(id));
const win = (programId: string) => useWindows.getState().wins.find((w) => w.programId === programId)!;

beforeAll(() => registerPrograms());
beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal('innerWidth', 1920);
  vi.stubGlobal('innerHeight', 1080);
  signInAs('admin');
  stubFetch({ '/api/approvals/count': { pending: 0 }, '/api/schedules': [] });
});
afterEach(() => {
  vi.unstubAllGlobals();
  useWindows.getState().reset();
  useZoom.getState().load(null);
  useSession.getState().logout();
});

test('the logo is an icon button whose menu has product items, a separator and lock/logout', async () => {
  render(<Desktop />);
  const logo = menuButton('ChronOS 메뉴');
  expect(logo).not.toHaveTextContent('ChronOS');
  await userEvent.click(logo);
  const menu = screen.getByRole('menu', { name: 'ChronOS 메뉴' });
  expect(within(menu).getAllByRole('menuitem').map((m) => m.textContent)).toEqual([
    'ChronOS 정보',
    '설정…',
    '앱 목록',
    '화면 잠금',
    '로그아웃',
  ]);
  expect(within(menu).getAllByRole('separator')).toHaveLength(1);
});

test('with no window the app menu is the product: ChronOS · 윈도우 · 도움말, hide and close disabled', async () => {
  render(<Desktop />);
  const names = within(menubar()).getAllByRole('button').map((b) => b.textContent);
  expect(names.slice(1, 4)).toEqual(['ChronOS', '윈도우', '도움말']);
  await openMenu('ChronOS');
  expect(item('ChronOS 정보')).toBeEnabled();
  expect(item('숨기기')).toBeDisabled();
  expect(item('닫기')).toBeDisabled();
});

test('the app name menu shows program info, hides and closes the active window', async () => {
  render(<Desktop />);
  openProgram('schedule');
  await openMenu('일정판');
  await userEvent.click(item('일정판 정보'));
  const info = screen.getByRole('dialog', { name: '일정판 정보' });
  expect(within(info).getByText('업무 프로그램')).toBeVisible();
  expect(within(info).getByText('schedule')).toBeVisible();
  await userEvent.click(within(info).getByRole('button', { name: '닫기' }));
  await openMenu('일정판');
  await userEvent.click(item('숨기기'));
  expect(win('schedule').minimized).toBe(true);
  openProgram('schedule');
  await openMenu('일정판');
  await userEvent.click(item('닫기'));
  expect(useWindows.getState().wins).toEqual([]);
});

test('clicking the empty desktop clears the active window', async () => {
  render(<Desktop />);
  openProgram('schedule');
  const dialog = screen.getByRole('dialog', { name: '일정판' });
  expect(dialog).toHaveClass('is-active');
  fireEvent.pointerDown(screen.getByTestId('desktop-surface'));
  expect(dialog).not.toHaveClass('is-active');
  expect(within(menubar()).getAllByRole('button')[1]).toHaveTextContent('ChronOS');
  fireEvent.pointerDown(dialog);
  expect(dialog).toHaveClass('is-active');
});

test('the 윈도우 menu has commands with shortcuts, disabled states and the window list', async () => {
  render(<Desktop />);
  await openMenu('윈도우');
  expect(item('최소화')).toBeDisabled();
  expect(item('좌우 분할')).toBeDisabled();
  expect(item('좌우 분할')).toHaveAttribute('aria-keyshortcuts', 'Control+Alt+S');
  expect(item('다음 창')).toBeDisabled();
  await userEvent.keyboard('{Escape}');
  openProgram('schedule');
  openProgram('chat');
  act(() => useWindows.getState().minimize(win('chat').id));
  await openMenu('윈도우');
  expect(item('모두 닫기')).toBeEnabled();
  expect(screen.getByRole('menu', { name: '윈도우' })).toHaveTextContent('에이전트 대화 (최소화)');
  await userEvent.click(item('에이전트 대화 (최소화)'));
  expect(win('chat').minimized).toBe(false);
  expect(useWindows.getState().activeProgramId()).toBe('chat');
});

test('arranging from the menu announces the result', async () => {
  render(<Desktop />);
  openProgram('schedule');
  openProgram('chat');
  await openMenu('윈도우');
  await userEvent.click(item('좌우 분할'));
  expect(screen.getByRole('status')).toHaveTextContent('창 2개를 좌우로 분할했습니다');
});

test('the 도움말 menu opens the keyboard shortcut list and product info', async () => {
  render(<Desktop />);
  await openMenu('도움말');
  await userEvent.click(item('키보드 단축키'));
  const dialog = screen.getByRole('dialog', { name: '키보드 단축키' });
  expect(within(dialog).getByText('Ctrl+Alt+S')).toBeVisible();
  expect(within(dialog).getByText('Ctrl+K')).toBeVisible();
  await userEvent.keyboard('{Escape}');
  await openMenu('도움말');
  await userEvent.click(item('ChronOS 정보'));
  expect(screen.getByRole('dialog', { name: 'ChronOS 정보' })).toBeVisible();
});

test('pointing at another menu name while a menu is open switches to it', async () => {
  render(<Desktop />);
  await openMenu('윈도우');
  fireEvent.pointerEnter(menuButton('도움말'));
  expect(screen.getByRole('menu', { name: '도움말' })).toBeVisible();
  expect(screen.queryByRole('menu', { name: '윈도우' })).toBeNull();
});

test('group titles are skipped by the arrow keys', async () => {
  render(<Desktop />);
  menuButton(/손장호/).focus();
  await userEvent.keyboard('{Enter}');
  expect(item('설정…')).toHaveFocus();
  await userEvent.keyboard('{ArrowDown}');
  expect(item('로그아웃')).toHaveFocus();
});

test('every program window gets a 보기 menu with zoom that is remembered per program', async () => {
  render(<Desktop />);
  openProgram('schedule');
  await openMenu('보기');
  expect(item('배율 100%')).toBeDisabled();
  expect(item('확대')).toHaveAttribute('aria-keyshortcuts', 'Control+Alt+=');
  await userEvent.click(item('확대'));
  expect(screen.getByRole('dialog', { name: '일정판' }).querySelector('.os-win-zoom')).toHaveAttribute('data-zoom', '110');
  key('Minus');
  key('Minus');
  expect(useZoom.getState().levels.schedule).toBe(90);
  key('Digit0');
  expect(useZoom.getState().levels.schedule).toBe(100);
  for (let i = 0; i < 12; i += 1) key('Equal');
  expect(useZoom.getState().levels.schedule).toBe(200);
  await openMenu('보기');
  expect(item('확대')).toBeDisabled();
  expect(JSON.parse(localStorage.getItem('chronos.zoom.1')!)).toEqual({ schedule: 200 });
});

test('zoom has a lower limit of 50%', () => {
  render(<Desktop />);
  openProgram('chat');
  for (let i = 0; i < 15; i += 1) key('Minus');
  expect(useZoom.getState().levels.chat).toBe(50);
});

test('the settings program keeps its own 보기 items and gets the zoom items appended', async () => {
  render(<Desktop />);
  openProgram('settings');
  await openMenu('보기');
  const menu = screen.getByRole('menu', { name: '보기' });
  expect(within(menu).getAllByRole('menuitem').length).toBeGreaterThan(4);
  expect(item('확대')).toBeInTheDocument();
  expect(within(menubar()).getAllByRole('button', { name: '보기' })).toHaveLength(1);
});

test('window shortcuts work, but not while typing or locked', () => {
  render(<Desktop />);
  openProgram('schedule');
  openProgram('chat');
  key('KeyM');
  expect(useWindows.getState().wins.every((w) => w.minimized)).toBe(true);
  openProgram('schedule');
  key('KeyW');
  expect(useWindows.getState().wins.map((w) => w.programId)).toEqual(['chat']);
  const input = document.createElement('input');
  document.body.append(input);
  input.focus();
  key('KeyQ');
  expect(useWindows.getState().wins).toHaveLength(1);
  input.remove();
  act(() => useSession.getState().lock());
  fireEvent.keyDown(document.body, { code: 'KeyQ', key: 'q', ctrlKey: true, altKey: true });
  expect(useWindows.getState().wins).toHaveLength(1);
  act(() => useSession.getState().signIn({ token: 'tok', loginId: 'jhsohn', user: { id: 1, name: '손장호', role: 'admin' } }));
  fireEvent.keyDown(document.body, { code: 'KeyQ', key: 'q', ctrlKey: true, altKey: true });
  expect(useWindows.getState().wins).toHaveLength(0);
});

test('Ctrl+` brings the next window forward and Ctrl+Alt+G arranges a grid', () => {
  render(<Desktop />);
  openProgram('schedule');
  openProgram('chat');
  fireEvent.keyDown(document.body, { code: 'Backquote', key: '`', ctrlKey: true });
  expect(useWindows.getState().activeProgramId()).toBe('schedule');
  fireEvent.keyDown(document.body, { code: 'KeyG', key: 'g', ctrlKey: true, altKey: true });
  expect(screen.getByRole('status')).toHaveTextContent('창 2개를 격자로 정렬했습니다');
});

test('program menu items can be grouped under titles, separated and checked', async () => {
  const { register } = await import('./registry');
  const { lazy } = await import('react');
  register({
    id: 'grouped',
    name: '묶음 시험',
    icon: null,
    kind: 'work',
    defaultSize: { w: 600, h: 400 },
    component: lazy(() => import('./Placeholder')),
    menus: [
      {
        label: '정렬',
        items: [
          { label: '이름순', group: '기준', checked: true, action: () => {} },
          { label: '날짜순', group: '기준', checked: false, action: () => {} },
          { label: '오름차순', group: '방향', action: () => {} },
          { label: '초기화', group: '방향', separatorBefore: true, action: () => {} },
        ],
      },
    ],
  });
  render(<Desktop />);
  openProgram('grouped');
  await openMenu('정렬');
  const menu = screen.getByRole('menu', { name: '정렬' });
  expect(within(menu).getByText('기준')).toBeInTheDocument();
  expect(within(menu).getByText('방향')).toBeInTheDocument();
  expect(within(menu).getAllByRole('separator')).toHaveLength(2);
  expect(within(menu).getByRole('menuitemcheckbox', { name: '이름순' })).toHaveAttribute('aria-checked', 'true');
  expect(within(menu).getByRole('menuitemcheckbox', { name: '날짜순' })).toHaveAttribute('aria-checked', 'false');
});

test('a menu closes when focus leaves its menu group, so two menus are never open at once', async () => {
  render(<Desktop />);
  await userEvent.click(menuButton('ChronOS 메뉴'));
  expect(screen.getByRole('menu', { name: 'ChronOS 메뉴' })).toBeVisible();
  act(() => menuButton('윈도우').focus());
  expect(screen.queryByRole('menu', { name: 'ChronOS 메뉴' })).toBeNull();
  await userEvent.keyboard('{Enter}');
  expect(screen.getAllByRole('menu')).toHaveLength(1);
});
