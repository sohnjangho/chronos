// 차단 목록(Task 85) — 기존 GET·DELETE /api/notify/blocked. 가린 번호·까닭·막은 사람, [풀기]. 7개부터 끝자리 찾기. 번호는 모두 가상.
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test, vi } from 'vitest';
import { stubFetch } from '../../test-helpers';
import BlockedNumbers from './BlockedNumbers';

const row = (id: number, last: string, reason = '광고') => ({ id, number_masked: `010-****-${last}`, reason, created_by: '김하늘', created_at: '2026-11-27T00:00:00Z' });

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test('lists masked numbers with reason and unblocks by id, then re-reads', async () => {
  let list = [row(2, '0199', '광고 문자'), row(1, '0198', '')];
  const fetchMock = stubFetch({
    '/api/notify/blocked': () => new Response(JSON.stringify(list), { status: 200 }),
    'DELETE /api/notify/blocked/2': () => {
      list = list.filter((r) => r.id !== 2);
      return new Response(null, { status: 204 });
    },
  });
  render(<BlockedNumbers />);
  const items = await screen.findAllByRole('listitem');
  expect(items.map((li) => li.textContent)).toEqual([expect.stringContaining('010-****-0199'), expect.stringContaining('010-****-0198')]);
  expect(items[0].textContent).toContain('광고 문자');
  expect(items[1].textContent).toContain('까닭 없음');
  await userEvent.click(within(items[0]).getByRole('button', { name: '풀기' }));
  await waitFor(() => expect(screen.getAllByRole('listitem')).toHaveLength(1));
  expect(fetchMock.mock.calls.filter((c) => c[1]?.method === 'DELETE').map((c) => String(c[0]))).toEqual(['/api/notify/blocked/2']);
});

test('an empty list says so', async () => {
  stubFetch({ '/api/notify/blocked': [] });
  render(<BlockedNumbers />);
  expect(await screen.findByText('차단한 번호가 없습니다.')).toBeVisible();
});

test('seven or more can be searched by the last digits', async () => {
  stubFetch({ '/api/notify/blocked': Array.from({ length: 8 }, (_, i) => row(i + 1, `01${i}0`)) });
  render(<BlockedNumbers />);
  await screen.findAllByRole('listitem');
  await userEvent.type(screen.getByRole('searchbox', { name: '차단 번호 끝자리 찾기' }), '0130');
  expect(screen.getAllByRole('listitem')).toHaveLength(1);
  expect(screen.getByText('1 / 8개')).toBeVisible();
});
