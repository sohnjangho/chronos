import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { lazy, useEffect } from 'react';
import { afterEach, beforeAll, beforeEach, expect, test, vi } from 'vitest';
import { registerPrograms } from '../programs';
import { signInAsDemo, stubFetch } from '../test-helpers';
import { setAgentViewPacing, setAgentWindowSync, useAgentView } from './agentView';
import { useApprovals } from './approvals';
import Desktop from './Desktop';
import { register } from './registry';
import { useSession } from './session';
import { resetShellState } from './shellReset';
import { setWindowMotion } from './windowMotion';
import { useWindows } from './windowStore';

/** 창 움직임 시험: 움직임 스위치를 켜고, jsdom 에 없는 Element.animate 를 기록하는 대역으로 바꾼다. */
interface Played {
  el: Element;
  frames: Keyframe[];
  options: KeyframeAnimationOptions;
}
let played: Played[] = [];
const playedOn = (el: Element) => played.filter((p) => p.el === el);
const lastOn = (el: Element) => playedOn(el).at(-1)!;

const dock = () => screen.getByRole('toolbar', { name: '프로그램 막대' });
const dockIcon = (name: string) => within(dock()).getByRole('button', { name: new RegExp(`^${name}(,|$)`) });
const tileOf = (name: string) => dockIcon(name).querySelector<HTMLElement>('.os-dock-tile')!;
const dialog = (name: string) => screen.getByRole('dialog', { name });
const light = (name: string, d: HTMLElement) => within(d).getByRole('button', { name });
/** 진짜 시계로 움직임이 끝나기를 기다린다(store 가 시간이 지나면 움직임을 걷는다). */
const settle = (ms: number) => act(() => new Promise<void>((r) => setTimeout(r, ms)));
const reducedMotion = (on: boolean) =>
  vi.stubGlobal('matchMedia', (q: string) => ({ matches: on && q.includes('reduce'), media: q, addEventListener() {}, removeEventListener() {} }));

/** Dock 타일 i 번은 (500 + 64i, 1003) 의 48×48. 가운데는 (524 + 64i, 1027). */
const TILE_TOP = 1003;
const iconCentre = (name: string) => ({ x: 524 + 64 * Number(tileOf(name).dataset.dockIndex), y: TILE_TOP + 24 });

beforeAll(() => registerPrograms());
beforeEach(() => {
  played = [];
  Object.defineProperty(Element.prototype, 'animate', {
    configurable: true,
    writable: true,
    value: function (this: Element, frames: Keyframe[], options: KeyframeAnimationOptions) {
      played.push({ el: this, frames, options });
      return { cancel() {} } as unknown as Animation;
    },
  });
  vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function (this: Element) {
    const i = (this as HTMLElement).dataset?.dockIndex;
    const left = i === undefined ? 0 : 500 + 64 * Number(i);
    const size = i === undefined ? 0 : 48;
    const top = i === undefined ? 0 : TILE_TOP;
    return { left, top, width: size, height: size, right: left + size, bottom: top + size, x: left, y: top, toJSON() {} } as DOMRect;
  });
  setWindowMotion(true);
  vi.stubGlobal('innerWidth', 1920);
  vi.stubGlobal('innerHeight', 1080);
  signInAsDemo('admin');
  stubFetch({ '/api/approvals/count': { pending: 0 }, '/api/schedules': [] });
});
afterEach(() => {
  resetShellState();
  setAgentWindowSync(false);
  setWindowMotion(false);
  delete (Element.prototype as { animate?: unknown }).animate;
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  useWindows.getState().reset();
  useApprovals.setState({ pending: 0 });
  useSession.getState().logout();
});

test('opening from the Dock grows the window out of its Dock icon, then the motion clears', async () => {
  render(<Desktop />);
  await userEvent.click(dockIcon('스케줄'));
  const d = dialog('스케줄');
  const w = useWindows.getState().wins[0];
  const icon = iconCentre('스케줄');
  expect(d).toHaveAttribute('data-motion', 'open');
  expect(lastOn(d).frames[0]).toMatchObject({ transform: 'scale(0.6)', opacity: 0, transformOrigin: `${icon.x - w.x}px ${icon.y - w.y}px` });
  expect(lastOn(d).frames.at(-1)).toMatchObject({ transform: 'scale(1)', opacity: 1 });
  expect(lastOn(d).options).toMatchObject({ duration: 220 });
  await settle(260);
  expect(d).not.toHaveAttribute('data-motion');
});

test('a window opened from elsewhere (drawer, search, another window) grows from the bottom centre', () => {
  render(<Desktop />);
  act(() => void useWindows.getState().open('schedule-table'));
  const d = dialog('스케줄');
  const w = useWindows.getState().wins[0];
  expect(d).toHaveAttribute('data-motion', 'open');
  expect(lastOn(d).frames[0]).toMatchObject({ transformOrigin: `${960 - w.x}px ${1080 - w.y}px` });
});

test('bringing an already open window forward plays no motion', async () => {
  render(<Desktop />);
  await userEvent.click(dockIcon('스케줄'));
  await userEvent.click(dockIcon('질문지'));
  await settle(260);
  const before = played.length;
  await userEvent.click(dockIcon('스케줄'));
  expect(useWindows.getState().activeProgramId()).toBe('schedule-table');
  expect(dialog('스케줄')).not.toHaveAttribute('data-motion');
  expect(played).toHaveLength(before);
});

test('closing fades the window out where it is, blocks clicks meanwhile and removes it after the motion', async () => {
  render(<Desktop />);
  await userEvent.click(dockIcon('스케줄'));
  await settle(260);
  const d = dialog('스케줄');
  await userEvent.click(light('닫기', d));
  expect(d).toHaveAttribute('data-motion', 'close');
  expect(d).toHaveAttribute('inert');
  expect(lastOn(d).frames).toEqual([
    { transform: 'scale(1)', opacity: 1 },
    { transform: 'scale(0.92)', opacity: 0 },
  ]);
  expect(lastOn(d).options).toMatchObject({ duration: 160 });
  fireEvent.pointerDown(d);
  expect(useWindows.getState().activeProgramId()).toBeNull();
  expect(useWindows.getState().wins).toHaveLength(1);
  await settle(200);
  expect(d).not.toBeInTheDocument();
  expect(useWindows.getState().wins).toEqual([]);
});

test('minimizing shrinks the window into its Dock icon and hides it after the motion; the Dock icon brings it back in reverse', async () => {
  render(<Desktop />);
  await userEvent.click(dockIcon('스케줄'));
  await settle(260);
  const d = dialog('스케줄');
  const icon = iconCentre('스케줄');
  await userEvent.click(light('최소화', d));
  expect(useWindows.getState().wins[0].minimized).toBe(true);
  expect(d).toBeVisible();
  expect(d).toHaveAttribute('data-motion', 'minimize');
  expect(d).toHaveAttribute('inert');
  const min = lastOn(d);
  // 스케줄 1600×900 @ (24, 68): 48/1600 = 0.03 → 48×27 상자의 가운데가 아이콘 가운데
  expect(min.frames.at(-1)).toMatchObject({ transform: `translate(${icon.x - 24 - 24}px, ${icon.y - 68 - 13.5}px) scale(0.03)`, opacity: 0 });
  expect(min.options).toMatchObject({ duration: 260 });
  fireEvent.pointerDown(d); // 줄어드는 창을 눌러도 되살아나지 않는다
  expect(useWindows.getState().wins[0].minimized).toBe(true);
  await settle(300);
  expect(d).not.toBeVisible();
  expect(d).not.toHaveAttribute('data-motion');

  await userEvent.click(dockIcon('스케줄'));
  expect(d).toBeVisible();
  expect(d).toHaveAttribute('data-motion', 'restore');
  expect(d).not.toHaveAttribute('inert');
  expect(lastOn(d).frames).toEqual(min.frames);
  expect(lastOn(d).options).toMatchObject({ duration: 260, direction: 'reverse' });
  await settle(300);
  expect(d).not.toHaveAttribute('data-motion');
});

test('maximize and restore move the frame smoothly from where it was', async () => {
  render(<Desktop />);
  await userEvent.click(dockIcon('스케줄'));
  await settle(260);
  const d = dialog('스케줄');
  await userEvent.click(light('확대', d));
  expect(d).toHaveStyle({ left: '0px', top: '48px', width: '1920px', height: '1032px' });
  expect(d).toHaveAttribute('data-motion', 'zoom');
  // 1600×900 @ (24, 68) → 1920×1032 @ (0, 48)
  expect(lastOn(d).frames[0]).toEqual({ transformOrigin: '0px 0px', transform: 'translate(24px, 20px) scale(0.8333, 0.8721)' });
  expect(lastOn(d).options).toMatchObject({ duration: 200 });
  await settle(240);
  expect(d).not.toHaveAttribute('data-motion');
  fireEvent.doubleClick(d.querySelector('.os-win-bar')!);
  expect(d).toHaveStyle({ left: '24px', top: '68px', width: '1600px', height: '900px' });
  expect(d).toHaveAttribute('data-motion', 'zoom');
  expect(lastOn(d).frames[0]).toEqual({ transformOrigin: '0px 0px', transform: 'translate(-24px, -20px) scale(1.2, 1.1467)' });
});

test('dragging and resizing play no motion', async () => {
  render(<Desktop />);
  await userEvent.click(dockIcon('탐색기'));
  await settle(260);
  const d = dialog('탐색기');
  const before = played.length;
  fireEvent.pointerDown(d.querySelector('.os-win-bar')!, { clientX: 300, clientY: 100 });
  fireEvent.pointerMove(window, { clientX: 350, clientY: 140, buttons: 1 });
  fireEvent.pointerUp(window);
  fireEvent.pointerDown(d.querySelector('[data-resize="se"]')!, { clientX: 500, clientY: 500 });
  fireEvent.pointerMove(window, { clientX: 450, clientY: 460, buttons: 1 });
  fireEvent.pointerUp(window);
  expect(d).not.toHaveAttribute('data-motion');
  expect(played).toHaveLength(before);
});

test('with reduced motion every change is immediate and nothing animates', async () => {
  reducedMotion(true);
  render(<Desktop />);
  await userEvent.click(dockIcon('스케줄'));
  const d = dialog('스케줄');
  expect(d).not.toHaveAttribute('data-motion');
  await userEvent.click(light('최소화', d));
  expect(d).not.toBeVisible();
  await userEvent.click(dockIcon('스케줄'));
  expect(d).toBeVisible();
  await userEvent.click(light('확대', d));
  expect(d).not.toHaveAttribute('data-motion');
  await userEvent.click(light('닫기', d));
  expect(d).not.toBeInTheDocument();
  expect(played).toEqual([]);
});

test('the program inside a window is not remounted by any motion', async () => {
  let mounts = 0;
  function Counter() {
    useEffect(() => {
      mounts += 1;
    }, []);
    return <p>세는 화면</p>;
  }
  register({ id: 'counter', name: '세기', icon: null, kind: 'work', defaultSize: { w: 600, h: 400 }, component: lazy(async () => ({ default: Counter })) });
  render(<Desktop />);
  await userEvent.click(dockIcon('세기'));
  expect(await screen.findByText('세는 화면')).toBeInTheDocument();
  const d = dialog('세기');
  await settle(260);
  await userEvent.click(light('최소화', d));
  await settle(300);
  await userEvent.click(dockIcon('세기'));
  await settle(300);
  await userEvent.click(light('확대', d));
  await settle(240);
  await userEvent.click(light('확대', d));
  await settle(240);
  expect(playedOn(d).length).toBeGreaterThanOrEqual(5);
  expect(mounts).toBe(1);
});

test('Computer Use shows top-bar badge, slim workflow ribbon, and stage window without auto-opening full workflow window', async () => {
  setAgentWindowSync(true);
  render(<Desktop />);
  act(() => {
    useAgentView.getState().onToolStart({ run_id: 9, n: 1, call_id: 'c1', tool: 'calc.cpm', program: 'cpm', arguments: '{"schedule_id":1}' });
  });
  expect(screen.queryByRole('dialog', { name: '워크플로우' })).toBeNull();
  const ribbon = screen.getByRole('region', { name: '워크플로우 진행 상황' });
  expect(ribbon).toHaveTextContent('진행 중');
  expect(ribbon).toHaveTextContent('1. 주공정(CPM) 계산');
  expect(screen.getByRole('button', { name: 'Computer-Use 상태' })).toHaveTextContent('Computer-Use');

  const cpm = dialog('CPM');
  expect(cpm).toHaveAttribute('data-motion', 'stage');
  expect(cpm).toHaveClass('is-agent-focus');
  expect(within(cpm).getByRole('status', { name: '에이전트 실시간 작업' })).toHaveTextContent('Computer Use1단계 실행 중 · 주공정(CPM) 계산');

  act(() => {
    useAgentView.getState().onToolEnd({ run_id: 9, n: 1, call_id: 'c1', tool: 'calc.cpm', ok: true, ms: 40 });
    useAgentView.getState().onTurnDone();
  });
  expect(useAgentView.getState().focus.active).toBe(false);
  expect(screen.getByRole('region', { name: '워크플로우 진행 상황' })).toHaveTextContent('완료');

  useAgentView.getState().setMode('workflow');
  act(() => {
    useAgentView.getState().onToolStart({ run_id: 10, n: 1, call_id: 'c2', tool: 'calc.cpm', program: 'cpm', arguments: '{"schedule_id":1}' });
  });
  expect(dialog('워크플로우')).toBeVisible();
});

test('workflow ribbon auto-collapses after 1.8s when pacing is enabled', async () => {
  vi.useFakeTimers();
  setAgentWindowSync(true);
  setAgentViewPacing(true);
  try {
    render(<Desktop />);
    act(() => {
      useAgentView.getState().onToolStart({ run_id: 12, n: 1, call_id: 'c1', tool: 'calc.cpm', program: 'cpm', arguments: '{"schedule_id":1}' });
    });
    expect(screen.getByRole('region', { name: '워크플로우 진행 상황' })).toBeVisible();
    act(() => {
      useAgentView.getState().onToolEnd({ run_id: 12, n: 1, call_id: 'c1', tool: 'calc.cpm', ok: true, ms: 20 });
      useAgentView.getState().onTurnDone();
    });
    expect(screen.getByRole('region', { name: '워크플로우 진행 상황' })).toHaveTextContent('완료');
    await act(() => vi.advanceTimersByTimeAsync(1900));
    expect(screen.queryByRole('region', { name: '워크플로우 진행 상황' })).toBeNull();
    expect(screen.getByRole('button', { name: '워크플로우 #12 완료' })).toBeVisible();
  } finally {
    setAgentViewPacing(false);
    vi.useRealTimers();
  }
});
