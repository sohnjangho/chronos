import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test, vi } from 'vitest';
import { stubFetch } from '../test-helpers';
import AttentionWidget from './AttentionWidget';
import { reasonText, type AttentionItem } from './attention';
import { useWindows } from './windowStore';

function item(name: string, level: AttentionItem['level'], extra: Partial<AttentionItem> = {}): AttentionItem {
  return {
    id: 1, name, domain: 'construction', finish: '2027-03-05', plan_finish: '2027-03-01', finish_delta: 0,
    late_count: 0, negative_float_count: 0, violations: 0, open_delays: 0, level, ...extra,
  };
}
const mockAttention = (items: AttentionItem[]) => stubFetch({ '/api/attention': { items } });
const DANGER = item('5층 사무동 신축', 'danger', { finish_delta: 4, open_delays: 1 });

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  useWindows.getState().reset();
});

test('widget lists schedules needing attention', async () => {
  mockAttention([DANGER, item('브래킷 BR-200', 'ok', { id: 2 })]);
  render(<AttentionWidget />);
  expect(await screen.findByText('주의할 일정 1')).toBeVisible();
  expect(screen.getByText('위험')).toBeVisible();
  expect(screen.getByText('준공 +4일 · 지연 사건 1건')).toBeVisible();
  expect(screen.queryByText('브래킷 BR-200')).toBeNull();
});

test('clicking opens the schedule table', async () => {
  mockAttention([DANGER]);
  const open = vi.spyOn(useWindows.getState(), 'open').mockImplementation(() => '');
  useWindows.setState({ open });
  render(<AttentionWidget />);
  await userEvent.click(await screen.findByRole('button', { name: /5층 사무동 신축/ }));
  expect(open).toHaveBeenCalledWith('schedule-table', { id: '1' });
});

test('empty state', async () => {
  mockAttention([]);
  render(<AttentionWidget />);
  expect(await screen.findByText('주의할 일정이 없습니다')).toBeVisible();
});

test('a failed first read says so instead of claiming nothing needs attention', async () => {
  stubFetch({});
  render(<AttentionWidget />);
  expect(await screen.findByText('불러오지 못했습니다')).toBeVisible();
  expect(screen.queryByText('주의할 일정이 없습니다')).toBeNull();
});

test('polls every minute', async () => {
  vi.useFakeTimers();
  const fetch = mockAttention([]);
  render(<AttentionWidget />);
  await vi.advanceTimersByTimeAsync(60_000);
  expect(fetch).toHaveBeenCalledTimes(2);
});

test('does not poll while the window is hidden, and reads again when it shows', async () => {
  vi.useFakeTimers();
  const fetch = mockAttention([]);
  const visibility = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden');
  render(<AttentionWidget />);
  await vi.advanceTimersByTimeAsync(120_000);
  expect(fetch).not.toHaveBeenCalled();
  visibility.mockReturnValue('visible');
  document.dispatchEvent(new Event('visibilitychange'));
  await vi.advanceTimersByTimeAsync(0);
  expect(fetch).toHaveBeenCalledTimes(1);
});

test('reasonText says why in one line', () => {
  expect(reasonText(item('a', 'danger', { violations: 2, negative_float_count: 3, late_count: 1 }))).toBe(
    '조건 위반 2건 · 여유 부족 3건 · 늦은 작업 1개',
  );
  expect(reasonText(item('b', 'danger', { finish: null, violations: 1 }))).toBe('일정을 계산할 수 없음');
});
