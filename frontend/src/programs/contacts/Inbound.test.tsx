// 들어온 문자 화면(Task 85): 주소록 아래 「모르는 번호」 묶음 · 주소록 위 「확인할 연락처 n」「확인할 보고 n」 · 오른쪽 칸의 목록과 단추.
// 번호는 가린 꼴(010-****-0199)과 peer_key 만 오간다 — 화면 어디에도 전체 번호가 없다. 사람·번호는 모두 가상.
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { useCurrentSchedule } from '../../os/currentSchedule';
import { useUiContext } from '../../os/uiContext';
import { useWindows } from '../../os/windowStore';
import Contacts from './Contacts';
import { contactCalls, mockInbox, mockWrite, stubContacts, writes } from './testKit';

const KEY_A = 'a1b2c3d4e5f6';
const KEY_B = '0123456789ab';
const FULL = /010-?0000-?019[89]|0100000019[89]/;

const peer = (over: Record<string, unknown> = {}) => ({
  peer_key: KEY_A, number_masked: '010-****-0199', last_at: '2026-11-27T00:50:00Z', messages: 2, calls: 1,
  last_line: '다시 연락 주세요 [번호]', last_kind: 'message', last_direction: 'in', blocked: false, known: false, ...over,
});
const PEER_A = peer();
const PEER_B = peer({ peer_key: KEY_B, number_masked: '010-****-0198', last_line: '누구신가요', messages: 1, calls: 0, blocked: true, last_at: '2026-11-26T00:00:00Z' });
const DETAIL_A = {
  peer_key: KEY_A, number_masked: '010-****-0199', blocked: false, known: false,
  lines: [
    { kind: 'message', id: 11, direction: 'in', at: '2026-11-27T00:30:00Z', text: '제 번호는 [번호] 입니다', status: 'received', message_kind: 'normal',
      events: [{ rule: 'admission', verdict: 'allowed', detail: 'unknown_accepted' }] },
    { kind: 'call', id: 5, direction: 'in', at: '2026-11-27T00:40:00Z', text: '용건을 남김', status: 'completed', message_kind: null, events: [] },
    { kind: 'message', id: 12, direction: 'out', at: '2026-11-27T00:41:00Z', text: '담당자가 확인 후 연락드리겠습니다.', status: 'accepted', message_kind: 'notice', events: [] },
  ],
};

const report = (over: Record<string, unknown> = {}) => ({
  id: 1, schedule_id: 1, medium: 'sms', kind: 'delay', text: '철근 반입이 하루 늦습니다', quote: '철근이 내일 들어와요', quote_found: true,
  status: 'open', contact_id: 1, contact_name: '박현장', peer_masked: null, peer_key: null, message_id: 3, call_id: null, draft_id: null,
  created_at: '2026-11-27T00:40:00Z', reviewed_by: null, reviewed_at: null, ...over,
});
const REPORTS = [
  report(),
  report({ id: 2, medium: 'call', kind: 'problem', text: '타워크레인이 멈췄습니다', quote: '크레인이 섰어요', quote_found: false, call_id: 7, message_id: null }),
  report({ id: 3, kind: 'review', text: '내용 확인 필요', quote: '', quote_found: false, draft_id: 44 }),
];
const LOOSE = [report({ id: 9, schedule_id: null, kind: 'message', contact_id: null, contact_name: null, peer_masked: '010-****-0199', peer_key: KEY_A, text: '현장 위치 문의' })];

const proposal = (over: Record<string, unknown> = {}) => ({
  id: 21, kind: 'new', schedule_id: 1, name: '최반장', role_title: '형틀 반장', company_name: '새벽형틀', number_masked: '010-****-0199',
  language: null, contact_id: null, contact_name: null, source: 'sms', created_at: '2026-11-27T00:20:00Z', ...over,
});
const PROPOSALS = [
  proposal(),
  proposal({ id: 22, kind: 'language', name: '', role_title: '', company_name: '', number_masked: null, language: 'en', contact_id: 1, contact_name: '박현장', source: 'call' }),
];

let open: ReturnType<typeof vi.fn>;
beforeEach(() => {
  stubContacts();
  open = vi.fn();
  useWindows.setState({ open, setTitle: vi.fn() } as never);
  useCurrentSchedule.setState({ current: { id: 1, name: '5층 사무동 신축' } });
});
afterEach(() => {
  cleanup();
  useCurrentSchedule.setState({ current: null });
  useUiContext.getState().reset();
  vi.unstubAllGlobals();
});

const show = () => render(<Contacts windowId="w1" params={{}} />);
const book = () => screen.getByRole('navigation', { name: '주소록' });
const posts = () => writes().map((w) => [w.method, w.url, w.body]);

test('unknown numbers are one group below the address book, with masked numbers and collapsed machine lines', async () => {
  mockInbox({ unknown: [PEER_A, PEER_B], peers: { [KEY_A]: DETAIL_A } });
  show();
  const group = await within(book()).findByRole('group', { name: '모르는 번호 · 대표번호 2' });
  expect(within(group).getByText('010-****-0199')).toBeVisible();
  expect(within(group).getByText('다시 연락 주세요 [번호]')).toBeVisible();
  expect(within(group).getByText('차단됨')).toBeVisible();

  await userEvent.click(within(group).getByRole('button', { name: /010-\*\*\*\*-0199/ }));
  const pane = await screen.findByRole('region', { name: '모르는 번호 010-****-0199' });
  expect(within(pane).getByText('제 번호는 [번호] 입니다')).toBeVisible();
  expect(within(pane).getByText('용건을 남김')).toBeVisible();
  expect(within(pane).getByText('담당자가 확인 후 연락드리겠습니다.')).toBeVisible();
  const machine = within(pane).getByText('처리 기록 1건').closest('details');
  expect(machine).not.toBeNull();
  expect(machine?.open).toBe(false);
  expect(contactCalls().some((c) => c.url === `/api/outreach/unknown/${KEY_A}?schedule_id=1`)).toBe(true);
  expect(document.body.textContent).not.toMatch(FULL);
});

test('a long unknown list can be searched by the last digits or the last line', async () => {
  const many = Array.from({ length: 8 }, (_, i) => peer({ peer_key: `${i}`.repeat(12), number_masked: `010-****-02${i}0`, last_line: `글 ${i}` }));
  mockInbox({ unknown: many });
  show();
  const group = await within(book()).findByRole('group', { name: '모르는 번호 · 대표번호 8' });
  await userEvent.type(within(group).getByRole('searchbox', { name: '모르는 번호 찾기' }), '0230');
  expect(within(group).getAllByRole('button', { name: /010-/ })).toHaveLength(1);
  expect(within(group).getByText('1 / 8')).toBeVisible();
});

test('[차단] sends the peer_key, not a number, and only admins see it', async () => {
  mockInbox({ unknown: [PEER_A], peers: { [KEY_A]: DETAIL_A } });
  show();
  await userEvent.click(await within(book()).findByRole('button', { name: /010-\*\*\*\*-0199/ }));
  const pane = await screen.findByRole('region', { name: '모르는 번호 010-****-0199' });
  await userEvent.click(within(pane).getByRole('button', { name: '차단' }));
  const confirm = within(pane).getByRole('group', { name: '차단 확인' });
  expect(confirm.textContent).toContain('걸려 오는 전화와 들어오는 문자를 받지 않습니다');
  await userEvent.type(within(confirm).getByRole('textbox', { name: '까닭' }), '광고');
  await userEvent.click(within(confirm).getByRole('button', { name: '차단하기' }));
  await waitFor(() => expect(posts()).toEqual([['POST', '/api/notify/blocked', { peer_key: KEY_A, reason: '광고' }]]));
});

test('a user (not admin) cannot block', async () => {
  stubContacts('user');
  mockInbox({ unknown: [PEER_A], peers: { [KEY_A]: DETAIL_A } });
  show();
  await userEvent.click(await within(book()).findByRole('button', { name: /010-\*\*\*\*-0199/ }));
  const pane = await screen.findByRole('region', { name: '모르는 번호 010-****-0199' });
  expect(within(pane).queryByRole('button', { name: '차단' })).toBeNull();
  expect(within(pane).getByText('차단은 관리자만 할 수 있습니다.')).toBeVisible();
});

test('[주소록에 넣기] for an unknown number posts to this project with a chosen company', async () => {
  mockInbox({ unknown: [PEER_A], peers: { [KEY_A]: DETAIL_A } });
  show();
  await userEvent.click(await within(book()).findByRole('button', { name: /010-\*\*\*\*-0199/ }));
  const pane = await screen.findByRole('region', { name: '모르는 번호 010-****-0199' });
  await userEvent.click(within(pane).getByRole('button', { name: '주소록에 넣기' }));
  const form = within(pane).getByRole('form', { name: '주소록에 넣기' });
  await userEvent.type(within(form).getByRole('textbox', { name: '이름' }), '최반장');
  await userEvent.selectOptions(within(form).getByRole('combobox', { name: '협력사' }), '10');
  mockWrite(200, { id: 99 });
  await userEvent.click(within(form).getByRole('button', { name: '넣기' }));
  await waitFor(() =>
    expect(posts()).toEqual([['POST', `/api/schedules/1/outreach/unknown/${KEY_A}/contact`, { name: '최반장', role_title: '', company_id: 10 }]]),
  );
});

test('reports: medium label, kind, quote and evidence, review lines link to the held draft', async () => {
  mockInbox({ reports: REPORTS, loose: LOOSE });
  show();
  await userEvent.click(await within(book()).findByRole('button', { name: '확인할 보고 4' }));
  const pane = await screen.findByRole('region', { name: '확인할 보고' });
  const cards = within(pane).getAllByRole('article');
  expect(cards).toHaveLength(4);
  const delay = within(pane).getByRole('article', { name: /철근 반입이 하루 늦습니다/ });
  expect(within(delay).getByText('문자로 받은 보고')).toBeVisible();
  expect(within(delay).getByText('지연')).toBeVisible();
  expect(within(delay).getByText('“철근이 내일 들어와요”')).toBeVisible();
  expect(within(delay).getByText('근거 있음')).toBeVisible();
  const crane = within(pane).getByRole('article', { name: /타워크레인이 멈췄습니다/ });
  expect(within(crane).getByText('전화로 받은 보고')).toBeVisible();
  expect(within(crane).getByText('근거 못 찾음')).toBeVisible();
  const review = within(pane).getByRole('article', { name: /내용 확인 필요/ });
  await userEvent.click(within(review).getByRole('button', { name: '초안 보기' }));
  await screen.findByRole('region', { name: '박현장 대화' });
  expect(document.body.textContent).not.toMatch(FULL);
});

test('[확인함] posts review to the project or the unassigned door and re-reads', async () => {
  mockInbox({ reports: REPORTS, loose: LOOSE });
  show();
  await userEvent.click(await within(book()).findByRole('button', { name: '확인할 보고 4' }));
  const pane = await screen.findByRole('region', { name: '확인할 보고' });
  const before = contactCalls().filter((c) => c.url.includes('/reports')).length;
  await userEvent.click(within(within(pane).getByRole('article', { name: /철근 반입/ })).getByRole('button', { name: '확인함' }));
  await userEvent.click(within(within(pane).getByRole('article', { name: /현장 위치 문의/ })).getByRole('button', { name: '확인함' }));
  await waitFor(() =>
    expect(posts()).toEqual([
      ['POST', '/api/schedules/1/outreach/reports/1/review', undefined],
      ['POST', '/api/outreach/reports/9/review', undefined],
    ]),
  );
  await waitFor(() => expect(contactCalls().filter((c) => c.url.includes('/reports')).length).toBeGreaterThan(before + 2));
});

test('[지연 기록 만들기] opens the chat with an ask that has the report but no number', async () => {
  mockInbox({ reports: [], loose: LOOSE });
  show();
  await userEvent.click(await within(book()).findByRole('button', { name: '확인할 보고 1' }));
  const pane = await screen.findByRole('region', { name: '확인할 보고' });
  await userEvent.click(within(pane).getByRole('button', { name: '지연 기록 만들기' }));
  expect(open).toHaveBeenCalledWith('chat', { ask: expect.stringContaining('현장 위치 문의') });
  const ask = (open.mock.calls[0][1] as { ask: string }).ask;
  expect(ask).toContain('모르는 번호');
  expect(ask).not.toMatch(/\d{3,}/);
});

test('reports can be searched and are grouped by kind', async () => {
  mockInbox({ reports: REPORTS, loose: LOOSE });
  show();
  await userEvent.click(await within(book()).findByRole('button', { name: '확인할 보고 4' }));
  const pane = await screen.findByRole('region', { name: '확인할 보고' });
  expect(within(pane).getByRole('heading', { name: '내용 확인 필요 1' })).toBeVisible();
  expect(within(pane).getByRole('heading', { name: '지연 1' })).toBeVisible();
  await userEvent.type(within(pane).getByRole('searchbox', { name: '보고 찾기' }), '크레인');
  expect(within(pane).getAllByRole('article')).toHaveLength(1);
});

test('proposals: add a new contact with a new company, or throw one away', async () => {
  mockInbox({ proposals: PROPOSALS });
  show();
  await userEvent.click(await within(book()).findByRole('button', { name: '확인할 연락처 2' }));
  const pane = await screen.findByRole('region', { name: '확인할 연락처' });
  const card = within(pane).getByRole('article', { name: /최반장/ });
  expect(card.textContent).toContain('형틀 반장');
  expect(card.textContent).toContain('010-****-0199');
  expect(card.textContent).toContain('문자에서');
  expect(within(card).getByRole('combobox', { name: '협력사' })).toHaveValue('new');
  expect(within(card).getByRole('textbox', { name: '새 협력사 이름' })).toHaveValue('새벽형틀');
  mockWrite(200, { id: 99 });
  await userEvent.click(within(card).getByRole('button', { name: '주소록에 넣기' }));
  await waitFor(() =>
    expect(posts()).toEqual([['POST', '/api/schedules/1/contacts/proposals/21/accept', { name: '최반장', role_title: '형틀 반장', company_name: '새벽형틀' }]]),
  );

  const lang = within(pane).getByRole('article', { name: /박현장/ });
  expect(lang.textContent).toContain('영어');
  await userEvent.click(within(lang).getByRole('button', { name: '버리기' }));
  await waitFor(() => expect(posts().at(-1)).toEqual(['POST', '/api/schedules/1/contacts/proposals/22/reject', undefined]));
});

test('a language proposal is accepted with an empty body and an existing company can be chosen', async () => {
  mockInbox({ proposals: PROPOSALS });
  show();
  await userEvent.click(await within(book()).findByRole('button', { name: '확인할 연락처 2' }));
  const pane = await screen.findByRole('region', { name: '확인할 연락처' });
  await userEvent.click(within(within(pane).getByRole('article', { name: /박현장/ })).getByRole('button', { name: '언어 바꾸기' }));
  await waitFor(() => expect(posts()).toEqual([['POST', '/api/schedules/1/contacts/proposals/22/accept', {}]]));
  const card = within(pane).getByRole('article', { name: /최반장/ });
  await userEvent.selectOptions(within(card).getByRole('combobox', { name: '협력사' }), '20');
  expect(within(card).queryByRole('textbox', { name: '새 협력사 이름' })).toBeNull();
  await userEvent.click(within(card).getByRole('button', { name: '주소록에 넣기' }));
  await waitFor(() =>
    expect(posts().at(-1)).toEqual(['POST', '/api/schedules/1/contacts/proposals/21/accept', { name: '최반장', role_title: '형틀 반장', company_id: 20 }]),
  );
});

test('no entries show when nothing is waiting', async () => {
  show();
  await screen.findByText('박현장');
  expect(within(book()).queryByRole('button', { name: /확인할/ })).toBeNull();
  expect(within(book()).queryByRole('group', { name: /모르는 번호/ })).toBeNull();
});
