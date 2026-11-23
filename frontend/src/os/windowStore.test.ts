import { lazy } from 'react';
import { signInAsDemo } from '../test-helpers';
import { useSession } from './session';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { register } from './registry';
import { setWindowMotion } from './windowMotion';
import { activeWindow, ARRANGE_GAP, DOCK_RESERVE, MENUBAR_H, RIBBON_H, resizeRect, useWindows, workArea, type Win } from './windowStore';
import { useCurrentSchedule } from './currentSchedule';

const program = (id: string, w: number, h: number) =>
  register({ id, name: id, icon: null, kind: 'work', defaultSize: { w, h }, component: lazy(() => import('./Placeholder')) });
const screenIs = (w: number, h: number) => {
  vi.stubGlobal('innerWidth', w);
  vi.stubGlobal('innerHeight', h);
};
const insideScreen = (w: Win, sw: number, sh: number) => {
  expect(w.x).toBeGreaterThanOrEqual(0);
  expect(w.y).toBeGreaterThanOrEqual(MENUBAR_H);
  expect(w.x + w.w).toBeLessThanOrEqual(sw);
  expect(w.y + w.h).toBeLessThanOrEqual(sh);
};

const s = () => useWindows.getState();
const win = (id: string): Win => s().wins.find((w) => w.id === id)!;
const top = (): Win => [...s().wins].sort((a, b) => b.z - a.z)[0];

beforeEach(() => {
  vi.stubGlobal('innerWidth', 1920);
  vi.stubGlobal('innerHeight', 1080);
  s().reset();
});

test('open twice focuses the same window', () => {
  const a = s().open('schedule-table');
  s().open('chat');
  const b = s().open('schedule-table', { activity: 'A2020' });
  expect(b).toBe(a);
  expect(top().id).toBe(a);
  expect(win(a).params).toEqual({ activity: 'A2020' });
});

// 일정판(schedule)은 넷으로 나뉘었다. 옛 대화 기록의 open_window·옛 단추가 부르는 open('schedule', …)은 맞는 프로그램을 연다.
test('the old schedule board id opens the matching tool program', () => {
  const table = s().open('schedule', { id: '1' });
  expect(win(table)).toMatchObject({ programId: 'schedule-table', params: { id: '1' } });
  const gantt = s().open('schedule', { id: '1', tab: 'gantt' });
  expect(win(gantt)).toMatchObject({ programId: 'gantt', params: { id: '1' } });
  expect(win(s().open('schedule', { tab: 'cpm' })).programId).toBe('cpm');
  expect(win(s().open('schedule', { tab: 'progress' })).programId).toBe('progress');
  expect(s().open('schedule', { tab: 'table', activity: 'A1' })).toBe(table);
  expect(win(table).params).toEqual({ activity: 'A1' });
  expect(s().open('schedule')).toBe(table);
  expect(s().wins.map((w) => w.programId)).toEqual(['schedule-table', 'gantt', 'cpm', 'progress']);
});

test('focus raises z above all', () => {
  const a = s().open('a');
  const b = s().open('b');
  s().focus(a);
  expect(win(a).z).toBeGreaterThan(win(b).z);
});

test('move is clamped below the menubar and inside the screen', () => {
  const a = s().open('a');
  s().move(a, -500, -500);
  expect(win(a).y).toBeGreaterThanOrEqual(44);
  expect(win(a).x).toBeGreaterThan(-win(a).w);
  s().move(a, 5000, 5000);
  expect(win(a).x + win(a).w).toBeLessThanOrEqual(1920);
  expect(win(a).y + win(a).h).toBeLessThanOrEqual(1080);
});

test('resize has a minimum', () => {
  const a = s().open('a');
  s().resize(a, 10, 10);
  expect(win(a)).toMatchObject({ w: 360, h: 240 });
});

test('minimized window is not active', () => {
  const a = s().open('a');
  s().minimize(a);
  expect(s().activeProgramId()).toBeNull();
});

test('active program is the top window that is not minimized', () => {
  s().open('a');
  const b = s().open('b');
  expect(s().activeProgramId()).toBe('b');
  s().minimize(b);
  expect(s().activeProgramId()).toBe('a');
});

test('opening a minimized program restores it and keeps its params', () => {
  const a = s().open('a', { id: '7' });
  s().minimize(a);
  expect(s().open('a')).toBe(a);
  expect(win(a)).toMatchObject({ minimized: false, params: { id: '7' } });
  expect(s().activeProgramId()).toBe('a');
});

test('close removes the window', () => {
  const a = s().open('a');
  s().close(a);
  expect(s().wins).toEqual([]);
  expect(s().activeProgramId()).toBeNull();
});

test('toggleMaximize flips the flag and raises the window', () => {
  const a = s().open('a');
  const b = s().open('b');
  s().toggleMaximize(a);
  expect(win(a).maximized).toBe(true);
  expect(win(a).z).toBeGreaterThan(win(b).z);
  s().toggleMaximize(a);
  expect(win(a).maximized).toBe(false);
});

test('new windows cascade 32px and wrap to the top-left', () => {
  const ids = Array.from({ length: 20 }, (_, i) => s().open(`p${i}`));
  const first = win(ids[0]);
  expect(first.y).toBeGreaterThanOrEqual(MENUBAR_H);
  expect(win(ids[1])).toMatchObject({ x: first.x + 32, y: first.y + 32 });
  const wrapped = ids.findIndex((id, i) => i > 0 && win(id).x === first.x && win(id).y === first.y);
  expect(wrapped).toBeGreaterThan(1);
  const before = win(ids[wrapped - 1]);
  expect(before.y + 32 + before.h > 1080 || before.x + 32 + before.w > 1920).toBe(true);
  for (const id of ids) {
    const w = win(id);
    expect(w.y).toBeGreaterThanOrEqual(MENUBAR_H);
    expect(w.y + w.h).toBeLessThanOrEqual(1080);
    expect(w.x + w.w).toBeLessThanOrEqual(1920);
  }
});

test('default size comes from the program and is clamped to the screen', () => {
  program('huge', 4000, 3000);
  screenIs(1280, 720);
  const a = s().open('huge');
  expect(win(a)).toMatchObject({ x: 0, y: MENUBAR_H, w: 1280, h: 720 - MENUBAR_H });
});

test('setTitle changes only the title', () => {
  const a = s().open('a');
  s().setTitle(a, '스케줄 — 5층 사무동 신축');
  expect(win(a)).toMatchObject({ title: '스케줄 — 5층 사무동 신축', programId: 'a' });
});

test('fitToScreen keeps every window inside a smaller screen', () => {
  program('big', 1600, 900);
  s().open('big');
  const b = s().open('b');
  s().move(b, 1500, 900);
  screenIs(1280, 720);
  s().fitToScreen();
  for (const w of s().wins) insideScreen(w, 1280, 720);
});

test('on a screen below the minimum size the title bar stays reachable', () => {
  const a = s().open('a');
  s().move(a, 900, 400);
  screenIs(300, 200);
  s().fitToScreen();
  expect(win(a)).toMatchObject({ x: 0, y: MENUBAR_H });
});

test('restore and focus clamp the window to the current screen', () => {
  const a = s().open('a');
  s().move(a, 1100, 450);
  s().minimize(a);
  screenIs(1024, 600);
  s().open('a');
  insideScreen(win(a), 1024, 600);
  screenIs(1920, 1080);
  s().move(a, 1100, 450);
  screenIs(1024, 600);
  s().focus(a);
  insideScreen(win(a), 1024, 600);
});

test('resizeRect from the left and top keeps the opposite edge fixed', () => {
  const r = { x: 100, y: 100, w: 800, h: 600 };
  expect(resizeRect(r, 'w', 100, 0)).toEqual({ x: 200, y: 100, w: 700, h: 600 });
  expect(resizeRect(r, 'w', 700, 0)).toEqual({ x: 540, y: 100, w: 360, h: 600 });
  expect(resizeRect(r, 'w', -500, 0)).toEqual({ x: 0, y: 100, w: 900, h: 600 });
  expect(resizeRect(r, 'n', 0, -100)).toEqual({ x: 100, y: MENUBAR_H, w: 800, h: 700 - MENUBAR_H });
  expect(resizeRect(r, 'se', 50, -500)).toEqual({ x: 100, y: 100, w: 850, h: 240 });
  expect(resizeRect(r, 'nw', 10, 10)).toEqual({ x: 110, y: 110, w: 790, h: 590 });
});

test('setBounds keeps the window inside the screen and above the minimum', () => {
  const a = s().open('a');
  s().setBounds(a, { x: -50, y: 0, w: 100, h: 5000 });
  expect(win(a)).toMatchObject({ x: 0, y: MENUBAR_H, w: 360, h: 1080 - MENUBAR_H });
});

test('the menubar is 48px and new windows start at y 68', () => {
  expect(MENUBAR_H).toBe(48);
  expect(win(s().open('a')).y).toBe(68);
});

test('clearActive leaves no active window until a window is raised again', () => {
  const a = s().open('a');
  s().clearActive();
  expect(s().activeProgramId()).toBeNull();
  expect(activeWindow(s())).toBeNull();
  s().focus(a);
  expect(s().activeProgramId()).toBe('a');
  s().clearActive();
  s().open('b');
  expect(s().activeProgramId()).toBe('b');
});

test('a maximized window fills from the menubar to the bottom of the screen', () => {
  expect(workArea()).toEqual({ x: 0, y: MENUBAR_H, w: 1920, h: 1080 - MENUBAR_H });
});

test('a right inset narrows the screen for clamping and maximizing', () => {
  const a = s().open('a');
  s().move(a, 1900, 100);
  s().setInsetRight(420);
  expect(win(a).x + win(a).w).toBeLessThanOrEqual(1500);
  expect(workArea().w).toBe(1500);
  s().setInsetRight(0);
  expect(workArea().w).toBe(1920);
});

const visible = () => s().wins.filter((w) => !w.minimized);
const area = { x: 0, y: MENUBAR_H, w: 1920, h: 1080 - MENUBAR_H - DOCK_RESERVE };

test('split puts the active window on the left half and stacks the rest on the right', () => {
  const a = s().open('a');
  const b = s().open('b');
  const c = s().open('c');
  s().focus(a);
  expect(s().arrange('split')).toBe(3);
  const half = (area.w - 3 * ARRANGE_GAP) / 2;
  expect(win(a)).toMatchObject({ x: ARRANGE_GAP, y: area.y + ARRANGE_GAP, w: Math.floor(half) });
  expect(win(b).x).toBe(win(c).x);
  expect(win(b).x).toBeGreaterThan(win(a).x + win(a).w);
  expect(win(c).y).toBeGreaterThan(win(b).y + win(b).h - 1);
  for (const w of visible()) expect(w.y + w.h).toBeLessThanOrEqual(area.y + area.h);
});

test('grid uses ceil(sqrt(n)) columns with equal cells and 8px gaps', () => {
  ['a', 'b', 'c', 'd', 'e'].forEach((p) => s().open(p));
  expect(s().arrange('grid')).toBe(5);
  const ws = visible();
  expect(new Set(ws.map((w) => w.w)).size).toBe(1);
  expect(new Set(ws.map((w) => w.h)).size).toBe(1);
  expect(new Set(ws.map((w) => w.x)).size).toBe(3);
  expect(Math.min(...ws.map((w) => w.x))).toBe(ARRANGE_GAP);
});

test('cascade offsets windows by 28px and never shrinks below the minimum', () => {
  const ids = ['a', 'b', 'c'].map((p) => s().open(p));
  s().arrange('cascade');
  expect(win(ids[1]).x - win(ids[0]).x).toBe(28);
  expect(win(ids[1]).y - win(ids[0]).y).toBe(28);
  for (const w of visible()) expect(w.w).toBeGreaterThanOrEqual(360);
});

test('arranging skips minimized windows and un-maximizes the rest', () => {
  const a = s().open('a');
  const b = s().open('b');
  s().toggleMaximize(a);
  s().minimize(b);
  expect(s().arrange('grid')).toBe(1);
  expect(win(a).maximized).toBe(false);
  expect(win(b).minimized).toBe(true);
});

test('minimizeAll, closeActive, closeAll and nextWindow', () => {
  const a = s().open('a');
  const b = s().open('b');
  const c = s().open('c');
  s().nextWindow();
  expect(s().activeProgramId()).toBe('a');
  s().nextWindow();
  expect(s().activeProgramId()).toBe('b');
  s().closeActive();
  expect(s().wins.map((w) => w.id)).toEqual([a, c]);
  expect(s().minimizeAll()).toBe(2);
  expect(s().activeProgramId()).toBeNull();
  expect(s().closeAll()).toBe(2);
  expect(s().wins).toEqual([]);
  expect(b).toBe('w2');
});

describe('window motion (switch on, fake clock)', () => {
  const ids = () => s().wins.map((w) => w.id);
  beforeEach(() => {
    setWindowMotion(true);
    vi.useFakeTimers();
  });
  afterEach(() => {
    s().reset();
    vi.useRealTimers();
    setWindowMotion(false);
    vi.unstubAllGlobals();
  });

  test('a new window opens with the open motion, which clears after 220ms', () => {
    const a = s().open('schedule-table');
    expect(win(a).motion).toBe('open');
    vi.advanceTimersByTime(219);
    expect(win(a).motion).toBe('open');
    vi.advanceTimersByTime(1);
    expect(win(a).motion).toBeUndefined();
  });

  test('an open from the Dock is marked so the window grows out of the icon', () => {
    const a = s().open('schedule-table', undefined, 'dock');
    expect(win(a)).toMatchObject({ motion: 'open', fromDock: true });
    vi.advanceTimersByTime(220);
    expect(win(a).motion).toBeUndefined();
    expect(win(a).fromDock).toBeUndefined();
  });

  test('bringing an open window forward has no motion', () => {
    const a = s().open('schedule-table');
    s().open('chat');
    vi.advanceTimersByTime(220);
    s().open('schedule-table');
    expect(win(a).motion).toBeUndefined();
    expect(top().id).toBe(a);
    s().focus(s().wins[1].id);
    expect(s().wins[1].motion).toBeUndefined();
  });

  test('close keeps the window, inactive and untouchable, until the 160ms motion ends', () => {
    const a = s().open('schedule-table');
    const b = s().open('chat');
    vi.advanceTimersByTime(220);
    s().close(b);
    expect(win(b).motion).toBe('close');
    expect(s().activeProgramId()).toBe('schedule-table');
    const z = s().topZ;
    s().focus(b);
    s().toggleMaximize(b);
    s().minimize(b);
    s().close(b);
    expect(win(b)).toMatchObject({ motion: 'close', minimized: false, maximized: false });
    expect(s().topZ).toBe(z);
    vi.advanceTimersByTime(159);
    expect(ids()).toEqual([a, b]);
    vi.advanceTimersByTime(1);
    expect(ids()).toEqual([a]);
  });

  test('opening a program whose window is closing makes a new window', () => {
    const a = s().open('schedule-table');
    s().close(a);
    const b = s().open('schedule-table');
    expect(b).not.toBe(a);
    expect(win(b).motion).toBe('open');
    vi.advanceTimersByTime(220);
    expect(ids()).toEqual([b]);
  });

  test('closing a minimized window removes it at once (there is nothing to see)', () => {
    const a = s().open('schedule-table');
    s().minimize(a);
    s().close(a);
    expect(s().wins).toEqual([]);
  });

  test('minimize hides in the store at once and the 260ms motion then clears; restore plays back', () => {
    const a = s().open('schedule-table');
    vi.advanceTimersByTime(220);
    s().minimize(a);
    expect(win(a)).toMatchObject({ minimized: true, motion: 'minimize' });
    expect(s().activeProgramId()).toBeNull();
    vi.advanceTimersByTime(259);
    expect(win(a).motion).toBe('minimize');
    vi.advanceTimersByTime(1);
    expect(win(a).motion).toBeUndefined();
    s().open('schedule-table');
    expect(win(a)).toMatchObject({ minimized: false, motion: 'restore' });
    vi.advanceTimersByTime(260);
    expect(win(a).motion).toBeUndefined();
    s().minimize(a);
    vi.advanceTimersByTime(260);
    s().focus(a);
    expect(win(a)).toMatchObject({ minimized: false, motion: 'restore' });
  });

  test('maximize and restore zoom for 200ms; a window that is still opening keeps its open motion', () => {
    const a = s().open('schedule-table');
    s().toggleMaximize(a);
    expect(win(a)).toMatchObject({ maximized: true, motion: 'open' });
    vi.advanceTimersByTime(220);
    s().toggleMaximize(a);
    expect(win(a)).toMatchObject({ maximized: false, motion: 'zoom' });
    vi.advanceTimersByTime(199);
    expect(win(a).motion).toBe('zoom');
    vi.advanceTimersByTime(1);
    expect(win(a).motion).toBeUndefined();
  });

  test('minimize all and close all move every window; closing windows are not counted again', () => {
    const a = s().open('schedule-table');
    const b = s().open('chat');
    vi.advanceTimersByTime(220);
    expect(s().minimizeAll()).toBe(2);
    expect(s().wins.map((w) => w.motion)).toEqual(['minimize', 'minimize']);
    vi.advanceTimersByTime(260);
    s().focus(a);
    s().focus(b);
    vi.advanceTimersByTime(260);
    expect(s().closeAll()).toBe(2);
    expect(s().wins.map((w) => w.motion)).toEqual(['close', 'close']);
    expect(s().closeAll()).toBe(0);
    vi.advanceTimersByTime(160);
    expect(s().wins).toEqual([]);
  });

  test('close active closes with motion and the next window becomes active at once', () => {
    s().open('schedule-table');
    const b = s().open('chat');
    s().closeActive();
    expect(win(b).motion).toBe('close');
    expect(s().activeProgramId()).toBe('schedule-table');
  });

  test('with reduced motion everything changes at once', () => {
    vi.stubGlobal('matchMedia', (q: string) => ({ matches: q.includes('reduce'), media: q, addEventListener() {}, removeEventListener() {} }));
    const a = s().open('schedule-table', undefined, 'dock');
    expect(win(a).motion).toBeUndefined();
    expect(win(a).fromDock).toBeUndefined();
    s().minimize(a);
    expect(win(a).minimized).toBe(true);
    expect(win(a).motion).toBeUndefined();
    s().focus(a);
    s().toggleMaximize(a);
    expect(win(a)).toMatchObject({ minimized: false, maximized: true });
    expect(win(a).motion).toBeUndefined();
    s().close(a);
    expect(s().wins).toEqual([]);
    expect(vi.getTimerCount()).toBe(0);
  });

  test('with the switch off (the default under the test runner) close removes at once', () => {
    setWindowMotion(false);
    const a = s().open('schedule-table');
    expect(win(a).motion).toBeUndefined();
    s().close(a);
    expect(s().wins).toEqual([]);
  });

  test('reset drops pending motion timers', () => {
    s().open('schedule-table');
    s().open('chat');
    expect(vi.getTimerCount()).toBe(2);
    s().reset();
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe('Task 25 fix 1 · 관리자 전용 프로그램은 창으로도 열지 않는다', () => {
  beforeEach(() => {
    register({ id: 'adm-only', name: '관리자 도구', icon: null, kind: 'system', adminOnly: true, defaultSize: { w: 800, h: 600 }, component: lazy(() => import('./Placeholder')) });
  });
  afterEach(() => useSession.getState().logout());

  test('a non-admin open() opens nothing', () => {
    signInAsDemo('user');
    expect(s().open('adm-only')).toBe('');
    expect(s().wins).toEqual([]);
  });

  test('an admin still opens it', () => {
    signInAsDemo('admin');
    const id = s().open('adm-only');
    expect(id).not.toBe('');
    expect(s().wins.map((w) => w.programId)).toEqual(['adm-only']);
  });
});

describe('프로젝트 격리 · 일정 동기화 · 2단 스테이지 배치', () => {
  afterEach(() => useCurrentSchedule.setState({ userId: null, current: null, reloadToken: 0, newProjectModal: 'closed', creatingNewProject: false }));

  test('changing currentSchedule synchronizes all open schedule-bound windows and clears stale params', () => {
    useCurrentSchedule.setState({ userId: 1, current: { id: 1, name: '5층 사무동' } });
    const ganttId = s().open('gantt', { id: '1' });
    const tableId = s().open('schedule-table', { id: '1', activity: 'A2020' });
    const condId = s().open('conditions', { id: '1' });
    const chatId = s().open('chat', { session: '9' });

    useCurrentSchedule.getState().setCurrent({ id: 5, name: '전해질 R&D' });
    expect(win(ganttId).params).toEqual({ id: '5' });
    expect(win(tableId).params).toEqual({ id: '5' });
    expect(win(condId).params).toEqual({ id: '5' });
    expect(win(chatId).params).toEqual({ session: '9' });
  });

  test('enterNewProjectMode minimizes open schedule windows and clears schedule ids', () => {
    useCurrentSchedule.setState({ userId: 1, current: { id: 1, name: '5층 사무동' } });
    const ganttId = s().open('gantt', { id: '1' });
    const chatId = s().open('chat');

    useCurrentSchedule.getState().enterNewProjectMode();
    expect(useCurrentSchedule.getState().current).toBeNull();
    expect(useCurrentSchedule.getState().creatingNewProject).toBe(true);
    expect(win(ganttId).minimized).toBe(true);
    expect(win(ganttId).params).toBeUndefined();
    expect(win(chatId).minimized).toBe(false);
  });

  test('stageLayout with chat open places chat left and target stage right without overlap or Dock collision', () => {
    s().setInsetTop(RIBBON_H);
    const chatId = s().open('chat');
    const qId = s().stageLayout('questionnaire', { id: '3', session: '1' });
    const c = win(chatId);
    const q = win(qId);

    expect(c.y).toBeGreaterThanOrEqual(MENUBAR_H + RIBBON_H);
    expect(q.y).toBeGreaterThanOrEqual(MENUBAR_H + RIBBON_H);
    expect(c.x + c.w).toBeLessThanOrEqual(q.x);
    expect(c.y + c.h).toBeLessThanOrEqual(1080 - DOCK_RESERVE);
    expect(q.y + q.h).toBeLessThanOrEqual(1080 - DOCK_RESERVE);
  });

  test('chat opened normally at 1440x900 fits strictly above the Dock', () => {
    screenIs(1440, 900);
    const chatId = s().open('chat');
    const c = win(chatId);
    expect(c.y + c.h).toBeLessThanOrEqual(900 - DOCK_RESERVE);
  });
});

describe('상단 진행 리본이 펼쳐지면 창 제목줄이 그 밑에 숨지 않는다 (U4)', () => {
  const ribbonBottom = MENUBAR_H + RIBBON_H;

  test('a new window, a dragged window and a maximized window start below the open ribbon', () => {
    s().setInsetTop(RIBBON_H);
    const a = s().open('a');
    expect(win(a).y).toBeGreaterThanOrEqual(ribbonBottom);
    s().move(a, 100, 0);
    expect(win(a).y).toBe(ribbonBottom);
    expect(workArea()).toEqual({ x: 0, y: ribbonBottom, w: 1920, h: 1080 - ribbonBottom });
    expect(resizeRect(win(a), 'n', 0, -500).y).toBe(ribbonBottom);
  });

  test('opening the ribbon pushes down windows it would cover and closing it leaves them', () => {
    const a = s().open('a');
    const b = s().open('b');
    s().move(b, 300, 400);
    expect(win(a).y).toBe(68);
    s().setInsetTop(RIBBON_H);
    expect(win(a).y).toBe(ribbonBottom);
    expect(win(a).y + win(a).h).toBeLessThanOrEqual(1080);
    expect(win(b).y).toBe(400);
    s().setInsetTop(0);
    expect(win(a).y).toBe(ribbonBottom);
    expect(workArea().y).toBe(MENUBAR_H);
  });

  // 리뷰 U4: 내려간 창은 내려간 만큼 줄어 아래 끝(Dock 위)이 그대로이고, 정렬도 리본 아래에서 한다.
  test('a window pushed down by the ribbon shrinks by the same amount so its bottom stays put', () => {
    const a = s().open('a');
    const bottom = win(a).y + win(a).h;
    const pushed = ribbonBottom - win(a).y;
    s().setInsetTop(RIBBON_H);
    expect(win(a).y).toBe(ribbonBottom);
    expect(win(a).y + win(a).h).toBe(bottom);
    expect(pushed).toBeGreaterThan(0);
  });

  test('arranging with the ribbon open keeps every window below it and above the Dock', () => {
    s().setInsetTop(RIBBON_H);
    ['a', 'b', 'c'].forEach((p) => s().open(p));
    s().arrange('grid');
    for (const w of s().wins) {
      expect(w.y).toBeGreaterThanOrEqual(ribbonBottom);
      expect(w.y + w.h).toBeLessThanOrEqual(1080 - DOCK_RESERVE);
    }
  });
});
