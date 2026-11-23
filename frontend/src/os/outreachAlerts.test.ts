// 긴급 보고 토스트(Task 85): 20초마다 GET /api/outreach/alerts?since=… — 보고 하나에 토스트 하나, 토스트에 번호 없음,
// 현장 관리자·로그인 안 함은 묻지 않는다.
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { json, signInAsDemo } from '../test-helpers';
import { ALERT_POLL_MS, alertText, resetOutreachAlerts, useOutreachAlerts } from './outreachAlerts';
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
  vi.useRealTimers();
  vi.unstubAllGlobals();
  useSession.getState().logout();
});

const urls = () => fetchMock.mock.calls.map((c) => String(c[0]));
const toasts = () => pushed.map((t) => t.text);

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
  expect(urls()[1]).toBe(`/api/outreach/alerts?since=${encodeURIComponent(NOW1)}`);
  expect(toasts()).toHaveLength(2); // 같은 보고(7)는 다시 띄우지 않는다
});

test('a toast never carries a number even if a name looks like one', () => {
  const text = alertText(alert({ contact_name: '현장 010-0000-0199', schedule_name: '현장 01000000199' }));
  expect(text).not.toMatch(/\d{3,}/);
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

test('a failed poll keeps the cursor and tries again on the next tick', async () => {
  signInAsDemo('admin');
  fetchMock.mockImplementationOnce(() => Promise.resolve(json(500, { code: 'server', message: '오류' })));
  replies = [];
  renderHook(() => useOutreachAlerts());
  await flush();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ALERT_POLL_MS);
  });
  expect(urls()).toEqual(['/api/outreach/alerts', '/api/outreach/alerts']);
  expect(toasts()).toEqual([]);
});
