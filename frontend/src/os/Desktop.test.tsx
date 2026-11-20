import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { lazy } from 'react';
import { afterEach, beforeAll, beforeEach, expect, test, vi } from 'vitest';
import { registerPrograms } from '../programs';
import { json, signInAs, stubFetch } from '../test-helpers';
import Desktop from './Desktop';
import { register, type ProgramManifest } from './registry';
import { useApprovals } from './approvals';
import { useSession } from './session';
import { useWindows } from './windowStore';

const m = (id: string, over: Partial<ProgramManifest> = {}): ProgramManifest => ({
  id,
  name: id,
  icon: null,
  kind: 'system',
  defaultSize: { w: 600, h: 400 },
  component: lazy(() => import('./Placeholder')),
  ...over,
});

const menubar = () => screen.getByRole('banner');
const dock = () => screen.getByRole('navigation', { name: 'Dock' });
const dockIcon = (name: string) => within(dock()).getByRole('button', { name });
const systemMenu = async (item: string) => {
  await userEvent.click(within(menubar()).getByRole('button', { name: 'ChronOS 메뉴' }));
  await userEvent.click(screen.getByRole('menuitem', { name: item }));
};

beforeAll(() => registerPrograms());
beforeEach(() => {
  vi.stubGlobal('innerWidth', 1920);
  vi.stubGlobal('innerHeight', 1080);
  signInAs('admin');
  stubFetch({
    '/api/approvals/count': { pending: 0 },
    '/api/schedules': [],
  });
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  useWindows.getState().reset();
  useApprovals.setState({ pending: 0 });
  useSession.getState().logout();
});

test('menubar shows the active program name', async () => {
  render(<Desktop />);
  await userEvent.click(dockIcon('일정판'));
  expect(within(menubar()).getByText('일정판')).toBeVisible();
  expect(await screen.findByText('준비 중입니다.')).toBeVisible();
});

test('a program that fails to load does not break the desktop', async () => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
  register(m('broken', { name: '고장', component: lazy(() => Promise.reject(new Error('x'))) }));
  render(<Desktop />);
  await userEvent.click(dockIcon('일정판'));
  await userEvent.click(dockIcon('고장'));
  expect(await screen.findByText('이 프로그램을 열 수 없습니다')).toBeVisible();
  expect(dock()).toBeVisible();
  expect(within(screen.getByRole('dialog', { name: '일정판' })).getByText('준비 중입니다.')).toBeVisible();
});

test('a window is a labelled dialog with traffic lights and gets focus when it opens', async () => {
  render(<Desktop />);
  await userEvent.click(dockIcon('일정판'));
  const dialog = screen.getByRole('dialog', { name: '일정판' });
  expect(dialog).toHaveFocus();
  for (const name of ['닫기', '최소화', '확대']) {
    expect(within(dialog).getByRole('button', { name })).toBeInTheDocument();
  }
});

test('traffic lights minimize, maximize and close', async () => {
  render(<Desktop />);
  await userEvent.click(dockIcon('일정판'));
  const dialog = screen.getByRole('dialog', { name: '일정판' });
  await userEvent.click(within(dialog).getByRole('button', { name: '확대' }));
  expect(dialog).toHaveStyle({ left: '0px', top: '44px', width: '1920px' });
  await userEvent.click(within(dialog).getByRole('button', { name: '최소화' }));
  expect(dialog).not.toBeVisible();
  expect(within(menubar()).queryByText('일정판')).toBeNull();
  await userEvent.click(dockIcon('일정판'));
  expect(dialog).toBeVisible();
  await userEvent.click(within(dialog).getByRole('button', { name: '닫기' }));
  expect(screen.queryByRole('dialog', { name: '일정판' })).toBeNull();
});

test('dragging the title bar moves the window and a click raises it', async () => {
  render(<Desktop />);
  await userEvent.click(dockIcon('일정판'));
  await userEvent.click(dockIcon('질문지'));
  const sched = useWindows.getState().wins.find((w) => w.programId === 'schedule')!;
  const dialog = screen.getByRole('dialog', { name: '일정판' });
  fireEvent.pointerDown(within(dialog).getByText('일정판'), { clientX: 100, clientY: 100 });
  fireEvent.pointerMove(window, { clientX: 150, clientY: 130 });
  fireEvent.pointerUp(window);
  const moved = useWindows.getState().wins.find((w) => w.id === sched.id)!;
  expect(moved).toMatchObject({ x: sched.x + 50, y: sched.y + 30 });
  expect(useWindows.getState().activeProgramId()).toBe('schedule');
});

test('dragging the corner resizes the window', async () => {
  render(<Desktop />);
  await userEvent.click(dockIcon('탐색기'));
  const before = useWindows.getState().wins[0];
  const corner = screen.getByRole('dialog', { name: '탐색기' }).querySelector('[data-resize="se"]')!;
  fireEvent.pointerDown(corner, { clientX: 500, clientY: 500 });
  fireEvent.pointerMove(window, { clientX: 400, clientY: 450 });
  fireEvent.pointerUp(window);
  expect(useWindows.getState().wins[0]).toMatchObject({ w: before.w - 100, h: before.h - 50 });
});

test('dock shows running programs and admin-only programs only to admins', async () => {
  register(m('dev', { name: '개발 콘솔', adminOnly: true }));
  render(<Desktop />);
  expect(dockIcon('개발 콘솔')).toBeInTheDocument();
  await userEvent.click(dockIcon('일정판'));
  expect(dockIcon('일정판')).toHaveAttribute('data-running', 'true');
  expect(dockIcon('질문지')).toHaveAttribute('data-running', 'false');
  act(() => signInAs('user', '김민지'));
  expect(within(dock()).queryByRole('button', { name: '개발 콘솔' })).toBeNull();
});

test('program menus run with the active window id', async () => {
  const action = vi.fn();
  register(m('menu-test', { name: '메뉴 시험', menus: [{ label: '새로 고침', action }] }));
  render(<Desktop />);
  let id = '';
  act(() => {
    id = useWindows.getState().open('menu-test');
  });
  await userEvent.click(within(menubar()).getByRole('button', { name: '새로 고침' }));
  expect(action).toHaveBeenCalledWith(id);
});

test('ChronOS menu: 정보 shows the product and version', async () => {
  render(<Desktop />);
  await systemMenu('정보');
  const about = screen.getByRole('dialog', { name: 'ChronOS 정보' });
  expect(within(about).getByText('버전 0.1.0')).toBeVisible();
  await userEvent.click(within(about).getByRole('button', { name: '닫기' }));
  expect(screen.queryByRole('dialog', { name: 'ChronOS 정보' })).toBeNull();
});

test('ChronOS menu: 설정 opens settings', async () => {
  render(<Desktop />);
  await systemMenu('설정');
  expect(screen.getByRole('dialog', { name: '설정' })).toBeInTheDocument();
});

test('ChronOS menu closes with Escape', async () => {
  render(<Desktop />);
  await userEvent.click(within(menubar()).getByRole('button', { name: 'ChronOS 메뉴' }));
  expect(screen.getByRole('menu')).toBeInTheDocument();
  await userEvent.keyboard('{Escape}');
  expect(screen.queryByRole('menu')).toBeNull();
});

test('lock keeps windows and unlocks with the password of the current user', async () => {
  const fetch = stubFetch({
    '/api/approvals/count': { pending: 0 },
    '/api/schedules': [],
    'POST /api/auth/login': (init) =>
      JSON.parse(String(init?.body)).password === 'right'
        ? json(200, { token: 'tok2', user: { id: 1, name: '손장호', role: 'admin' } })
        : json(401, { code: 'bad_credentials', message: '아이디 또는 비밀번호가 맞지 않습니다.', detail: null }),
  });
  render(<Desktop />);
  await userEvent.click(dockIcon('일정판'));
  await systemMenu('잠금');
  const lock = screen.getByRole('dialog', { name: '잠금 화면' });
  await userEvent.type(within(lock).getByLabelText('비밀번호'), 'wrong{Enter}');
  expect(await within(lock).findByText('아이디 또는 비밀번호가 맞지 않습니다.')).toBeVisible();
  expect(useSession.getState().session).not.toBeNull();
  await userEvent.clear(within(lock).getByLabelText('비밀번호'));
  await userEvent.type(within(lock).getByLabelText('비밀번호'), 'right{Enter}');
  await vi.waitFor(() => expect(screen.queryByRole('dialog', { name: '잠금 화면' })).toBeNull());
  expect(useSession.getState().session?.token).toBe('tok2');
  expect(screen.getByRole('dialog', { name: '일정판' })).toBeInTheDocument();
  const loginCall = fetch.mock.calls.find(([url]) => url === '/api/auth/login')!;
  expect(JSON.parse(String(loginCall[1]?.body))).toMatchObject({ login_id: 'jhsohn' });
});
