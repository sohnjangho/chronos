import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { lazy } from 'react';
import { afterEach, beforeAll, beforeEach, expect, test, vi } from 'vitest';
import { registerPrograms } from '../programs';
import { json, signInAsDemo, stubFetch } from '../test-helpers';
import Desktop from './Desktop';
import { register, type ProgramManifest } from './registry';
import { useApprovals } from './approvals';
import { useSession } from './session';
import { useWindows } from './windowStore';
import { resetShellState } from './shellReset';

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
const dock = () => screen.getByRole('toolbar', { name: '프로그램 막대' });
const dockIcon = (name: string) => within(dock()).getByRole('button', { name: new RegExp(`^${name}(,|$)`) });
const systemMenu = async (item: string) => {
  await userEvent.click(within(menubar()).getByRole('button', { name: 'ChronOS 메뉴' }));
  await userEvent.click(screen.getByRole('menuitem', { name: item }));
};

beforeAll(() => registerPrograms());
beforeEach(() => {
  vi.stubGlobal('innerWidth', 1920);
  vi.stubGlobal('innerHeight', 1080);
  signInAsDemo('admin');
  stubFetch({
    '/api/approvals/count': { pending: 0 },
    '/api/schedules': [],
  });
});
afterEach(() => {
  resetShellState();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  useWindows.getState().reset();
  useApprovals.setState({ pending: 0 });
  useSession.getState().logout();
});

test('menubar shows the active program name', async () => {
  render(<Desktop />);
  await userEvent.click(dockIcon('스케줄'));
  expect(within(menubar()).getByText('스케줄')).toBeVisible();
  expect(await screen.findByText('메뉴바에서 일정을 고르세요.')).toBeVisible(); // 스케줄 화면(Task 16), 지금 일정 없음
});

test('a program that fails to load does not break the desktop', async () => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
  register(m('broken', { name: '고장', component: lazy(() => Promise.reject(new Error('x'))) }));
  render(<Desktop />);
  await userEvent.click(dockIcon('스케줄'));
  await userEvent.click(dockIcon('고장'));
  expect(await screen.findByText('이 프로그램을 열 수 없습니다')).toBeVisible();
  expect(dock()).toBeVisible();
  expect(within(screen.getByRole('dialog', { name: '스케줄' })).getByText('메뉴바에서 일정을 고르세요.')).toBeVisible();
});

test('a window is a labelled dialog with traffic lights and gets focus when it opens', async () => {
  render(<Desktop />);
  await userEvent.click(dockIcon('스케줄'));
  const dialog = screen.getByRole('dialog', { name: '스케줄' });
  expect(dialog).toHaveFocus();
  for (const name of ['닫기', '최소화', '확대']) {
    expect(within(dialog).getByRole('button', { name })).toBeInTheDocument();
  }
});

test('traffic lights minimize, maximize and close', async () => {
  render(<Desktop />);
  await userEvent.click(dockIcon('스케줄'));
  const dialog = screen.getByRole('dialog', { name: '스케줄' });
  await userEvent.click(within(dialog).getByRole('button', { name: '확대' }));
  expect(dialog).toHaveStyle({ left: '0px', top: '48px', width: '1920px', height: '1032px' });
  await userEvent.click(within(dialog).getByRole('button', { name: '최소화' }));
  expect(dialog).not.toBeVisible();
  expect(within(menubar()).queryByText('스케줄')).toBeNull();
  await userEvent.click(dockIcon('스케줄'));
  expect(dialog).toBeVisible();
  await userEvent.click(within(dialog).getByRole('button', { name: '닫기' }));
  expect(screen.queryByRole('dialog', { name: '스케줄' })).toBeNull();
});

test('dragging the title bar moves the window and a click raises it', async () => {
  render(<Desktop />);
  await userEvent.click(dockIcon('스케줄'));
  await userEvent.click(dockIcon('질문지'));
  const sched = useWindows.getState().wins.find((w) => w.programId === 'schedule-table')!;
  const dialog = screen.getByRole('dialog', { name: '스케줄' });
  fireEvent.pointerDown(within(dialog).getByText('스케줄'), { clientX: 100, clientY: 100 });
  fireEvent.pointerMove(window, { clientX: 150, clientY: 130, buttons: 1 });
  fireEvent.pointerUp(window);
  const moved = useWindows.getState().wins.find((w) => w.id === sched.id)!;
  expect(moved).toMatchObject({ x: sched.x + 50, y: sched.y + 30 });
  expect(useWindows.getState().activeProgramId()).toBe('schedule-table');
});

test('dragging the corner resizes the window', async () => {
  render(<Desktop />);
  await userEvent.click(dockIcon('탐색기'));
  const before = useWindows.getState().wins[0];
  const corner = screen.getByRole('dialog', { name: '탐색기' }).querySelector('[data-resize="se"]')!;
  fireEvent.pointerDown(corner, { clientX: 500, clientY: 500 });
  fireEvent.pointerMove(window, { clientX: 400, clientY: 450, buttons: 1 });
  fireEvent.pointerUp(window);
  expect(useWindows.getState().wins[0]).toMatchObject({ w: before.w - 100, h: before.h - 50 });
});

test('dock shows running programs and admin-only programs only to admins', async () => {
  register(m('dev', { name: '개발 콘솔', adminOnly: true }));
  render(<Desktop />);
  expect(dockIcon('개발 콘솔')).toBeInTheDocument();
  await userEvent.click(dockIcon('스케줄'));
  expect(dockIcon('스케줄')).toHaveAccessibleName('스케줄, 활성 창');
  expect(dockIcon('질문지')).toHaveAccessibleName('질문지');
  act(() => signInAsDemo('user', '김민지'));
  expect(within(dock()).queryByRole('button', { name: /^개발 콘솔/ })).toBeNull();
});

function menuProgram() {
  const refresh = vi.fn();
  const exportIt = vi.fn();
  const gantt = vi.fn();
  register(
    m('menu-test', {
      name: '메뉴 시험',
      menus: [
        {
          label: '파일',
          items: [
            { label: '새로 고침', action: refresh, shortcut: '⌘R' },
            { label: '내보내기', action: exportIt, disabled: true },
            { label: '닫기', action: vi.fn() },
          ],
        },
        { label: '보기', items: [{ label: '간트', action: gantt }] },
      ],
    }),
  );
  render(<Desktop />);
  let id = '';
  act(() => {
    id = useWindows.getState().open('menu-test');
  });
  return { id, refresh, exportIt, gantt };
}
const item = (name: string) => screen.getByRole('menuitem', { name });

test('program menus open as dropdowns and run an item with the window id', async () => {
  const { id, refresh } = menuProgram();
  await userEvent.click(within(menubar()).getByRole('button', { name: '파일' }));
  expect(screen.getByRole('menu', { name: '파일' })).toBeVisible();
  await userEvent.click(item('새로 고침'));
  expect(refresh).toHaveBeenCalledWith(id);
  expect(screen.queryByRole('menu')).toBeNull();
});

test('a disabled menu item does nothing', async () => {
  const { exportIt } = menuProgram();
  await userEvent.click(within(menubar()).getByRole('button', { name: '파일' }));
  expect(item('내보내기')).toBeDisabled();
  await userEvent.click(item('내보내기'));
  expect(exportIt).not.toHaveBeenCalled();
});

test('program menus work from the keyboard', async () => {
  const { id, gantt } = menuProgram();
  const file = within(menubar()).getByRole('button', { name: '파일' });
  file.focus();
  await userEvent.keyboard('{Enter}');
  expect(item('새로 고침')).toHaveFocus();
  await userEvent.keyboard('{ArrowDown}');
  expect(item('닫기')).toHaveFocus();
  await userEvent.keyboard('{ArrowDown}');
  expect(item('새로 고침')).toHaveFocus();
  await userEvent.keyboard('{ArrowUp}');
  expect(item('닫기')).toHaveFocus();
  await userEvent.keyboard('{ArrowRight}');
  expect(item('간트')).toHaveFocus();
  await userEvent.keyboard('{ArrowLeft}');
  expect(item('새로 고침')).toHaveFocus();
  await userEvent.keyboard('{Escape}');
  expect(screen.queryByRole('menu')).toBeNull();
  expect(file).toHaveFocus();
  await userEvent.keyboard(' ');
  expect(item('새로 고침')).toHaveFocus();
  await userEvent.keyboard('{Escape}{ArrowDown}');
  expect(item('새로 고침')).toHaveFocus();
  await userEvent.keyboard('{ArrowRight}{Enter}');
  expect(gantt).toHaveBeenCalledWith(id);
});

test('a click outside closes a menu', async () => {
  menuProgram();
  await userEvent.click(within(menubar()).getByRole('button', { name: '보기' }));
  expect(screen.getByRole('menu')).toBeVisible();
  await userEvent.click(document.body);
  expect(screen.queryByRole('menu')).toBeNull();
});

test('setTitle changes the window title while the menubar keeps the program name', async () => {
  render(<Desktop />);
  await userEvent.click(dockIcon('스케줄'));
  act(() => useWindows.getState().setTitle(useWindows.getState().wins[0].id, '스케줄 — 5층 사무동 신축'));
  const dialog = screen.getByRole('dialog', { name: '스케줄 — 5층 사무동 신축' });
  expect(within(dialog).getByText('스케줄 — 5층 사무동 신축')).toBeVisible();
  expect(within(menubar()).getByText('스케줄')).toBeVisible();
});

test('shrinking the browser keeps windows on screen, maximized ones included', async () => {
  render(<Desktop />);
  await userEvent.click(dockIcon('스케줄'));
  await userEvent.click(dockIcon('질문지'));
  const quest = screen.getByRole('dialog', { name: '질문지' });
  await userEvent.click(within(quest).getByRole('button', { name: '확대' }));
  vi.stubGlobal('innerWidth', 1280);
  vi.stubGlobal('innerHeight', 720);
  act(() => {
    window.dispatchEvent(new Event('resize'));
  });
  expect(quest).toHaveStyle({ width: '1280px', height: `${720 - 48}px` });
  const sched = screen.getByRole('dialog', { name: '스케줄' });
  expect(parseInt(sched.style.left) + parseInt(sched.style.width)).toBeLessThanOrEqual(1280);
  expect(parseInt(sched.style.top) + parseInt(sched.style.height)).toBeLessThanOrEqual(720);
});

test('a drag ends on pointercancel, on window blur and on a move without buttons', async () => {
  render(<Desktop />);
  await userEvent.click(dockIcon('탐색기'));
  const title = within(screen.getByRole('dialog', { name: '탐색기' })).getByText('탐색기');
  const pos = () => useWindows.getState().wins[0];
  const start = pos();
  const dragThen = (end: () => void) => {
    fireEvent.pointerDown(title, { clientX: 100, clientY: 100 });
    fireEvent.pointerMove(window, { clientX: 110, clientY: 110, buttons: 1 });
    end();
    fireEvent.pointerMove(window, { clientX: 300, clientY: 300, buttons: 1 });
  };
  dragThen(() => fireEvent.pointerCancel(window));
  expect(pos()).toMatchObject({ x: start.x + 10, y: start.y + 10 });
  dragThen(() => fireEvent.blur(window));
  expect(pos()).toMatchObject({ x: start.x + 20, y: start.y + 20 });
  dragThen(() => fireEvent.pointerMove(window, { clientX: 200, clientY: 200, buttons: 0 }));
  expect(pos()).toMatchObject({ x: start.x + 30, y: start.y + 30 });
});

test('closing a window mid-drag removes the drag listeners', async () => {
  render(<Desktop />);
  await userEvent.click(dockIcon('탐색기'));
  const title = within(screen.getByRole('dialog', { name: '탐색기' })).getByText('탐색기');
  fireEvent.pointerDown(title, { clientX: 100, clientY: 100 });
  const removed = vi.spyOn(window, 'removeEventListener');
  act(() => useWindows.getState().close(useWindows.getState().wins[0].id));
  expect(removed.mock.calls.map(([type]) => type)).toEqual(
    expect.arrayContaining(['pointermove', 'pointerup', 'pointercancel', 'blur']),
  );
});

test('all four edges and corners resize; the left edge keeps the right edge fixed', async () => {
  render(<Desktop />);
  await userEvent.click(dockIcon('탐색기'));
  const dialog = screen.getByRole('dialog', { name: '탐색기' });
  const edges = [...dialog.querySelectorAll('[data-resize]')].map((el) => el.getAttribute('data-resize'));
  expect(edges.sort()).toEqual(['e', 'n', 'ne', 'nw', 's', 'se', 'sw', 'w']);
  const before = useWindows.getState().wins[0];
  fireEvent.pointerDown(dialog.querySelector('[data-resize="w"]')!, { clientX: 500, clientY: 500 });
  fireEvent.pointerMove(window, { clientX: 600, clientY: 500, buttons: 1 });
  fireEvent.pointerUp(window);
  const after = useWindows.getState().wins[0];
  expect(after).toMatchObject({ x: before.x + 100, w: before.w - 100 });
  expect(after.x + after.w).toBe(before.x + before.w);
});

test('bringing a window to the front from the Dock moves focus into it', async () => {
  render(<Desktop />);
  await userEvent.click(dockIcon('스케줄'));
  await userEvent.click(dockIcon('질문지'));
  const sched = screen.getByRole('dialog', { name: '스케줄' });
  await userEvent.click(dockIcon('스케줄'));
  expect(sched).toHaveFocus();
  await userEvent.click(within(sched).getByRole('button', { name: '최소화' }));
  await userEvent.click(dockIcon('스케줄'));
  expect(sched).toHaveFocus();
});

test('tabbing into a background window does not steal focus from the focused control', async () => {
  render(<Desktop />);
  await userEvent.click(dockIcon('스케줄'));
  await userEvent.click(dockIcon('질문지'));
  const close = within(screen.getByRole('dialog', { name: '스케줄' })).getByRole('button', { name: '닫기' });
  act(() => close.focus());
  expect(useWindows.getState().activeProgramId()).toBe('schedule-table');
  expect(close).toHaveFocus();
});

test('ChronOS menu: ChronOS 정보 shows the product and version', async () => {
  render(<Desktop />);
  await systemMenu('ChronOS 정보');
  const about = screen.getByRole('dialog', { name: 'ChronOS 정보' });
  expect(within(about).getByText('버전 0.1.0')).toBeVisible();
  await userEvent.click(within(about).getByRole('button', { name: '닫기' }));
  expect(screen.queryByRole('dialog', { name: 'ChronOS 정보' })).toBeNull();
});

test('ChronOS menu: 설정 opens settings', async () => {
  render(<Desktop />);
  await systemMenu('설정…');
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
        ? json(200, { token: 'tok2', user: { id: 1, name: '김하늘', role: 'admin' } })
        : json(401, { code: 'bad_credentials', message: '아이디 또는 비밀번호가 맞지 않습니다.', detail: null }),
  });
  render(<Desktop />);
  await userEvent.click(dockIcon('스케줄'));
  await systemMenu('화면 잠금');
  const lock = screen.getByRole('dialog', { name: '잠금 화면' });
  await userEvent.type(within(lock).getByLabelText('비밀번호'), 'wrong{Enter}');
  expect(await within(lock).findByText('아이디 또는 비밀번호가 맞지 않습니다.')).toBeVisible();
  expect(useSession.getState().session).not.toBeNull();
  await userEvent.clear(within(lock).getByLabelText('비밀번호'));
  await userEvent.type(within(lock).getByLabelText('비밀번호'), 'right{Enter}');
  await vi.waitFor(() => expect(screen.queryByRole('dialog', { name: '잠금 화면' })).toBeNull());
  expect(useSession.getState().session?.token).toBe('tok2');
  expect(screen.getByRole('dialog', { name: '스케줄' })).toBeInTheDocument();
  const loginCall = fetch.mock.calls.find(([url]) => url === '/api/auth/login')!;
  expect(JSON.parse(String(loginCall[1]?.body))).toMatchObject({ login_id: 'demo-admin' });
});
