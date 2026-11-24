// 현장 항목의 회신 후보(Task 104): GET …/outreach/replies?field_item_id= 의 받은 문자를 「문자 회신 후보: "…" — 박현장 08:40
// [회신 칸에 넣기]」로 보인다. 누르면 onUse(글)만 — 저장·진행률은 사람이 한다. 현장 관리자에게는 없다. 자료는 가상.
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { useSession } from '../../os/session';
import { json, signInAsDemo } from '../../test-helpers';
import ReplyCandidates from './ReplyCandidates';

const reply = (message_id: number, text: string, at: string, name = '박현장') => ({ message_id, contact: { name, role_title: '공무' }, text, at, answers: [] });
let rows: Record<string, unknown[]>;
let calls: [string, string][];

beforeEach(() => {
  signInAsDemo('user');
  rows = {};
  calls = [];
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(new Date('2026-11-27T03:00:00Z')); // KST 12:00
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push([init?.method ?? 'GET', url]);
    const m = /^\/api\/schedules\/7\/outreach\/replies\?field_item_id=(\d+)$/.exec(url);
    if (m) return json(200, rows[m[1]] ?? []);
    return json(404, { code: 'not_found', message: '현장 항목을 찾을 수 없습니다.', detail: null });
  }));
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  useSession.getState().logout();
});

test('shows the replies linked to this item with who and when, and [회신 칸에 넣기] only hands the text over', async () => {
  rows['5'] = [reply(31, '정상 진행 중입니다. 오후에 철근 반입 예정.', '2026-11-26T23:40:00Z')];
  rows['6'] = [reply(32, '다른 항목의 답', '2026-11-26T23:50:00Z')];
  const onUse = vi.fn();
  render(<ReplyCandidates scheduleId={7} fieldItemId={5} onUse={onUse} />);
  const box = await screen.findByRole('region', { name: '문자 회신 후보' });
  const line = within(box).getByRole('listitem');
  expect(line).toHaveTextContent('문자 회신 후보: "정상 진행 중입니다. 오후에 철근 반입 예정." — 박현장 08:40');
  expect(within(box).queryByText(/다른 항목의 답/)).toBeNull();
  await userEvent.click(within(line).getByRole('button', { name: '회신 칸에 넣기' }));
  expect(onUse).toHaveBeenCalledWith('정상 진행 중입니다. 오후에 철근 반입 예정.');
  expect(calls).toEqual([['GET', '/api/schedules/7/outreach/replies?field_item_id=5']]); // 저장하지 않는다
});

test('an older reply shows its day; more than three are folded behind a button', async () => {
  rows['5'] = [
    reply(41, '넷째', '2026-11-27T02:00:00Z'), reply(40, '셋째', '2026-11-27T01:00:00Z'),
    reply(39, '둘째', '2026-11-27T00:00:00Z'), reply(38, '첫째', '2026-11-25T00:30:00Z', '이설비'),
  ];
  render(<ReplyCandidates scheduleId={7} fieldItemId={5} onUse={vi.fn()} />);
  const box = await screen.findByRole('region', { name: '문자 회신 후보' });
  expect(within(box).getAllByRole('listitem')).toHaveLength(3);
  await userEvent.click(within(box).getByRole('button', { name: '회신 후보 4건 모두 보기' }));
  const lines = within(box).getAllByRole('listitem');
  expect(lines).toHaveLength(4);
  expect(lines[3]).toHaveTextContent('— 이설비 11월 25일 09:30');
});

test('nothing is drawn when there is no reply or it cannot be read', async () => {
  const { container } = render(<ReplyCandidates scheduleId={7} fieldItemId={5} onUse={vi.fn()} />);
  await waitFor(() => expect(calls).toHaveLength(1));
  expect(container).toBeEmptyDOMElement();
  const other = render(<ReplyCandidates scheduleId={8} fieldItemId={5} onUse={vi.fn()} />);
  await waitFor(() => expect(calls).toHaveLength(2));
  expect(other.container).toBeEmptyDOMElement();
});

test('the field-manager role does not ask and sees nothing', async () => {
  signInAsDemo('field');
  const { container } = render(<ReplyCandidates scheduleId={7} fieldItemId={5} onUse={vi.fn()} />);
  await Promise.resolve();
  expect(container).toBeEmptyDOMElement();
  expect(calls).toEqual([]);
});

test('the button is off while the card is busy', async () => {
  rows['5'] = [reply(31, '정상 진행', '2026-11-26T23:40:00Z')];
  render(<ReplyCandidates scheduleId={7} fieldItemId={5} onUse={vi.fn()} disabled />);
  expect(await screen.findByRole('button', { name: '회신 칸에 넣기' })).toBeDisabled();
});

test('a long reply is shortened on the line but [회신 칸에 넣기] hands over the whole text', async () => {
  const long = `막히는 점: ${'가'.repeat(200)}`;
  rows['5'] = [reply(31, long, '2026-11-26T23:40:00Z')];
  const onUse = vi.fn();
  render(<ReplyCandidates scheduleId={7} fieldItemId={5} onUse={onUse} />);
  const line = await screen.findByRole('listitem');
  expect(line).toHaveTextContent('…" — 박현장 08:40');
  expect(line.textContent!.length).toBeLessThan(200);
  await userEvent.click(within(line).getByRole('button', { name: '회신 칸에 넣기' }));
  expect(onUse).toHaveBeenCalledWith(long);
});
