import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeAll, beforeEach, expect, test, vi } from 'vitest';
import { registerPrograms } from '../programs';
import { json, signInAs, stubFetch } from '../test-helpers';
import Desktop from './Desktop';
import { useApprovals } from './approvals';
import { useSession } from './session';
import { useWindows } from './windowStore';

const ago = (min: number) => new Date(Date.now() - min * 60_000).toISOString();
const item = (id: number, title: string, min: number) => ({ id, title, created_at: ago(min) });

beforeAll(() => registerPrograms());
beforeEach(() => signInAs('user', '김민지'));
afterEach(() => {
  vi.unstubAllGlobals();
  useWindows.getState().reset();
  useApprovals.setState({ pending: 0 });
  useSession.getState().logout();
});

test('승인 대기 widget lists the top 3 pending with age and opens the approval', async () => {
  stubFetch({
    '/api/approvals/count': { pending: 4 },
    '/api/schedules': [],
    '/api/approvals?status=pending': {
      mode: 'important',
      items: [item(11, '만회 계획', 5), item(10, '내 규칙 저장', 120), item(9, '준공 변경', 60 * 49), item(8, '네 번째', 60 * 50)],
    },
  });
  render(<Desktop />);
  const widget = await screen.findByRole('region', { name: '승인 대기' });
  expect(await within(widget).findByText('만회 계획')).toBeVisible();
  expect(within(widget).getByText('4')).toBeVisible();
  expect(within(widget).getByText('5분 전')).toBeVisible();
  expect(within(widget).getByText('2시간 전')).toBeVisible();
  expect(within(widget).getByText('2일 전')).toBeVisible();
  expect(within(widget).queryByText('네 번째')).toBeNull();
  await userEvent.click(within(widget).getByRole('button', { name: /만회 계획/ }));
  expect(useWindows.getState().wins).toMatchObject([{ programId: 'approvals', params: { id: '11' } }]);
});

test('승인 대기 widget is hidden when nothing is pending', async () => {
  const fetch = stubFetch({ '/api/approvals/count': { pending: 0 }, '/api/schedules': [] });
  render(<Desktop />);
  await vi.waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/approvals/count', expect.anything()));
  expect(screen.queryByRole('region', { name: '승인 대기' })).toBeNull();
});

test('the widget refetches on every refresh and ignores an answer that arrives late', async () => {
  let answerFirst: (r: Response) => void = () => {};
  const firstAnswer: Promise<Response> = new Promise((resolve) => {
    answerFirst = resolve;
  });
  let listCalls = 0;
  stubFetch({
    '/api/approvals/count': { pending: 2 },
    '/api/schedules': [],
    '/api/approvals?status=pending': () => {
      listCalls += 1;
      if (listCalls === 1) return firstAnswer;
      return json(200, { mode: 'important', items: [item(2, '새 건', 1)] });
    },
  });
  render(<Desktop />);
  await vi.waitFor(() => expect(listCalls).toBe(1));
  fireEvent.focus(window);
  expect(await screen.findByText('새 건')).toBeVisible();
  await act(async () => answerFirst(json(200, { mode: 'important', items: [item(1, '옛 건', 9)] })));
  expect(screen.queryByText('옛 건')).toBeNull();
  expect(screen.getByText('새 건')).toBeVisible();
});
