// 받는 통화 화면(Task 96): 통화 카드의 [상대 발신] — 등급 글(내부 · 주소록 · 대표번호 · 수신 거부 · 모르는 번호 · 번호 표시 제한) ·
// 상태 글(통화 n분 · 받지 않음(시험 모드 · 차단 · 잦은 전화 · 받지 않음 설정) · 부재중) · 받지 않은 까닭 · 물은 것과 답한 것 ·
// 하네스 사건(「범위 밖 물음 n번」·「내용 확인 필요」만 붉게). 「모르는 번호」 묶음에 통화 줄도 보이고, 부재중 뒤 만든 회신 문자 초안은
// 그 사람 대화에 점선 말풍선. 세 결과(통화됨·실패·확인 필요)는 셋으로 남는다. 사람·번호는 모두 가상.
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { useCurrentSchedule } from '../../os/currentSchedule';
import { useUiContext } from '../../os/uiContext';
import { useWindows } from '../../os/windowStore';
import { CALLER_CLASS_LABEL, callerClassLabel, callStatusLabel, inboundWhy, redFlags } from '../../shared/outreach/labels';
import type { Call, OutreachEvent } from '../../shared/outreach/outreachApi';
import { call, stubCalls } from './callKit';
import CallCard, { type CallCardProps } from './CallCard';
import Contacts from './Contacts';
import { agentDraft, stubThread } from './threadKit';
import { mockInbox, PARK, stubContacts } from './testKit';
import ThreadPane from './ThreadPane';

const FULL = /01\d[-. ]?\d{3,4}[-. ]?\d{4}|0100000\d{4}/;
const ev = (rule: string, verdict: string, detail: string | null): OutreachEvent & { at: string } => ({ rule, verdict, detail, at: '2026-11-24T05:00:00+00:00' });
const admission = (detail: string, verdict = 'blocked') => ev('admission', verdict, detail);

/** 받은 통화 한 줄(가상) — 서버의 받는 통화 꼴: direction in · origin peer · 목적·질문 없음. */
const inbound = (over: Partial<Call> = {}): Call =>
  call({
    direction: 'in', origin: 'peer', origin_name: '', send_mode: null, approved_by: null, caller_class: 'contact', purpose: '', questions: [], avoid: [],
    status: 'completed', duration_s: 180, summary_ko: '철근 배근 시작일을 물어 3월 1일이라고 답함.', result_proposed: '',
    events: [admission('known_caller', 'allowed')], ...over,
  });
const gone = { duration_s: null, summary_ko: '', started_at: null, ended_at: null } as const;

const WHILE_OFF = '앱이 꺼져 있는 동안 걸려 와 받지 못했습니다';
const SCOPE_OFF = '받는 범위가 「받지 않음」이라 받지 않았습니다';
const DIAGNOSING = '음성 진단 중이라 받지 못했습니다';
const BUSY_LINE = '통화 중이라 받지 못했습니다';

const noop = () => undefined;
function showCard(c: Call, over: Partial<CallCardProps> = {}) {
  const props: CallCardProps = {
    c, scheduleId: 1, peerName: '박현장', busy: null, note: null, blocked: null, onHangup: noop, onRedial: noop, onConfirm: async () => true,
    onCancel: noop, onDiscard: noop, onOpen: noop, onSchedule: noop, onRow: noop, ...over,
  };
  return render(<CallCard {...props} />);
}
const cardEl = () => screen.getByRole('article');

beforeEach(() => {
  useWindows.setState({ open: vi.fn(), setTitle: vi.fn() } as never);
  useCurrentSchedule.setState({ current: { id: 1, name: '5층 사무동 신축' } });
});
afterEach(() => {
  cleanup();
  useCurrentSchedule.setState({ current: null });
  useUiContext.getState().reset();
  vi.unstubAllGlobals();
});

describe('the caller class words', () => {
  test('every class the server sends reads as the plan’s word', () => {
    expect(CALLER_CLASS_LABEL).toEqual({
      internal: '내부', contact: '주소록', contact_multi: '주소록', shared: '대표번호', do_not_contact: '수신 거부', unknown: '모르는 번호', withheld: '번호 표시 제한',
    });
    // 받지 않은 등급(차단·시험 모드 밖)은 상태 글이 말한다 — 등급 칩을 따로 달지 않는다. 우리가 건 통화의 상대도 없음.
    expect(['blocked', 'outside_test', 'outbound', null].map(callerClassLabel)).toEqual([null, null, null, null]);
  });

  test.each(Object.entries({ internal: '내부', contact: '주소록', shared: '대표번호', do_not_contact: '수신 거부', unknown: '모르는 번호', withheld: '번호 표시 제한' }))(
    'an inbound card from a %s caller says [상대 발신] and 「%s」',
    (cls, word) => {
      showCard(inbound({ caller_class: cls }));
      const card = cardEl();
      expect(card).toHaveAccessibleName(/^\[상대 발신\] 받은 전화/);
      expect(within(card).getByText('[상대 발신]')).toBeVisible();
      expect(within(card).getByText(word)).toBeVisible();
      expect(within(card).getByText('받은 전화')).toBeVisible();
      expect(within(card).queryByText('AI 전화')).toBeNull();
      expect(within(card).queryByText('목적')).toBeNull(); // 받은 통화에는 우리가 정한 목적이 없다
    },
  );

  test('an outbound card keeps its own head (no class chip)', () => {
    showCard(call());
    const card = cardEl();
    expect(within(card).getByText('[에이전트 발신]')).toBeVisible();
    expect(within(card).getByText('AI 전화')).toBeVisible();
    for (const word of Object.values(CALLER_CLASS_LABEL)) expect(within(card).queryByText(word)).toBeNull();
  });
});

describe('the status words', () => {
  test('every inbound status reads as its own words; refusals are never red and the three outcomes stay three', () => {
    const rows: [Partial<Call>, string, string][] = [
      [{ status: 'completed', duration_s: 180 }, '통화 3분', 'ok'],
      [{ status: 'completed', duration_s: 130 }, '통화 2분 10초', 'ok'],
      [{ status: 'rejected', ...gone, caller_class: 'outside_test', events: [admission('outside_test')] }, '받지 않음(시험 모드)', 'muted'],
      [{ status: 'rejected', ...gone, caller_class: 'blocked', events: [admission('blocked_number')] }, '받지 않음(차단)', 'muted'],
      [{ status: 'rejected', ...gone, events: [admission('burst_limit')] }, '받지 않음(잦은 전화)', 'muted'],
      [{ status: 'rejected', ...gone, events: [admission('inbound_off')] }, '받지 않음(받지 않음 설정)', 'muted'],
      [{ status: 'rejected', ...gone, caller_class: 'unknown', events: [admission('unknown_not_accepted')] }, '받지 않음', 'muted'],
      [{ status: 'rejected', ...gone, events: [] }, '받지 않음', 'muted'],
      [{ status: 'missed', ...gone, fail_reason: BUSY_LINE, events: [admission('line_busy', 'noted')] }, '부재중', 'warn'],
      [{ status: 'missed', ...gone, fail_reason: WHILE_OFF, events: [ev('call_result', 'noted', 'no_answer')] }, '부재중', 'warn'],
      [{ status: 'dialing', ...gone }, '받는 중', 'info'],
      [{ status: 'in_call', ...gone }, '통화 중', 'info'],
      [{ status: 'failed', ...gone, fail_reason: '음성 서버 오류' }, '실패 — 음성 서버 오류', 'bad'],
    ];
    for (const [over, text, tone] of rows) expect(callStatusLabel(inbound(over)), text).toEqual({ text, tone });
    // 거는 통화의 글은 그대로
    expect(callStatusLabel(call({ status: 'dialing' })).text).toBe('거는 중');
    expect(callStatusLabel(call({ status: 'no_answer' })).text).toBe('받지 않음');
  });

  test('a card shows the status chip in the status colour (refused calls muted, missed amber, none red)', () => {
    showCard(inbound({ status: 'rejected', ...gone, caller_class: 'blocked', events: [admission('blocked_number')] }));
    const chip = within(cardEl()).getByText('받지 않음(차단)');
    expect(chip).toHaveClass('th-chip', 'is-muted');
    expect(cardEl().querySelector('.is-bad')).toBeNull();
    cleanup();
    showCard(inbound({ status: 'missed', ...gone, fail_reason: WHILE_OFF }));
    expect(within(cardEl()).getByText('부재중')).toHaveClass('th-chip', 'is-warn');
    expect(cardEl().querySelector('.is-bad')).toBeNull();
  });
});

describe('why a call was not taken', () => {
  test.each([WHILE_OFF, SCOPE_OFF, DIAGNOSING, BUSY_LINE, '받을 준비를 하지 못해 받지 않았습니다'])('a missed call says 「받지 못한 까닭: %s」', (why) => {
    showCard(inbound({ status: 'missed', ...gone, fail_reason: why }));
    expect(within(cardEl()).getByText(`받지 못한 까닭: ${why}`)).toBeVisible();
  });

  test('a missed call caught by the line limit with no text falls back to the admission words', () => {
    expect(inboundWhy(inbound({ status: 'missed', ...gone, fail_reason: null, events: [admission('line_busy', 'noted')] }))).toBe('동시 통화 한도');
  });

  test('a refused call whose status does not already say why gives the admission reason; the four named ones do not repeat it', () => {
    showCard(inbound({ status: 'rejected', ...gone, caller_class: 'unknown', fail_reason: '받지 않고 거절했습니다', events: [admission('unknown_not_accepted')] }));
    expect(within(cardEl()).getByText('받지 않은 까닭: 모르는 번호 — 받지 않음')).toBeVisible();
    cleanup();
    showCard(inbound({ status: 'rejected', ...gone, fail_reason: '받지 않고 거절했습니다', events: [admission('burst_limit')] }));
    expect(within(cardEl()).queryByText(/받지 않은 까닭/)).toBeNull();
    expect(within(cardEl()).queryByText('받지 않고 거절했습니다')).toBeNull();
  });

  test('an inbound call that was not taken offers no redial, no transcript and no 「자동으로 다시 걸지 않습니다」', () => {
    for (const over of [{ status: 'missed' as const, fail_reason: WHILE_OFF }, { status: 'rejected' as const, events: [admission('inbound_off')] }, { status: 'failed' as const, fail_reason: '음성 서버 오류' }]) {
      showCard(inbound({ ...gone, ...over }));
      expect(within(cardEl()).queryByRole('button', { name: '다시 걸기' })).toBeNull();
      expect(within(cardEl()).queryByRole('button', { name: '받아쓰기 보기' })).toBeNull();
      expect(within(cardEl()).queryByText(/자동으로 다시 걸지 않습니다/)).toBeNull();
      cleanup();
    }
  });
});

describe('what was asked and answered', () => {
  test('an answered inbound call lists 「물은 것」 and 「답한 것」 with the evidence state', () => {
    showCard(inbound({
      answers: [
        { question: '철근 배근 언제 시작해요?', answer: '3월 1일 시작', quote: '철근 배근 언제 시작해요', quote_found: true },
        { question: '토요일 작업 되나요?', answer: '확인 후 연락', quote: '', quote_found: false },
      ],
    }));
    const list = within(cardEl()).getByRole('list', { name: '물은 것과 답한 것' });
    const items = within(list).getAllByRole('listitem');
    expect(items).toHaveLength(2);
    expect(within(items[0]).getByText('물은 것')).toBeVisible();
    expect(within(items[0]).getByText('철근 배근 언제 시작해요?')).toBeVisible();
    expect(within(items[0]).getByText('답한 것')).toBeVisible();
    expect(within(items[0]).getByText('3월 1일 시작')).toBeVisible();
    expect(within(items[1]).getByText('확인 필요 — 근거 말 없음')).toHaveClass('is-warn');
  });

  test('an outbound call keeps 「질문별 답」', () => {
    showCard(call({ answers: [{ question: '토요일 인원', answer: '6명', quote: '6명 됩니다', quote_found: true }] }));
    expect(within(cardEl()).getByRole('list', { name: '질문별 답' })).toBeVisible();
  });
});

describe('harness events in red', () => {
  const denied = (n: number) => Array.from({ length: n }, () => ev('scope_denied', 'blocked', 'tool=schedule_fact'));

  test('「범위 밖 물음 n번」 and 「내용 확인 필요」 are the only red lines, outside the folded record', () => {
    expect(redFlags([...denied(3), ev('unsupported_date', 'noted', '도구 결과에 없는 날짜 1')])).toEqual(['범위 밖 물음 3번', '내용 확인 필요']);
    for (const flag of ['unsupported_answer', 'out_of_scope_said', 'money_said', 'disclosed_to_unknown']) expect(redFlags([ev(flag, 'noted', null)])).toEqual(['내용 확인 필요']);
    expect(redFlags([admission('known_caller', 'allowed'), ev('call_result', 'noted', 'no_answer'), ev('silence', 'noted', null), ev('tool:schedule_fact', 'allowed', 'tool=schedule_fact')])).toEqual([]);

    showCard(inbound({ events: [admission('known_caller', 'allowed'), ...denied(3), ev('money_said', 'noted', '금액 1')] }));
    const card = cardEl();
    const flags = within(card).getByRole('group', { name: '확인할 사건' });
    expect(within(flags).getByText('범위 밖 물음 3번')).toHaveClass('th-chip', 'is-bad');
    expect(within(flags).getByText('내용 확인 필요')).toHaveClass('th-chip', 'is-bad');
    expect(flags.closest('details')).toBeNull(); // 접힌 처리 기록 안이 아니라 카드에 보인다
    expect(card.querySelectorAll('.is-bad')).toHaveLength(2);
  });

  test('the same red lines show on an outbound call', () => {
    showCard(call({ events: [ev('unsupported_answer', 'noted', null)] }));
    expect(within(cardEl()).getByText('내용 확인 필요')).toHaveClass('is-bad');
  });

  test('an outbound call whose outcome is unknown is amber, never red, and never a failure', () => {
    const unsure = [ev('delivery', 'allowed', '통로가 받았습니다'), ev('delivery', 'noted', '보냈는지 확인 필요')];
    showCard(call({ status: 'failed', ...gone, fail_reason: '음성 통화 오류', events: unsure }));
    const card = cardEl();
    expect(within(card).getByText('확인 필요 — 걸렸는지 알 수 없음')).toHaveClass('is-warn');
    expect(card.querySelector('.is-bad')).toBeNull();
    expect(within(card).queryByText(/^실패/)).toBeNull();
    expect(within(card).queryByRole('group', { name: '확인할 사건' })).toBeNull();
  });
});

describe('in the person’s call tab', () => {
  test('inbound and outbound calls sit together; search finds the class and the reason; no full number anywhere', async () => {
    const rows = [
      call({ id: 1, created_at: '2026-11-24T01:00:00Z', started_at: '2026-11-24T01:00:00Z' }),
      inbound({ id: 2, created_at: '2026-11-24T02:00:00Z', started_at: '2026-11-24T02:00:00Z' }),
      inbound({ id: 3, status: 'missed', ...gone, fail_reason: WHILE_OFF, created_at: '2026-11-24T03:00:00Z' }),
      inbound({ id: 4, status: 'rejected', ...gone, events: [admission('burst_limit')], created_at: '2026-11-24T03:10:00Z' }),
      inbound({ id: 5, caller_class: 'shared', created_at: '2026-11-24T03:20:00Z', started_at: '2026-11-24T03:20:00Z', summary_ko: '대표번호로 걸려 온 통화' }),
      inbound({ id: 6, caller_class: 'internal', created_at: '2026-11-24T03:30:00Z', started_at: '2026-11-24T03:30:00Z', summary_ko: '내부 통화' }),
    ];
    stubCalls(rows);
    render(<ThreadPane scheduleId={1} person={PARK} tab="calls" onChanged={noop} />);
    const log = await screen.findByRole('log', { name: '통화 기록' });
    await waitFor(() => expect(within(log).getAllByRole('article')).toHaveLength(6));
    expect(within(log).getAllByText('[상대 발신]')).toHaveLength(5);
    expect(within(log).getByText(`받지 못한 까닭: ${WHILE_OFF}`)).toBeVisible();
    const search = screen.getByRole('searchbox', { name: '통화 찾기' });
    await userEvent.type(search, '대표번호');
    await waitFor(() => expect(within(log).getAllByRole('article')).toHaveLength(1));
    await userEvent.clear(search);
    await userEvent.type(search, '꺼져 있는');
    await waitFor(() => expect(within(log).getAllByRole('article')).toHaveLength(1));
    await userEvent.clear(search);
    await userEvent.type(search, '잦은 전화');
    await waitFor(() => expect(within(log).getAllByRole('article')).toHaveLength(1));
    expect(document.body.innerHTML).not.toMatch(FULL);
  });
});

describe('the unknown-number group', () => {
  const KEY = 'a1b2c3d4e5f6';
  const PEER = {
    peer_key: KEY, number_masked: '010-****-0199', last_at: '2026-11-27T00:50:00Z', messages: 1, calls: 3, last_line: '용건을 남김',
    last_kind: 'call', last_direction: 'in', blocked: false, known: false,
  };
  const line = (over: Record<string, unknown>) => ({ kind: 'call', id: 1, direction: 'in', at: '2026-11-27T00:30:00Z', text: '', status: 'completed', message_kind: null, events: [], ...over });
  const DETAIL = {
    peer_key: KEY, number_masked: '010-****-0199', blocked: false, known: false,
    lines: [
      line({ id: 1, status: 'rejected', events: [admission('unknown_not_accepted')] }),
      line({ id: 2, status: 'missed', at: '2026-11-27T00:35:00Z', events: [ev('call_result', 'noted', 'no_answer')] }),
      line({ id: 3, status: 'completed', at: '2026-11-27T00:40:00Z', text: '용건을 남김', events: [admission('unknown_accepted', 'allowed'), ...Array.from({ length: 3 }, () => ev('scope_denied', 'blocked', 'tool=schedule_fact'))] }),
      { kind: 'message', id: 9, direction: 'out', at: '2026-11-27T00:41:00Z', text: '담당자가 확인 후 연락드리겠습니다.', status: 'accepted', message_kind: 'notice', events: [] },
    ],
  };

  test('calls show in the group and in the pane with the inbound words; only the scope line is red; no full number', async () => {
    stubContacts();
    mockInbox({ unknown: [PEER], peers: { [KEY]: DETAIL } });
    render(<Contacts windowId="w1" params={{}} />);
    const book = screen.getByRole('navigation', { name: '주소록' });
    const group = await within(book).findByRole('group', { name: '모르는 번호 1' });
    const row = within(group).getByRole('button', { name: /010-\*\*\*\*-0199/ });
    expect(row).toHaveTextContent('전화 — 용건을 남김');
    expect(row).toHaveTextContent('전화 3');
    await userEvent.click(row);
    const pane = await screen.findByRole('region', { name: '모르는 번호 010-****-0199' });
    const lines = within(within(pane).getByRole('list', { name: '주고받은 줄' })).getAllByRole('listitem').filter((li) => li.classList.contains('ct-ib-line'));
    expect(lines).toHaveLength(4);
    expect(lines[0]).toHaveTextContent('받은 전화');
    expect(lines[0]).toHaveTextContent('받지 않음');
    expect(within(lines[0]).getByText('받지 않은 까닭: 모르는 번호 — 받지 않음')).toBeVisible();
    expect(within(lines[0]).queryByText('요약 없음')).toBeNull();
    expect(lines[1]).toHaveTextContent('부재중');
    expect(lines[2]).toHaveTextContent('통화함');
    expect(within(lines[2]).getByText('범위 밖 물음 3번')).toHaveClass('is-bad');
    expect(pane.querySelectorAll('.is-bad')).toHaveLength(1);
    expect(lines[3]).toHaveTextContent('보낸 문자');
    expect(document.body.innerHTML).not.toMatch(FULL);
  });
});

describe('the reply draft after a missed call', () => {
  test('sits in that person’s conversation as a dotted bubble, not sent', async () => {
    const MISSED_SMS = 'ChronOS AI 비서입니다. 방금 주신 전화를 받지 못했습니다. 담당자가 확인 후 연락드리겠습니다.';
    stubThread({ 1: [agentDraft({ id: 30, chat: null, kind: 'normal', body: MISSED_SMS, created_at: '2026-11-24T03:01:00Z' })] });
    render(<ThreadPane scheduleId={1} person={PARK} tab="messages" onChanged={noop} />);
    const bubble = (await screen.findByText(MISSED_SMS)).closest('article') as HTMLElement;
    expect(bubble).toHaveClass('is-draft');
    expect(within(bubble).getByText('에이전트 초안')).toBeVisible();
    expect(within(bubble).queryByText('도착')).toBeNull();
  });
});

// 서버의 글과 같은지 — 파이썬 파일을 글로 읽는다(labels.test.ts 와 같은 방법). 바뀌면 조용히 지나가지 않고 깨진다.
const fsModule = 'node:fs';
const { readFileSync } = (await import(/* @vite-ignore */ fsModule)) as { readFileSync(path: URL, encoding: 'utf8'): string };
const here = import.meta.url;
const backend = (path: string) => readFileSync(new URL(`../../../../backend/${path}`, here), 'utf8');

describe('the words are the server’s', () => {
  test('the red review flags are harness.types.REVIEW_FLAGS', () => {
    const src = backend('app/outreach/harness/types.py');
    const block = /REVIEW_FLAGS: frozenset\[str\] = frozenset\(\{([\s\S]*?)\}\)/.exec(src);
    expect(block, 'REVIEW_FLAGS 를 찾지 못함').not.toBeNull();
    const names = [...block![1].matchAll(/"([a-z_]+)"/g)].map((m) => m[1]).sort();
    for (const n of names) expect(redFlags([ev(n, 'noted', null)]), n).toEqual(['내용 확인 필요']);
    expect(names).toHaveLength(5);
    expect(/"scope_denied"/.test(src)).toBe(true);
  });

  test('the missed reasons tested above are the inbound module’s texts', () => {
    const src = backend('app/outreach/voice/inbound.py');
    for (const text of [WHILE_OFF, SCOPE_OFF, DIAGNOSING, BUSY_LINE]) expect(src, text).toContain(`"${text}"`);
  });
});
