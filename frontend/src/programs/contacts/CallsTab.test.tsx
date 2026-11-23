// 연락처 통화 탭(Task 92, 시안 ②): 날짜 줄 아래 통화 카드 — 누가 걸었나·「AI 전화」·상태·시각·승인한 사람, 목적, 요약, 결과(에이전트 제안 ·
// 사람이 확정), 질문별 답과 근거(근거 없는 답은 「확인 필요」), 하네스 사건(말풍선과 같은 접힌 줄), 연결된 작업, [받아쓰기 보기][녹음 듣기]
// [결과 확정][다시 걸기]. 통화하는 중에는 2초마다 받아쓰기를 잇고 [통화 끊기]. 세 결과(걸림·실패·확인 필요)는 셋으로 남는다.
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { useCurrentSchedule } from '../../os/currentSchedule';
import { register, type ProgramManifest } from '../../os/registry';
import { useUiContext } from '../../os/uiContext';
import { useWindows } from '../../os/windowStore';
import type { Call } from '../../shared/outreach/outreachApi';
import css from './calls.css?raw';
import {
  call, callGets, callPosts, change, draftCall, failCall, holdCall, nextPlace, onEveryDetail, rowOf, setTranscript, speak, stubCalls,
} from './callKit';
import { LIVE_POLL_MS } from './CallsTab';
import Contacts from './Contacts';
import { JUNG, PARK } from './testKit';
import ThreadPane from './ThreadPane';

const open = vi.fn();
const onChanged = vi.fn();

beforeEach(() => {
  open.mockReset();
  onChanged.mockReset();
  useWindows.setState({ open, setTitle: vi.fn() } as never);
  useCurrentSchedule.setState({ current: { id: 1, name: '5층 사무동 신축' } });
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  useCurrentSchedule.setState({ current: null });
  useUiContext.getState().reset();
  vi.unstubAllGlobals();
});

const show = (person = PARK) => render(<ThreadPane scheduleId={1} person={person} tab="calls" onChanged={onChanged} />);
const list = () => screen.getByRole('log', { name: '통화 기록' });
const cards = () => within(list()).queryAllByRole('article');
const card = (text: string | RegExp) => {
  const found = cards().filter((a) => (typeof text === 'string' ? a.textContent?.includes(text) : text.test(a.textContent ?? '')));
  expect(found, `카드 「${String(text)}」`).toHaveLength(1);
  return found[0];
};
const findCard = async (text: string | RegExp) => {
  await waitFor(() => card(text));
  return card(text);
};
const btn = (el: HTMLElement, name: string | RegExp) => within(el).getByRole('button', { name });
const noBtn = (el: HTMLElement, name: string | RegExp) => expect(within(el).queryByRole('button', { name })).toBeNull();
const FULL_NUMBER = /01\d[-. ]?\d{3,4}[-. ]?\d{4}/;

const UNSURE_EVENTS: Call['events'] = [
  { rule: 'channel_choice', verdict: 'allowed', detail: 'call', at: '2026-11-24T05:00:00+00:00' },
  { rule: 'delivery', verdict: 'allowed', detail: '통로가 받았습니다', at: '2026-11-24T05:00:01+00:00' },
  { rule: 'delivery', verdict: 'noted', detail: '보냈는지 확인 필요', at: '2026-11-24T05:03:00+00:00' },
];

/** 모든 상태의 통화 줄(가상). */
function everyStatus(): Call[] {
  const gone = { duration_s: null, summary_ko: '', result_proposed: '', started_at: null, ended_at: null };
  return [
    call({ id: 1, status: 'no_answer', ...gone, created_at: '2026-11-23T07:05:00Z', started_at: '2026-11-23T07:05:00Z', purpose: 'A1210 만회안 B 가능 여부 확인' }),
    call({ id: 2, status: 'completed', duration_s: 130, purpose: '토요일 인원 확인' }),
    call({ id: 3, status: 'in_call', ...gone, purpose: '지금 통화하는 목적' }),
    call({ id: 4, status: 'blocked_hours', ...gone, scheduled_at: '2026-11-29T23:00:00Z', purpose: '밤에 걸려던 목적' }),
    call({ id: 5, status: 'blocked_test', ...gone, purpose: '시험 모드 목적' }),
    call({ id: 6, status: 'failed', ...gone, fail_reason: '음성 통화 오류 — 전화가 걸렸는지 확인 필요', events: UNSURE_EVENTS, purpose: '모르는 결과 목적' }),
    call({ id: 7, status: 'failed', ...gone, fail_reason: '받는 번호가 없거나 맞지 않아 걸지 않았습니다', purpose: '실패한 목적' }),
    call({ id: 8, status: 'busy', ...gone, purpose: '상대가 통화 중이던 목적' }),
    call({ id: 9, status: 'scheduled', ...gone, scheduled_at: '2026-11-29T23:00:00Z', purpose: '예약한 목적' }),
    call({ id: 10, status: 'queued', ...gone, purpose: '줄에 넣은 목적' }),
    call({ id: 11, status: 'dialing', ...gone, purpose: '거는 중인 목적' }),
    draftCall({ id: 12, purpose: '사람이 쓴 초안 목적' }),
    call({ id: 13, status: 'completed', origin: 'user', origin_name: '김공정', send_mode: 'manual', approved_by: null, duration_s: 45, purpose: '직접 건 목적' }),
    call({ id: 14, status: 'completed', send_mode: 'delegated', approved_by: null, duration_s: 3700, purpose: '위임으로 건 목적' }),
  ];
}

describe('call cards (시안 ②)', () => {
  test('every status reads as its own words; the three outcomes stay three', async () => {
    stubCalls(everyStatus());
    show();
    const status = (purpose: string, text: string) => expect(card(purpose).textContent).toContain(text);
    await findCard('A1210 만회안 B');
    status('A1210 만회안 B', '받지 않음');
    status('토요일 인원 확인', '통화 2분 10초');
    status('지금 통화하는 목적', '통화 중');
    status('밤에 걸려던 목적', '근무시간 밖으로 막힘');
    status('시험 모드 목적', '시험 모드로 걸지 않음');
    status('모르는 결과 목적', '확인 필요 — 걸렸는지 알 수 없음');
    status('실패한 목적', '실패 — 받는 번호가 없거나 맞지 않아 걸지 않았습니다');
    status('상대가 통화 중이던 목적', '상대 통화 중');
    status('예약한 목적', '예약됨 11/30(월) 08:00');
    status('줄에 넣은 목적', '걸 차례를 기다리는 중');
    status('거는 중인 목적', '거는 중');
    status('사람이 쓴 초안 목적', '아직 걸지 않음');
    status('위임으로 건 목적', '통화 1시간 1분 40초');
    // 「확인 필요」는 실패도 성공도 아니다
    const unsure = card('모르는 결과 목적');
    expect(unsure.querySelector('.th-chip.is-warn')?.textContent).toBe('확인 필요 — 걸렸는지 알 수 없음');
    expect(unsure.textContent).not.toMatch(/실패 —/);
    expect(card('실패한 목적').querySelector('.th-chip.is-bad')?.textContent).toMatch(/^실패 — /);
  });

  test('who called, the AI-call chip, the time and who approved; no answer is never redialled by itself', async () => {
    stubCalls(everyStatus());
    show();
    const missed = await findCard('A1210 만회안 B');
    expect(missed.textContent).toContain('[에이전트 발신]');
    expect(within(missed).getByText('AI 전화')).toBeVisible();
    expect(missed.textContent).toContain('16:05 · 김공정 승인');
    expect(missed.textContent).toContain('자동으로 다시 걸지 않습니다');
    expect(btn(missed, '다시 걸기')).toBeEnabled();
    noBtn(missed, '받아쓰기 보기'); // 받지 않은 통화에는 받아쓰기가 없다
    expect(card('직접 건 목적').textContent).toContain('[김공정 발신]');
    expect(card('직접 건 목적').textContent).not.toContain('승인');
    expect(card('위임으로 건 목적').textContent).toContain('[에이전트 발신 · 위임]');
    // 날짜 줄(KST) — 오래된 것이 위
    const days = within(list()).getAllByRole('heading', { level: 3 }).map((h) => h.textContent);
    expect(days).toEqual(['2026년 11월 23일 월요일', '2026년 11월 24일 화요일']);
  });

  test('a completed card: summary, result proposed by the agent, answers with evidence, linked task, buttons', async () => {
    register({ id: 'schedule-table', name: '스케줄' } as ProgramManifest);
    stubCalls([
      call({
        id: 2, has_recording: true, activity: { id: 'A1210', name: '지상 골조' },
        answers: [
          { question: '이번 주말 인원 투입 가능한지', answer: '토요일 6명 가능', quote: '토요일은 6명 됩니다', quote_found: true },
          { question: '안 되면 가장 빠른 날', answer: '월요일', quote: '월요일 연장', quote_found: false },
          { question: '자재 반입', answer: '모름', quote: '', quote_found: false },
        ],
      }),
    ]);
    show();
    const c = await findCard('토요일 6명 가능, 일요일은 불가.');
    expect(c.textContent).toContain('결과: 조건부 가능 (에이전트 제안 · 확정 전)');
    const answers = within(c).getByRole('list', { name: '질문별 답' });
    const [first, second, third] = within(answers).getAllByRole('listitem');
    expect(first.textContent).toContain('토요일 6명 가능');
    expect(first.textContent).toContain('「토요일은 6명 됩니다」');
    expect(first.textContent).not.toContain('확인 필요');
    // 근거가 받아쓰기에 없거나 근거 말이 없는 답은 「확인 필요」 — 사실처럼 보이지 않는다
    expect(within(second).getByText(/확인 필요/)).toHaveClass('is-warn');
    expect(within(third).getByText(/확인 필요/)).toHaveClass('is-warn');
    await userEvent.click(btn(c, 'A1210 지상 골조 — 스케줄에서 열기'));
    expect(open).toHaveBeenCalledWith('schedule-table', { id: '1', activity: 'A1210' });
    for (const name of ['받아쓰기 보기', '녹음 듣기', '결과 확정']) expect(btn(c, name)).toBeEnabled();
    noBtn(c, '다시 걸기');
  });

  test('harness events are a folded line like the message bubbles', async () => {
    stubCalls([
      call({ id: 6, status: 'failed', fail_reason: '음성 통화 오류 — 전화가 걸렸는지 확인 필요', events: UNSURE_EVENTS, duration_s: null }),
      call({
        id: 7, status: 'no_answer', duration_s: null,
        events: [
          { rule: 'channel_choice', verdict: 'allowed', detail: 'call', at: null },
          { rule: 'recheck_before_dial', verdict: 'allowed', detail: 'ok', at: null },
          { rule: 'call_result', verdict: 'noted', detail: 'no_answer', at: null },
        ],
        purpose: '받지 않은 통화',
      }),
    ]);
    show();
    const c = await findCard('받지 않은 통화');
    const folded = c.querySelector('details.th-events') as HTMLDetailsElement;
    expect(folded).not.toBeNull();
    expect(folded.open).toBe(false);
    await userEvent.click(within(folded).getByText(/기록 3건/));
    const lines = within(folded).getAllByRole('listitem').map((li) => li.textContent);
    expect(lines).toEqual(['지나감통로 고르기 — 전화', '지나감걸기 직전 다시 확인 — 이상 없음', '메모통화 결과 — 받지 않음']);
  });

  test('[결과 확정] posts the result a person wrote and the card shows who confirmed it', async () => {
    stubCalls([call({ id: 2 })]);
    show();
    const c = await findCard('토요일 6명 가능');
    await userEvent.click(btn(c, '결과 확정'));
    const box = within(c).getByRole('textbox', { name: '확정할 결과' });
    expect(box).toHaveValue('조건부 가능');
    await userEvent.clear(box);
    await userEvent.type(box, '토요일만 가능');
    await userEvent.dblClick(btn(c, '확정'));
    await waitFor(() => expect(callPosts('confirm')).toHaveLength(1));
    expect(callPosts('confirm')[0]).toMatchObject({ url: '/api/schedules/1/outreach/calls/2/confirm', body: { result: '토요일만 가능' } });
    await waitFor(() => expect(card('토요일 6명 가능').textContent).toContain('결과: 토요일만 가능 (김하늘 확정 · 에이전트 제안 「조건부 가능」)'));
    expect(onChanged).toHaveBeenCalled();
  });

  test('a confirm the server refuses shows its words and keeps the editor', async () => {
    stubCalls([call({ id: 2 })]);
    show();
    const c = await findCard('토요일 6명 가능');
    await userEvent.click(btn(c, '결과 확정'));
    failCall((r) => r.url.endsWith('/confirm'), 409, { code: 'not_completed', message: '통화가 끝난 뒤에만 결과를 확정할 수 있습니다.' });
    await userEvent.click(btn(c, '확정'));
    expect(await within(c).findByText('통화가 끝난 뒤에만 결과를 확정할 수 있습니다.')).toHaveClass('is-bad');
    expect(within(c).getByRole('textbox', { name: '확정할 결과' })).toBeVisible();
  });
});

describe('live call', () => {
  test('the transcript continues every 2 s while the call is live, [통화 끊기] asks once, and reading stops when it ends', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
    stubCalls([call({ id: 5, status: 'in_call', duration_s: null, summary_ko: '', result_proposed: '', ended_at: null, purpose: '지금 통화' })]);
    setTranscript(5, [
      { role: 'agent', text: '안녕하세요, ChronOS AI 비서입니다. 이 통화는 기록됩니다.', t: 0 },
      { role: 'peer', text: '네 말씀하세요', t: 3 },
    ]);
    show();
    const c = await findCard('지금 통화');
    const tr = await within(c).findByRole('log', { name: '받아쓰기' });
    await waitFor(() => expect(within(tr).getAllByRole('listitem')).toHaveLength(2));
    expect(within(tr).getAllByRole('listitem')[1].textContent).toContain('박현장');
    speak(5, { role: 'peer', text: '토요일 6명 가능합니다', t: 9 });
    await act(async () => void vi.advanceTimersByTime(LIVE_POLL_MS));
    await waitFor(() => expect(within(tr).getAllByRole('listitem')).toHaveLength(3));
    expect(within(tr).getByText('토요일 6명 가능합니다')).toBeVisible();

    const release = holdCall((r) => r.url.endsWith('/hangup'));
    const hang = btn(c, '통화 끊기');
    await userEvent.dblClick(hang);
    await userEvent.click(hang);
    expect(hang).toBeDisabled();
    release();
    await waitFor(() => expect(callPosts('hangup')).toHaveLength(1));

    change(5, { status: 'completed', duration_s: 40, ended_at: '2026-11-24T05:16:00Z' });
    await act(async () => void vi.advanceTimersByTime(LIVE_POLL_MS));
    await waitFor(() => expect(card('지금 통화').textContent).toContain('통화 40초'));
    noBtn(card('지금 통화'), '통화 끊기');
    const n = callGets(5).length;
    await act(async () => void vi.advanceTimersByTime(LIVE_POLL_MS * 3));
    expect(callGets(5)).toHaveLength(n);
  });

  test('a hang-up the server refuses shows its words', async () => {
    stubCalls([call({ id: 5, status: 'dialing', duration_s: null, purpose: '거는 통화' })]);
    failCall((r) => r.url.endsWith('/hangup'), 409, { code: 'not_live', message: '진행 중인 통화가 아닙니다.' });
    show();
    const c = await findCard('거는 통화');
    await userEvent.click(btn(c, '통화 끊기'));
    expect(await within(c).findByText('진행 중인 통화가 아닙니다.')).toBeVisible();
  });

  test('the live card follows the state the worker writes (queued → dialing → in call)', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
    stubCalls([call({ id: 5, status: 'queued', duration_s: null, purpose: '줄의 통화' })]);
    let step = 0;
    onEveryDetail((c) => {
      step += 1;
      if (step === 2) c.status = 'dialing';
      if (step === 3) c.status = 'in_call';
    });
    show();
    await findCard('걸 차례를 기다리는 중');
    await act(async () => void vi.advanceTimersByTime(LIVE_POLL_MS));
    await findCard('거는 중');
    await act(async () => void vi.advanceTimersByTime(LIVE_POLL_MS));
    await waitFor(() => expect(card('줄의 통화').textContent).toContain('통화 중'));
  });
});

describe('transcript', () => {
  test('a 200-line transcript scrolls inside its own box, not the window', async () => {
    stubCalls([call({ id: 2 })]);
    setTranscript(2, Array.from({ length: 200 }, (_, i) => ({ role: i % 2 ? 'peer' : 'agent', text: `가상 줄 ${i + 1}`, t: i * 2 })));
    show();
    const c = await findCard('토요일 6명 가능');
    await userEvent.click(btn(c, '받아쓰기 보기'));
    const tr = await within(c).findByRole('log', { name: '받아쓰기' });
    await waitFor(() => expect(within(tr).getAllByRole('listitem')).toHaveLength(200));
    expect(tr).toHaveClass('cl-tr-scroll');
    expect(tr).toHaveAttribute('tabindex', '0');
    expect(css).toMatch(/\.cl-tr-scroll\s*\{[^}]*max-height:[^;]+;/);
    expect(css).toMatch(/\.cl-tr-scroll\s*\{[^}]*overflow-y:\s*auto/);
    expect(css).toMatch(/\.cl-tr-scroll\s*\{[^}]*overflow-x:\s*hidden/);
    expect(within(tr).getAllByRole('listitem')[199].textContent).toContain('6:38');
    await userEvent.click(btn(c, '받아쓰기 닫기'));
    expect(within(c).queryByRole('log', { name: '받아쓰기' })).toBeNull();
  });

  test('a long call list scrolls in its pane, has a search box and keeps the day lines', async () => {
    const many = Array.from({ length: 40 }, (_, i) =>
      call({ id: 100 + i, purpose: i === 17 ? '타워크레인 일정 확인' : `가상 목적 ${i}`, created_at: `2026-11-${String(1 + Math.floor(i / 4)).padStart(2, '0')}T01:00:00Z`, started_at: null }),
    );
    stubCalls(many);
    show();
    await waitFor(() => expect(cards()).toHaveLength(40));
    expect(list()).toHaveClass('th-scroll');
    const search = screen.getByRole('searchbox', { name: '통화 찾기' });
    await userEvent.type(search, '타워크레인');
    expect(cards()).toHaveLength(1);
    expect(screen.getByText('40건 중 1건')).toBeVisible();
    expect(within(list()).getAllByRole('heading', { level: 3 })).toHaveLength(1);
    await userEvent.clear(search);
    await userEvent.type(search, '없는 말');
    expect(within(list()).getByText('찾는 통화가 없습니다.')).toBeVisible();
  });

  test('long words cannot widen the pane', () => {
    expect(css).toMatch(/\.cl-card\s*\{[^}]*min-width:\s*0/);
    expect(css).toMatch(/\.cl-text\s*\{[^}]*overflow-wrap:\s*anywhere/);
    expect(css).not.toMatch(/#[0-9a-f]{3,8}\b/i);
  });
});

describe('redial and recording', () => {
  test('[다시 걸기] makes a new draft and opens the call window on it — nothing is placed', async () => {
    stubCalls([call({ id: 1, status: 'no_answer', duration_s: null, purpose: '받지 않은 목적' })]);
    show();
    const c = await findCard('받지 않은 목적');
    const release = holdCall((r) => r.url.endsWith('/redial'));
    await userEvent.dblClick(btn(c, '다시 걸기'));
    expect(btn(c, '초안 만드는 중…')).toBeDisabled();
    release();
    const dialog = await screen.findByRole('dialog', { name: '전화 걸기' });
    expect(callPosts('redial')).toHaveLength(1);
    expect(callPosts('place')).toHaveLength(0);
    await waitFor(() => expect(dialog.textContent).toContain('받지 않은 목적'));
    expect(rowOf(900)?.status).toBe('draft');
  });

  test('an unknown-outcome call asks first; the server may still refuse the call within its block', async () => {
    stubCalls([call({ id: 6, status: 'failed', duration_s: null, fail_reason: '음성 통화 오류 — 전화가 걸렸는지 확인 필요', events: UNSURE_EVENTS, purpose: '모르는 결과' })]);
    show();
    const c = await findCard('모르는 결과');
    await userEvent.click(btn(c, '다시 걸기'));
    const ask = screen.getByRole('dialog', { name: '다시 걸기 확인' });
    expect(ask.textContent).toContain('이미 걸렸을 수 있습니다');
    expect(callPosts()).toHaveLength(0);
    await userEvent.click(within(ask).getByRole('button', { name: '새 초안 만들기' }));
    const dialog = await screen.findByRole('dialog', { name: '전화 걸기' });
    expect(callPosts('redial')).toHaveLength(1);
    nextPlace({ code: 'duplicate', message: '방금 건 전화가 걸렸는지 확인되지 않았습니다. 잠시 뒤 다시 걸어 주세요', scheduled_at: null }, {});
    await userEvent.click(await within(dialog).findByRole('button', { name: '전화 걸기' }));
    expect(await within(dialog).findByText('방금 건 전화가 걸렸는지 확인되지 않았습니다. 잠시 뒤 다시 걸어 주세요')).toHaveClass('is-warn');
  });

  test('[녹음 듣기] reads the file with the login and plays it in the card', async () => {
    const url = vi.fn(() => 'blob:rec');
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: url, revokeObjectURL: vi.fn() }));
    stubCalls([call({ id: 2, has_recording: true })]);
    show();
    const c = await findCard('토요일 6명 가능');
    await userEvent.click(btn(c, '녹음 듣기'));
    await waitFor(() => expect(c.querySelector('audio')).not.toBeNull());
    expect(c.querySelector('audio')?.getAttribute('src')).toBe('blob:rec');
    expect(callGets().some((r) => r.url.endsWith('/calls/2/recording'))).toBe(true);
  });

  test('a scheduled call can be cancelled, a draft discarded or opened in the call window', async () => {
    stubCalls([
      call({ id: 9, status: 'scheduled', duration_s: null, scheduled_at: '2026-11-29T23:00:00Z', purpose: '예약한 목적' }),
      draftCall({ id: 12, purpose: '초안 목적' }),
    ]);
    show();
    await userEvent.click(btn(await findCard('예약한 목적'), '예약 취소'));
    await waitFor(() => expect(callPosts('cancel')).toHaveLength(1));
    await waitFor(() => expect(card('예약한 목적').textContent).toContain('아직 걸지 않음'));
    await userEvent.click(btn(card('초안 목적'), '전화 걸기 창 열기'));
    expect(await screen.findByRole('dialog', { name: '전화 걸기' })).toBeVisible();
  });
});

describe('the pane around the cards', () => {
  test('empty, read failure and the [전화 걸기] line under the list', async () => {
    stubCalls([]);
    show();
    expect(await within(list()).findByText('아직 통화한 기록이 없습니다.')).toBeVisible();
    expect(screen.getByText('통화는 AI 음성 에이전트가 겁니다. 걸기 전에 목적과 물어볼 것을 확인합니다.')).toBeVisible();
    expect(screen.getByRole('button', { name: '전화 걸기' })).toBeEnabled();
  });

  test('a person who cannot be called cannot open the call window, and says why', async () => {
    stubCalls([]);
    show(JUNG);
    await within(list()).findByText('아직 통화한 기록이 없습니다.');
    const go = screen.getByRole('button', { name: '전화 걸기' });
    expect(go).toBeDisabled();
    expect(screen.getByText('수신 거부한 사람에게는 걸 수 없습니다.')).toBeVisible();
  });

  test('the tab says how many calls there are', async () => {
    stubCalls([call({ id: 1 }), call({ id: 2, status: 'no_answer' })]);
    render(<Contacts windowId="w" params={{ id: '1', contact: '1' }} />);
    expect(await screen.findByRole('tab', { name: '통화 2' })).toBeVisible();
  });

  test('no full phone number anywhere on the screen', async () => {
    stubCalls([
      call({ id: 2, summary_ko: '박현장 010-****-0199 로 회신 요청', answers: [{ question: '연락처', answer: '010-****-0199', quote: '공일공 별표', quote_found: true }] }),
      draftCall({ id: 3, purpose: '010-0000-0199 로 걸어 확인', questions: ['010 0000 0198 은 누구 번호인지'], avoid: ['01000000197'] }),
    ]);
    setTranscript(2, [{ role: 'peer', text: '제 번호는 010-****-0199 입니다', t: 1 }]);
    show();
    const c = await findCard('회신 요청');
    await userEvent.click(btn(c, '받아쓰기 보기'));
    await within(c).findByText('제 번호는 010-****-0199 입니다');
    await userEvent.click(btn(card('걸어 확인'), '전화 걸기 창 열기'));
    await screen.findByRole('dialog', { name: '전화 걸기' });
    await screen.findAllByText(/로 걸어 확인/);
    expect(document.body.innerHTML).not.toMatch(FULL_NUMBER);
    expect(document.body.textContent).not.toMatch(FULL_NUMBER);
  });
});
