// 긴급 보고 토스트(Task 85): 20초마다 GET /api/outreach/alerts?since=… — 보고 하나에 토스트 하나, 토스트에 번호 없음,
// 현장 관리자·로그인 안 함·창이 안 보일 때는 묻지 않는다. 커서는 서버 now 에서 30초 겹치고(본 보고는 다시 띄우지 않음),
// 실패하면 쉬는 동안을 두 배씩(2분까지) 늘린다.
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { json, signInAsDemo } from '../test-helpers';
import { ALERT_MAX_MS, ALERT_POLL_MS, alertText, resetOutreachAlerts, SEEN_MAX, useOutreachAlerts } from './outreachAlerts';
import { useSession } from './session';
import { useToast } from './ToastStack';

const NOW1 = '2026-11-27T01:00:00Z';
const NOW2 = '2026-11-27T01:00:20Z';
const alert = (over: Record<string, unknown> = {}) => ({
  id: 7, schedule_id: 1, schedule_name: '5층 사무동 신축', medium: 'call', contact_name: '박현장', created_at: '2026-11-27T00:59:00Z', ...over,
});

let replies: unknown[];
let fetchMock: ReturnType<typeof vi.fn>;
let pushed: { text: string; tone: string }[];
beforeEach(() => {
  vi.useFakeTimers();
  resetOutreachAlerts();
  pushed = [];
  // 토스트는 3.2초 뒤 저절로 사라지므로 띄운 것을 따로 센다.
  useToast.setState({ items: [], push: (text: string, tone = 'info') => void pushed.push({ text, tone }) } as never);
  replies = [];
  fetchMock = vi.fn(() => Promise.resolve(json(200, replies.shift() ?? { now: NOW2, items: [] })));
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => {
  setHidden(false);
  vi.useRealTimers();
  vi.unstubAllGlobals();
  useSession.getState().logout();
});

const urls = () => fetchMock.mock.calls.map((c) => String(c[0]));
const toasts = () => pushed.map((t) => t.text);

function setHidden(hidden: boolean) {
  Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden });
}
const later = (ms: number) =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });

async function flush() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
}

test('polls every 20 seconds, toasts each urgent report once and moves the cursor', async () => {
  signInAsDemo('user');
  replies = [
    { now: NOW1, items: [alert(), alert({ id: 8, schedule_id: null, schedule_name: null, contact_name: null, medium: 'sms' })] },
    { now: NOW2, items: [alert()] },
  ];
  renderHook(() => useOutreachAlerts());
  await flush();
  expect(urls()).toEqual(['/api/outreach/alerts']);
  expect(toasts()).toEqual(['긴급 보고 — 5층 사무동 신축 · 박현장 · 전화로 받은 보고', '긴급 보고 — 일정 없음 · 모르는 번호 · 문자로 받은 보고']);
  expect(pushed.every((t) => t.tone === 'warning')).toBe(true);

  await act(async () => {
    await vi.advanceTimersByTimeAsync(ALERT_POLL_MS);
  });
  expect(ALERT_POLL_MS).toBe(20_000);
  // 다음 since = 서버 now − 30초(그사이 같은 때에 들어온 보고를 놓치지 않게 겹친다 — 본 보고는 위에서 거른다)
  expect(urls()[1]).toBe(`/api/outreach/alerts?since=${encodeURIComponent('2026-11-27T00:59:30.000Z')}`);
  expect(toasts()).toHaveLength(2); // 같은 보고(7)는 다시 띄우지 않는다
});

test('a toast never carries a phone number even if a name looks like one, but other numbers stay', () => {
  for (const name of ['현장 010-0000-0199', '현장 01000000199', '현장 +82 10-0000-0199', '현장 02-000-0000', '대표 1588-0000']) {
    const text = alertText(alert({ contact_name: name }));
    expect(text).toContain('[번호]');
    expect(text.replace('5층', '')).not.toMatch(/\d{3,}/);
  }
  expect(alertText(alert({ schedule_name: '123동 신축', contact_name: '2공구 반장' }))).toBe('긴급 보고 — 123동 신축 · 2공구 반장 · 전화로 받은 보고');
});

test('field managers and signed-out sessions never ask', async () => {
  signInAsDemo('field');
  const { unmount } = renderHook(() => useOutreachAlerts());
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ALERT_POLL_MS * 3);
  });
  unmount();
  useSession.getState().logout();
  renderHook(() => useOutreachAlerts());
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ALERT_POLL_MS * 2);
  });
  expect(fetchMock).not.toHaveBeenCalled();
});

test('failed polls keep the cursor and wait twice as long each time (up to 2 minutes), success resets', async () => {
  signInAsDemo('admin');
  const fail = () => Promise.resolve(json(500, { code: 'server', message: '오류' }));
  for (let i = 0; i < 4; i++) fetchMock.mockImplementationOnce(fail);
  renderHook(() => useOutreachAlerts());
  await flush();
  expect(urls()).toHaveLength(1);
  await later(ALERT_POLL_MS); // 실패 1 → 40초 뒤
  expect(urls()).toHaveLength(1);
  await later(ALERT_POLL_MS);
  expect(urls()).toHaveLength(2); // 실패 2 → 80초 뒤
  await later(80_000);
  expect(urls()).toHaveLength(3); // 실패 3 → 160초가 아니라 2분
  await later(ALERT_MAX_MS);
  expect(urls()).toHaveLength(4); // 실패 4 → 다시 2분
  await later(ALERT_MAX_MS);
  expect(urls()).toHaveLength(5); // 성공 → 다음은 20초
  await later(ALERT_POLL_MS);
  expect(urls()).toHaveLength(6);
  expect(ALERT_MAX_MS).toBe(120_000);
  expect(new Set(urls().slice(0, 5))).toEqual(new Set(['/api/outreach/alerts'])); // 실패 동안 커서는 그대로
  expect(toasts()).toEqual([]);
});

test('nothing is asked while the browser tab is hidden', async () => {
  signInAsDemo('user');
  setHidden(true);
  renderHook(() => useOutreachAlerts());
  await later(ALERT_POLL_MS * 3);
  expect(fetchMock).not.toHaveBeenCalled();
  setHidden(false);
  await later(ALERT_POLL_MS);
  expect(urls()).toEqual(['/api/outreach/alerts']);
});

test('the memory of seen reports is capped — the oldest falls out first', async () => {
  signInAsDemo('user');
  const many = Array.from({ length: SEEN_MAX + 1 }, (_, i) => alert({ id: i + 1 }));
  replies = [{ now: NOW1, items: many }, { now: NOW2, items: [alert({ id: 1 }), alert({ id: SEEN_MAX + 1 })] }];
  renderHook(() => useOutreachAlerts());
  await flush();
  expect(pushed).toHaveLength(SEEN_MAX + 1);
  await later(ALERT_POLL_MS);
  expect(pushed).toHaveLength(SEEN_MAX + 2); // 1 은 밀려나 다시 뜨고, 막 본 것은 뜨지 않는다
  expect(SEEN_MAX).toBe(200);
});
