import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeAll, beforeEach, expect, test, vi } from 'vitest';
import { registerPrograms } from '../programs';
import { signInAsDemo, stubFetch } from '../test-helpers';
import { useApprovals } from './approvals';
import Desktop from './Desktop';
import Dock, { magnification } from './Dock';
import { useDock } from './dockStore';
import { useSession } from './session';
import { useShell } from './shell';
import { useWindows } from './windowStore';
import { resetShellState } from './shellReset';

const dock = () => screen.getByRole('toolbar', { name: '프로그램 막대' });
const icon = (name: string) => within(dock()).getByRole('button', { name: new RegExp(`^${name}(,|$)`) });
const order = () =>
  [...dock().querySelectorAll('[role=separator], button')].map((el) =>
    el.getAttribute('role') === 'separator' ? '|' : el.getAttribute('aria-label')!.split(',')[0],
  );
const openProgram = (id: string) => act(() => void useWindows.getState().open(id));
const reducedMotion = (on: boolean) =>
  vi.stubGlobal('matchMedia', (q: string) => ({ matches: on && q.includes('reduce'), media: q, addEventListener() {}, removeEventListener() {} }));

beforeAll(() => registerPrograms());
beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal('innerWidth', 1920);
  vi.stubGlobal('innerHeight', 1080);
  reducedMotion(false);
  signInAsDemo('admin');
  stubFetch({ '/api/approvals/count': { pending: 0 }, '/api/schedules': [] });
});
afterEach(() => {
  resetShellState();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  useWindows.getState().reset();
  useApprovals.setState({ pending: 0 });
  useShell.setState({ drawer: 'closed', dockRevealed: false });
  useDock.getState().load(null);
  useSession.getState().logout();
});

test('the Dock is a toolbar: 앱 목록 first, programs, a separator between system and work programs', () => {
  render(<Desktop />);
  expect(order()).toEqual(['앱 목록', '에이전트 대화', '질문지', '워크플로우', '승인함', '탐색기', '설정', '|', '일정판', '조건·규칙']);
  expect(icon('일정판')).not.toHaveAttribute('title');
});

test('roving focus: one tab stop, arrows wrap, Home and End', async () => {
  render(<Desktop />);
  const tabbable = within(dock()).getAllByRole('button').filter((b) => b.tabIndex === 0);
  expect(tabbable).toEqual([icon('앱 목록')]);
  icon('앱 목록').focus();
  await userEvent.keyboard('{ArrowRight}');
  expect(icon('에이전트 대화')).toHaveFocus();
  await userEvent.keyboard('{ArrowLeft}{ArrowLeft}');
  expect(icon('조건·규칙')).toHaveFocus();
  await userEvent.keyboard('{Home}');
  expect(icon('앱 목록')).toHaveFocus();
  await userEvent.keyboard('{End}');
  expect(icon('조건·규칙')).toHaveFocus();
  openProgram('schedule');
  expect(icon('일정판').tabIndex).toBe(0);
});

test('names carry running, active and badge state', () => {
  render(<Desktop />);
  openProgram('schedule');
  expect(icon('일정판')).toHaveAccessibleName('일정판, 활성 창');
  openProgram('chat');
  expect(icon('일정판')).toHaveAccessibleName('일정판, 실행 중');
  act(() => useApprovals.setState({ pending: 2 }));
  expect(icon('승인함')).toHaveAccessibleName('승인함, 승인 2');
  expect(icon('일정판').closest('.os-dock-item')!.querySelector('.os-dock-dot')).toHaveClass('is-on');
  expect(icon('질문지').closest('.os-dock-item')!.querySelector('.os-dock-dot')).not.toHaveClass('is-on');
});

test('the label is a bubble shown on hover or focus and hidden while the item menu is open', () => {
  render(<Desktop />);
  fireEvent.pointerEnter(icon('일정판'));
  expect(screen.getByRole('tooltip')).toHaveTextContent('일정판');
  fireEvent.pointerLeave(icon('일정판'));
  expect(screen.queryByRole('tooltip')).toBeNull();
  fireEvent.focus(icon('탐색기'));
  expect(screen.getByRole('tooltip')).toHaveTextContent('탐색기');
  fireEvent.contextMenu(icon('탐색기'));
  expect(screen.queryByRole('tooltip')).toBeNull();
});

test('앱 목록 opens the app drawer and its item menu has only 열기', async () => {
  render(<Desktop />);
  await userEvent.click(icon('앱 목록'));
  expect(useShell.getState().drawer).toBe('open');
  act(() => useShell.getState().setDrawer('closed'));
  fireEvent.contextMenu(icon('앱 목록'));
  expect(within(screen.getByRole('menu')).getAllByRole('menuitem').map((m) => m.textContent)).toEqual(['열기']);
});

test('item menu of a closed program: 열기, options with Dock에 유지 checked and Dock에서 제거', async () => {
  render(<Desktop />);
  fireEvent.contextMenu(icon('일정판'));
  const menu = screen.getByRole('menu', { name: '일정판' });
  expect(within(menu).getByText('옵션')).toBeInTheDocument();
  expect(within(menu).getByRole('menuitemcheckbox', { name: 'Dock에 유지' })).toHaveAttribute('aria-checked', 'true');
  expect(within(menu).getByRole('menuitem', { name: 'Dock에서 제거' })).toBeEnabled();
  expect(within(menu).getByRole('menuitem', { name: '열기' })).toHaveFocus();
  await userEvent.keyboard('{Escape}');
  expect(screen.queryByRole('menu')).toBeNull();
  expect(icon('일정판')).toHaveFocus();
  fireEvent.contextMenu(icon('일정판'));
  await userEvent.click(screen.getByRole('menuitem', { name: '열기' }));
  expect(useWindows.getState().activeProgramId()).toBe('schedule');
});

test('item menu of an open program lists its window, minimized marked, and 닫기', async () => {
  render(<Desktop />);
  openProgram('schedule');
  const id = useWindows.getState().wins[0].id;
  act(() => {
    useWindows.getState().setTitle(id, '일정판 — 5층');
    useWindows.getState().minimize(id);
  });
  fireEvent.contextMenu(icon('일정판'));
  await userEvent.click(screen.getByRole('menuitem', { name: '일정판 — 5층 (최소화)' }));
  expect(useWindows.getState().wins[0].minimized).toBe(false);
  fireEvent.contextMenu(icon('일정판'));
  await userEvent.click(screen.getByRole('menuitem', { name: '닫기' }));
  expect(useWindows.getState().wins).toEqual([]);
});

test('Shift+F10 opens the item menu on the focused item', async () => {
  render(<Desktop />);
  icon('탐색기').focus();
  await userEvent.keyboard('{Shift>}{F10}{/Shift}');
  expect(screen.getByRole('menu', { name: '탐색기' })).toBeVisible();
});

test('a long press opens the item menu without launching; moving more than 8px cancels', () => {
  vi.useFakeTimers();
  render(<Desktop />);
  fireEvent.pointerDown(icon('워크플로우'), { pointerType: 'touch', clientX: 100, clientY: 100 });
  act(() => vi.advanceTimersByTime(500));
  expect(screen.getByRole('menu', { name: '워크플로우' })).toBeVisible();
  fireEvent.pointerUp(icon('워크플로우'), { pointerType: 'touch' });
  fireEvent.click(icon('워크플로우'));
  expect(useWindows.getState().wins).toEqual([]);
  act(() => useShell.getState().setDrawer('closed'));
  fireEvent.keyDown(screen.getByRole('menu'), { key: 'Escape' });
  fireEvent.pointerDown(icon('탐색기'), { pointerType: 'touch', clientX: 100, clientY: 100 });
  fireEvent.pointerMove(icon('탐색기'), { pointerType: 'touch', clientX: 120, clientY: 100 });
  act(() => vi.advanceTimersByTime(600));
  expect(screen.queryByRole('menu')).toBeNull();
});

test('removing from the Dock persists per user; a running unpinned program shows after a separator until pinned', async () => {
  render(<Desktop />);
  fireEvent.contextMenu(icon('질문지'));
  await userEvent.click(screen.getByRole('menuitem', { name: 'Dock에서 제거' }));
  expect(order()).not.toContain('질문지');
  expect(JSON.parse(localStorage.getItem('chronos.dock.1')!)).not.toContain('questionnaire');
  openProgram('questionnaire');
  expect(order().slice(-2)).toEqual(['|', '질문지']);
  fireEvent.contextMenu(icon('질문지'));
  expect(screen.getByRole('menuitemcheckbox', { name: 'Dock에 유지' })).toHaveAttribute('aria-checked', 'false');
  expect(screen.getByRole('menuitem', { name: 'Dock에서 제거' })).toBeDisabled();
  await userEvent.click(screen.getByRole('menuitemcheckbox', { name: 'Dock에 유지' }));
  expect(JSON.parse(localStorage.getItem('chronos.dock.1')!).at(-1)).toBe('questionnaire');
  act(() => useDock.getState().load(2));
  expect(order()).toContain('질문지');
});

test('magnification follows a cosine curve up to 1.4x within 120px', () => {
  expect(magnification(0)).toBeCloseTo(1.4);
  expect(magnification(60)).toBeCloseTo(1.2);
  expect(magnification(120)).toBe(1);
  expect(magnification(500)).toBe(1);
});

function stubTileRects() {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
    const i = Number(this.dataset.dockIndex ?? -1);
    const left = 12 + i * 56;
    return { left, right: left + 48, top: 1000, bottom: 1048, width: 48, height: 48, x: left, y: 1000, toJSON() {} } as DOMRect;
  });
}
const tile = (name: string) => icon(name).querySelector<HTMLElement>('.os-dock-tile')!;

test('tiles grow toward the pointer and reset when it leaves', () => {
  render(<Desktop />);
  stubTileRects();
  const center = 12 + 3 * 56 + 24;
  fireEvent.pointerMove(dock(), { clientX: center, clientY: 1020, pointerType: 'mouse' });
  expect(tile('워크플로우').style.transform).toBe('scale(1.4)');
  const near = Number(/scale\(([\d.]+)\)/.exec(tile('질문지').style.transform)![1]);
  expect(near).toBeGreaterThan(1);
  expect(near).toBeLessThan(1.4);
  expect(tile('앱 목록').style.transform).toBe('scale(1)');
  fireEvent.pointerLeave(dock());
  expect(tile('워크플로우').style.transform).toBe('scale(1)');
});

test('reduced motion turns off magnification and the launch bounce', async () => {
  render(<Desktop />);
  stubTileRects();
  await userEvent.click(icon('일정판'));
  expect(icon('일정판').closest('.os-dock-item')).toHaveClass('is-launching');
  act(() => useWindows.getState().reset());
  reducedMotion(true);
  fireEvent.pointerMove(dock(), { clientX: 12 + 3 * 56 + 24, clientY: 1020, pointerType: 'mouse' });
  expect(tile('워크플로우').style.transform).toBe('');
  await userEvent.click(icon('탐색기'));
  expect(icon('탐색기').closest('.os-dock-item')).not.toHaveClass('is-launching');
});

test('a maximized window hides the Dock; the bottom strip and Ctrl+Alt+D reveal it, Escape hides it', () => {
  vi.useFakeTimers();
  render(<Desktop />);
  const wrap = () => dock().closest('.os-dock-wrap')!;
  openProgram('schedule');
  expect(wrap()).toHaveAttribute('data-hidden', 'false');
  act(() => useWindows.getState().toggleMaximize(useWindows.getState().wins[0].id));
  expect(wrap()).toHaveAttribute('data-hidden', 'true');
  fireEvent.pointerEnter(screen.getByTestId('dock-reveal'));
  act(() => vi.advanceTimersByTime(200));
  expect(wrap()).toHaveAttribute('data-hidden', 'false');
  fireEvent.keyDown(icon('일정판'), { key: 'Escape' });
  expect(wrap()).toHaveAttribute('data-hidden', 'true');
  fireEvent.keyDown(document.body, { code: 'KeyD', key: 'd', ctrlKey: true, altKey: true });
  expect(wrap()).toHaveAttribute('data-hidden', 'false');
  expect(icon('일정판')).toHaveFocus();
  fireEvent.keyDown(document.body, { code: 'KeyD', key: 'd', ctrlKey: true, altKey: true });
  expect(wrap()).toHaveAttribute('data-hidden', 'true');
});

test('the Dock clears the timers it starts when it goes away', () => {
  vi.useFakeTimers();
  // Dock 만 그린다(창·지연 로딩 없음). 그래서 남는 타이머는 모두 Dock 몫이다.
  const { unmount } = render(<Dock />);
  expect(vi.getTimerCount()).toBe(0);
  fireEvent.click(icon('일정판'));
  fireEvent.pointerDown(icon('탐색기'), { pointerType: 'touch', clientX: 1, clientY: 1 });
  expect(vi.getTimerCount()).toBe(2);
  unmount();
  expect(vi.getTimerCount()).toBe(0);
});

test('a Dock revealed from the bottom strip hides 0.8 s after the pointer leaves without entering it', () => {
  vi.useFakeTimers();
  render(<Desktop />);
  const wrap = () => dock().closest('.os-dock-wrap')!;
  openProgram('schedule');
  act(() => useWindows.getState().toggleMaximize(useWindows.getState().wins[0].id));
  const strip = screen.getByTestId('dock-reveal');
  fireEvent.pointerEnter(strip);
  act(() => vi.advanceTimersByTime(200));
  fireEvent.pointerLeave(strip);
  act(() => vi.advanceTimersByTime(799));
  expect(wrap()).toHaveAttribute('data-hidden', 'false');
  act(() => vi.advanceTimersByTime(1));
  expect(wrap()).toHaveAttribute('data-hidden', 'true');
  fireEvent.pointerEnter(strip);
  act(() => vi.advanceTimersByTime(200));
  fireEvent.pointerLeave(strip);
  fireEvent.pointerEnter(wrap());
  act(() => vi.advanceTimersByTime(2000));
  expect(wrap()).toHaveAttribute('data-hidden', 'false');
});

test('after Dock에서 제거 the focus moves to the neighbouring item', async () => {
  render(<Desktop />);
  fireEvent.contextMenu(icon('질문지'));
  await userEvent.click(screen.getByRole('menuitem', { name: 'Dock에서 제거' }));
  expect(icon('워크플로우')).toHaveFocus();
});
