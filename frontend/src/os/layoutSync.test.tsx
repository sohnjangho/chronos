// 다시 열면 그대로: 화면 형태별 되살리기, 사람마다 따로, 화면에 맞춤, 틀린 저장 → 첫 화면, 서버 맞춤·기기 사이 이어 열기.
import { StrictMode } from 'react';
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeAll, beforeEach, expect, test, vi } from 'vitest';
import { registerPrograms } from '../programs';
import { json, signInAsDemo, stubFetch } from '../test-helpers';
import App from './App';
import { useApprovals } from './approvals';
import { useSession } from './session';
import { resetShellState } from './shellReset';
import { useDeviceMode } from './useIsMobile';
import { useWindows, type Win } from './windowStore';

const PHONE_LIKE = /\d(?:[\s.-]?\d){7,}/;
const KEY = (mode: string, id: number) => `chronos.layout.${mode}.${id}`;
const stored = (mode: string, id: number) => JSON.parse(localStorage.getItem(KEY(mode, id)) ?? 'null');
const s = () => useWindows.getState();
const byProgram = (p: string): Win => s().wins.find((w) => w.programId === p)!;
const screenIs = (w: number, h: number) => {
  vi.stubGlobal('innerWidth', w);
  vi.stubGlobal('innerHeight', h);
};

let server: Record<string, unknown>;
let puts: { mode: string; body: string; init: RequestInit | undefined }[];
let holdPut: ((r: Response) => void)[] | null;

function fakeServer() {
  const putRoute = (mode: string) => (init?: RequestInit) => {
    puts.push({ mode, body: String(init?.body), init });
    const reply = json(200, { mode, updated_at: new Date().toISOString() });
    if (holdPut) return new Promise<Response>((resolve) => holdPut!.push(() => resolve(reply)));
    return reply;
  };
  return stubFetch({
    '/api/approvals/count': { pending: 0 },
    '/api/schedules': [],
    '/api/chat/sessions': [],
    '/api/me/ui-state': () => json(200, server),
    'PUT /api/me/ui-state/desktop': putRoute('desktop'),
    'PUT /api/me/ui-state/tablet': putRoute('tablet'),
    'PUT /api/me/ui-state/phone': putRoute('phone'),
  });
}

/** 탭을 버렸다가 다시 여는 것: 그린 것을 걷고(떠날 때 쓰기 포함) 창 상태를 새로 시작한다. */
function reload() {
  window.dispatchEvent(new Event('pagehide'));
  cleanup();
  useWindows.getState().reset();
}

beforeAll(() => registerPrograms());
beforeEach(() => {
  localStorage.clear();
  server = {};
  puts = [];
  holdPut = null;
  screenIs(1920, 1080);
  fakeServer();
});
afterEach(() => {
  cleanup();
  resetShellState();
  vi.unstubAllGlobals();
  useApprovals.setState({ pending: 0 });
  useSession.getState().logout();
  useDeviceMode.getState().reset();
});

const settle = () => act(() => new Promise((r) => setTimeout(r, 0)));

test('desktop: windows, places, sizes, minimized/maximized, stacking, focus and params come back after a reload', async () => {
  signInAsDemo('user', '김하늘', 'demo-user', 1);
  render(<App />);
  await settle();
  act(() => {
    s().open('gantt', { id: '3' });
    s().open('contacts', { id: '3', contact: '12', tab: 'calls' });
    s().open('explorer');
  });
  act(() => {
    s().move(byProgram('gantt').id, 400, 300);
    s().minimize(byProgram('explorer').id);
    s().toggleMaximize(byProgram('contacts').id);
  });
  const before = s().wins.map(({ programId, x, y, w, h, minimized, maximized, params, z }) => ({ programId, x, y, w, h, minimized, maximized, params, z }));
  reload();
  render(<App />);
  await settle();
  const after = s().wins.map(({ programId, x, y, w, h, minimized, maximized, params, z }) => ({ programId, x, y, w, h, minimized, maximized, params, z }));
  const order = (l: typeof before) => [...l].sort((a, b) => a.z - b.z).map((w) => ({ ...w, z: 0 }));
  expect(order(after)).toEqual(order(before));
  expect(s().activeProgramId()).toBe('contacts');
});

test('desktop: positions and sizes are fitted to a smaller screen on restore', async () => {
  signInAsDemo('user', '김하늘', 'demo-user', 1);
  localStorage.setItem(
    KEY('desktop', 1),
    JSON.stringify({ state: { v: 1, wins: [{ program: 'gantt', x: 3000, y: -50, w: 2500, h: 1600, min: false, max: false }], deactivated: false }, at: 0, dirty: false }),
  );
  screenIs(1280, 800);
  render(<App />);
  await settle();
  const w = byProgram('gantt');
  expect(w.x).toBeGreaterThanOrEqual(0);
  expect(w.y).toBeGreaterThanOrEqual(48);
  expect(w.x + w.w).toBeLessThanOrEqual(1280);
  expect(w.y + w.h).toBeLessThanOrEqual(800);
});

test('desktop: unreadable or old-shape saved state starts at home and is overwritten', async () => {
  signInAsDemo('user', '김하늘', 'demo-user', 1);
  for (const bad of ['{not json', JSON.stringify({ state: { v: 0, windows: ['gantt'] }, at: 0, dirty: false }), JSON.stringify([1, 2])]) {
    localStorage.setItem(KEY('desktop', 1), bad);
    render(<App />);
    await settle();
    expect(s().wins).toEqual([]);
    expect(stored('desktop', 1).state).toEqual({ v: 1, wins: [], deactivated: false });
    reload();
  }
});

test('desktop: each account keeps its own windows; logout keeps them for the next login', async () => {
  signInAsDemo('user', '김하늘', 'demo-user', 1);
  render(<App />);
  await settle();
  act(() => void s().open('gantt'));
  act(() => useSession.getState().logout());
  expect(stored('desktop', 1).state.wins.map((w: { program: string }) => w.program)).toEqual(['gantt']);
  signInAsDemo('user', '이바다', 'demo-user-2', 2);
  await settle();
  expect(s().wins).toEqual([]);
  act(() => useSession.getState().logout());
  signInAsDemo('user', '김하늘', 'demo-user', 1);
  await settle();
  expect(s().wins.map((w) => w.programId)).toEqual(['gantt']);
});

test('desktop: access is checked again on restore (role became field)', async () => {
  localStorage.setItem(
    KEY('desktop', 2),
    JSON.stringify({
      state: { v: 1, wins: ['contacts', 'devconsole', 'gantt', 'gone'].map((program) => ({ program, x: 10, y: 60, w: 600, h: 400, min: false, max: false })), deactivated: false },
      at: 0,
      dirty: false,
    }),
  );
  signInAsDemo('field', '박현장', 'demo-field', 2);
  render(<App />);
  await settle();
  expect(s().wins.map((w) => w.programId)).toEqual(['gantt']);
});

test('desktop: never keeps a draft, a call step or a question to send — and no phone numbers, locally or on the server', async () => {
  signInAsDemo('user', '김하늘', 'demo-user', 1);
  render(<App />);
  await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/me/ui-state', expect.anything()));
  await settle();
  act(() => {
    s().open('contacts', { id: '3', contact: '12', tab: 'calls', compose: '010-0000-0000 으로 회신 바랍니다', call: '1' });
    s().open('chat', { ask: '010-0000-0000 에 전화해 줘' });
    s().open('delays', { id: '3', activity: 'A2020', days: '2' });
  });
  reload();
  const local = JSON.stringify(stored('desktop', 1).state); // 곁에 둔 맞춘 시각(at)은 서버 시각 숫자라 뺀다
  expect(local).not.toMatch(PHONE_LIKE);
  expect(local).not.toMatch(/compose|call"|ask|activity|days/);
  await waitFor(() => expect(puts.length).toBeGreaterThan(0));
  for (const p of puts) expect(p.body).not.toMatch(PHONE_LIKE);
  render(<App />);
  await settle();
  expect(byProgram('contacts').params).toEqual({ id: '3', contact: '12', tab: 'calls' });
  expect(byProgram('chat').params).toBeUndefined();
  expect(byProgram('delays').params).toEqual({ id: '3' });
});

test('desktop: a newer server layout (another desktop) replaces the local one', async () => {
  signInAsDemo('user', '김하늘', 'demo-user', 1);
  localStorage.setItem(KEY('desktop', 1), JSON.stringify({ state: { v: 1, wins: [{ program: 'gantt', x: 10, y: 60, w: 600, h: 400, min: false, max: false }], deactivated: false }, at: 1000, dirty: false }));
  server = { desktop: { state: { v: 1, wins: [{ program: 'cpm', x: 40, y: 80, w: 700, h: 500, min: false, max: false, params: { id: '3' } }], deactivated: false }, updated_at: '2026-11-24T01:00:00+00:00' } };
  render(<App />);
  await waitFor(() => expect(s().wins.map((w) => w.programId)).toEqual(['cpm']));
  expect(byProgram('cpm').params).toEqual({ id: '3' });
});

test('desktop: continues from the phone — its focused program opens here when the phone state is newer', async () => {
  signInAsDemo('user', '김하늘', 'demo-user', 1);
  server = {
    desktop: { state: { v: 1, wins: [{ program: 'gantt', x: 10, y: 60, w: 600, h: 400, min: false, max: false }], deactivated: false }, updated_at: '2026-11-24T01:00:00+00:00' },
    phone: { state: { v: 1, tab: 'contacts', sub: 'gantt', params: { contact: '12', tab: 'calls' } }, updated_at: '2026-11-24T02:00:00+00:00' },
  };
  render(<App />);
  await waitFor(() => expect(s().activeProgramId()).toBe('contacts'));
  expect(s().wins.map((w) => w.programId)).toEqual(['gantt', 'contacts']);
  expect(byProgram('contacts').params).toEqual({ contact: '12', tab: 'calls' });
});

test('saving: debounced, keepalive, nothing when unchanged, one request at a time', async () => {
  signInAsDemo('user', '김하늘', 'demo-user', 1);
  render(<App />);
  await waitFor(() => expect(puts.length).toBe(1)); // 서버에 없던 첫 모양
  await act(() => new Promise((r) => setTimeout(r, 50)));
  holdPut = [];
  act(() => void s().open('gantt'));
  await act(() => new Promise((r) => setTimeout(r, 400)));
  expect(puts.length).toBe(1); // 아직(1초 기다림)
  await act(() => new Promise((r) => setTimeout(r, 800)));
  expect(puts.length).toBe(2);
  expect(puts[1].init?.keepalive).toBe(true);
  act(() => void s().open('cpm'));
  act(() => window.dispatchEvent(new Event('pagehide')));
  expect(puts.length).toBe(2); // 앞 요청이 아직 — 하나씩
  await act(async () => holdPut!.splice(0).forEach((f) => f(new Response())));
  await waitFor(() => expect(puts.length).toBe(3));
  const release = holdPut!;
  holdPut = null;
  await act(async () => release.splice(0).forEach((f) => f(new Response())));
  await settle();
  act(() => window.dispatchEvent(new Event('pagehide')));
  await settle();
  expect(puts.length).toBe(3); // 같은 모양은 다시 보내지 않는다
});

test('phone: the tab and its program come back after a reload', async () => {
  screenIs(390, 844);
  signInAsDemo('user', '김하늘', 'demo-user', 1);
  render(<App />);
  const nav = () => screen.getByRole('navigation', { name: '모바일 탐색' });
  await userEvent.click(within(nav()).getByRole('button', { name: /연락처/ }));
  reload();
  render(<App />);
  expect(within(nav()).getByRole('button', { name: /연락처/ })).toHaveAttribute('aria-current', 'page');
  expect(stored('phone', 1).state).toEqual({ v: 1, tab: 'contacts', sub: 'schedule-table' });
});

test('phone: an old saved tab that no longer exists starts at home', async () => {
  screenIs(390, 844);
  signInAsDemo('user', '김하늘', 'demo-user', 1);
  localStorage.setItem(KEY('phone', 1), JSON.stringify({ state: { v: 1, tab: 'library', sub: 'gantt' }, at: 0, dirty: false }));
  render(<App />);
  const nav = screen.getByRole('navigation', { name: '모바일 탐색' });
  expect(within(nav).getByRole('button', { name: /대화/ })).toHaveAttribute('aria-current', 'page');
  expect(stored('phone', 1).state.tab).toBe('chat');
});

test('phone: continues from the desktop — the focused contacts window opens on the contacts tab (first visit, StrictMode double mount)', async () => {
  screenIs(390, 844);
  signInAsDemo('user', '김하늘', 'demo-user', 1);
  server = {
    desktop: {
      state: { v: 1, wins: [{ program: 'contacts', x: 10, y: 60, w: 600, h: 400, min: false, max: false, params: { contact: '12', tab: 'calls' } }], deactivated: false },
      updated_at: '2026-11-24T02:00:00+00:00',
    },
  };
  render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
  const nav = screen.getByRole('navigation', { name: '모바일 탐색' });
  await waitFor(() => expect(within(nav).getByRole('button', { name: /연락처/ })).toHaveAttribute('aria-current', 'page'));
  await waitFor(() => expect(stored('phone', 1).state).toEqual({ v: 1, tab: 'contacts', sub: 'schedule-table', params: { contact: '12', tab: 'calls' } }));
});

test('tablet: the open program comes back after a reload', async () => {
  screenIs(1180, 820);
  signInAsDemo('user', '김하늘', 'demo-user', 1);
  act(() => useDeviceMode.getState().setMode('tablet'));
  render(<App />);
  const rail = () => screen.getByRole('navigation', { name: '태블릿 탐색' });
  await userEvent.click(within(rail()).getByRole('button', { name: /간트/ }));
  reload();
  render(<App />);
  expect(within(rail()).getByRole('button', { name: /간트/ })).toHaveAttribute('aria-current', 'page');
  expect(stored('tablet', 1).state).toEqual({ v: 1, active: 'gantt' });
});
