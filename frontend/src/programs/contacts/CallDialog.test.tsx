// 「전화 걸기」 창(Task 92, 시안 ③): 받는 사람 · 통화 목적 · 물어볼 것 · 말하지 않을 것 · 연결 · 언어 · 음성(고른 까닭) · 근무시간 줄,
// [에이전트에게 다시 쓰게][고치기][전화 걸기]. 근무시간 밖이면 [전화 걸기] 대신 「지금은 근무시간 밖입니다 — [<다음 근무 시작>에 예약]」.
// [전화 걸기]는 진짜 전화로 이어진다 — 두 번 눌러도 요청은 하나, 걸기 직전에 다시 읽어 바뀐 내용은 걸지 않는다.
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { useCurrentSchedule } from '../../os/currentSchedule';
import { useUiContext } from '../../os/uiContext';
import { useWindows } from '../../os/windowStore';
import { CALL_UNKNOWN, SCHEDULE_UNKNOWN } from '../../shared/outreach/labels';
import { CALL_TIMEOUT_MS } from '../../shared/outreach/outreachApi';
import { call, callGets, callPosts, callReqs, change, draftCall, failCall, failPerson, holdCall, nextPlace, rowOf, stubCalls } from './callKit';
import { NOT_CALLABLE } from './CallDialog';
import Contacts from './Contacts';
import { detail, mockDetail, PARK } from './testKit';
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

const DRAFT = draftCall({
  id: 7, origin: 'agent', origin_name: '에이전트', purpose: 'A1210 만회안 B(주말 작업 2일) 가능 여부 확인',
  questions: ['이번 주말 인원 투입 가능한지', '가능 인원', '안 되면 가장 빠른 날'], avoid: ['계약·금액', '다른 협력사 이야기'],
  activity: { id: 'A1210', name: '지상 골조' }, language: 'ko',
});
const showWith = (callId?: string) => render(<ThreadPane scheduleId={1} person={PARK} tab="calls" call={callId} onChanged={onChanged} />);
const dialog = () => screen.getByRole('dialog', { name: '전화 걸기' });
const inDialog = (name: string | RegExp) => within(dialog()).getByRole('button', { name });
const OFF = { working_now: false, hours_label: '근무 밖 · 월 08:00 부터', next_start: '2026-11-30T08:00:00+09:00' };

describe('opening', () => {
  test('params.call opens the window on that draft (시안 ③ rows)', async () => {
    stubCalls([DRAFT]);
    mockDetailOf({ gender: 'male' });
    render(<Contacts windowId="w" params={{ id: '1', contact: '1', tab: 'calls', call: '7' }} />);
    const d = await screen.findByRole('dialog', { name: '전화 걸기' });
    await waitFor(() => expect(d.textContent).toContain('A1210 만회안 B(주말 작업 2일) 가능 여부 확인'));
    const row = (name: string) => within(d).getByText(name, { selector: 'dt' }).nextElementSibling?.textContent;
    expect(row('받는 사람')).toBe('박현장 골조 팀장 (대한골조)');
    expect(row('물어볼 것')).toBe('① 이번 주말 인원 투입 가능한지② 가능 인원③ 안 되면 가장 빠른 날');
    expect(row('말하지 않을 것')).toBe('계약·금액, 다른 협력사 이야기');
    expect(row('연결')).toBe('A1210 지상 골조');
    expect(row('언어')).toBe('한국어');
    expect(row('음성')).toBe('설정의 「남성 연락처에게 걸 때」 칸에서 고릅니다');
    expect(row('근무시간')).toBe('근무 중 · 18:00 까지');
    for (const name of ['에이전트에게 다시 쓰게', '고치기', '전화 걸기']) expect(within(d).getByRole('button', { name })).toBeEnabled();
    expect(callPosts()).toHaveLength(0);
  });

  test('the same params do not reopen the window after it was closed', async () => {
    stubCalls([DRAFT]);
    const params = { id: '1', contact: '1', tab: 'calls', call: '7' };
    const view = render(<Contacts windowId="w" params={params} />);
    await screen.findByRole('dialog', { name: '전화 걸기' });
    await userEvent.click(inDialog('닫기'));
    expect(screen.queryByRole('dialog')).toBeNull();
    await userEvent.click(await screen.findByRole('tab', { name: /문자 · 카카오톡/ }));
    await userEvent.click(screen.getByRole('tab', { name: /통화/ }));
    view.rerender(<Contacts windowId="w" params={params} />);
    await screen.findByRole('log', { name: '통화 기록' });
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  test('a call of another person or one already handled shows the state, not [전화 걸기]', async () => {
    stubCalls([call({ id: 8, status: 'completed', duration_s: 130 })]);
    showWith('8');
    const d = await screen.findByRole('dialog', { name: '전화 걸기' });
    expect(await within(d).findByText(/^지금 상태: 통화 2분 10초 · \[에이전트 발신\] · 김공정 승인$/)).toBeVisible();
    expect(within(d).queryByRole('button', { name: '전화 걸기' })).toBeNull();
    expect(within(d).queryByRole('button', { name: '고치기' })).toBeNull();
  });

  test('voice: chosen per contact, or the reason of the setting slot', async () => {
    stubCalls([DRAFT]);
    mockDetailOf({ voice_mode: 'manual', voice_id: 'ko-voice-7' });
    showWith('7');
    const d = await screen.findByRole('dialog', { name: '전화 걸기' });
    await waitFor(() => expect(within(d).getByText('음성', { selector: 'dt' }).nextElementSibling?.textContent).toBe('ko-voice-7 · 연락처에서 직접 고른 음성'));
  });
});

describe('[전화 걸기]', () => {
  test('two clicks (and a double click) make one place request, after one re-read', async () => {
    stubCalls([DRAFT]);
    showWith('7');
    await screen.findByRole('dialog', { name: '전화 걸기' });
    await waitFor(() => expect(inDialog('전화 걸기')).toBeEnabled());
    const release = holdCall((r) => r.url.endsWith('/place'));
    const go = inDialog('전화 걸기');
    await userEvent.dblClick(go);
    await userEvent.click(go);
    expect(go).toBeDisabled();
    expect(go).toHaveTextContent('거는 중…');
    release();
    expect(await within(dialog()).findByText('전화를 걸 차례에 넣었습니다')).toHaveClass('is-ok');
    expect(callPosts('place')).toHaveLength(1);
    const order = callReqs().filter((r) => r.url.includes('/calls/7')).map((r) => `${r.method} ${r.url.replace('/api/schedules/1/outreach/calls/7', '')}`);
    // 걸기 바로 전에 그 줄을 다시 읽었다(뒤의 읽기는 목록의 받아쓰기 칸이 걸고 있는 통화를 읽는 것)
    expect(order[order.indexOf('POST /place') - 1]).toBe('GET ');
    expect(within(dialog()).queryByRole('button', { name: '전화 걸기' })).toBeNull();
    expect(onChanged).toHaveBeenCalled();
  });

  test('a draft changed since the window drew is not placed — the new text is shown first', async () => {
    stubCalls([DRAFT]);
    showWith('7');
    await screen.findByRole('dialog', { name: '전화 걸기' });
    await waitFor(() => expect(inDialog('전화 걸기')).toBeEnabled());
    change(7, { purpose: '다른 사람이 고친 목적' });
    await userEvent.click(inDialog('전화 걸기'));
    expect(await within(dialog()).findByText('내용이 바뀌었습니다 — 확인한 뒤 다시 눌러 주세요')).toHaveClass('is-warn');
    expect(dialog().textContent).toContain('다른 사람이 고친 목적');
    expect(callPosts('place')).toHaveLength(0);
    await userEvent.click(inDialog('전화 걸기'));
    await waitFor(() => expect(callPosts('place')).toHaveLength(1));
  });

  test('the gate’s outcomes are the server’s words; unknown stays 「확인 필요」, never sent or failed', async () => {
    stubCalls([DRAFT]);
    const unsure = { rule: 'delivery', verdict: 'noted', detail: '보냈는지 확인 필요', at: null };
    nextPlace({ code: 'unsure', message: '보냈는지 확인 필요', scheduled_at: null }, { status: 'failed', fail_reason: '보냈는지 확인 필요', events: [unsure] });
    showWith('7');
    await screen.findByRole('dialog', { name: '전화 걸기' });
    await waitFor(() => expect(inDialog('전화 걸기')).toBeEnabled());
    await userEvent.click(inDialog('전화 걸기'));
    // 판정 글과 지금 상태가 같은 말이면 한 번만(지금 상태 줄), 경고 색
    const line = await within(dialog()).findByText(/^지금 상태: 확인 필요 — 걸렸는지 알 수 없음/);
    expect(line).toHaveClass('is-warn');
    expect(within(dialog()).getAllByText(/확인 필요 — 걸렸는지 알 수 없음/)).toHaveLength(1);
    expect(dialog().textContent).not.toMatch(/실패|걸었습니다|차례에 넣었습니다/);
  });

  test('no answer to the place request is 「not known」, and the window re-reads before unlocking', async () => {
    stubCalls([DRAFT]);
    showWith('7');
    await screen.findByRole('dialog', { name: '전화 걸기' });
    await waitFor(() => expect(inDialog('전화 걸기')).toBeEnabled());
    failCall((r) => r.url.endsWith('/place'), 0);
    const before = callGets(7).length;
    await userEvent.click(inDialog('전화 걸기'));
    expect(await within(dialog()).findByText('걸었는지 확인하지 못했습니다 — 다시 읽은 뒤 상태를 확인해 주세요')).toHaveClass('is-warn');
    await waitFor(() => expect(callGets(7).length).toBeGreaterThanOrEqual(before + 2));
  });

  test('blocked by the test mode: the gate’s text with the row state', async () => {
    stubCalls([DRAFT]);
    nextPlace({ code: 'blocked_test', message: '시험 모드라 허용한 번호에만 연락합니다', scheduled_at: null }, { status: 'blocked_test' });
    showWith('7');
    await screen.findByRole('dialog', { name: '전화 걸기' });
    await waitFor(() => expect(inDialog('전화 걸기')).toBeEnabled());
    await userEvent.click(inDialog('전화 걸기'));
    expect(await within(dialog()).findByText('시험 모드로 걸지 않음 — 시험 모드라 허용한 번호에만 연락합니다')).toHaveClass('is-warn');
  });
});

describe('outside working hours', () => {
  test('only the schedule button, at the next working start the server gives', async () => {
    stubCalls([DRAFT]);
    mockDetailOf(OFF);
    showWith('7');
    const d = await screen.findByRole('dialog', { name: '전화 걸기' });
    await within(d).findByText(/지금은 근무시간 밖입니다 —/);
    expect(within(d).queryByRole('button', { name: '전화 걸기' })).toBeNull();
    const at = within(d).getByRole('button', { name: '11/30(월) 08:00에 예약' });
    await userEvent.dblClick(at);
    await waitFor(() => expect(callPosts('schedule')).toHaveLength(1));
    expect(callPosts('schedule')[0].body).toEqual({ at: '2026-11-30T08:00:00+09:00' });
    expect(callPosts('place')).toHaveLength(0);
    expect(await within(d).findByText(/^지금 상태: 예약됨 11\/30\(월\) 08:00/)).toBeVisible();
    expect(within(d).getByText('예약했습니다 — 그 시각에 근무시간·시험 모드를 다시 확인한 뒤 겁니다.')).toHaveClass('is-info');
  });

  test('a call the gate held outside hours offers the gate’s suggested time', async () => {
    stubCalls([DRAFT]);
    nextPlace({ code: 'blocked_hours', message: '근무시간 밖입니다', scheduled_at: '2099-11-30T08:00:00+09:00' }, { status: 'blocked_hours', scheduled_at: '2099-11-29T23:00:00Z' });
    showWith('7');
    await screen.findByRole('dialog', { name: '전화 걸기' });
    await waitFor(() => expect(inDialog('전화 걸기')).toBeEnabled());
    mockDetailOf(OFF); // 문이 막은 뒤에는 근무 밖(다음 읽기부터)
    await userEvent.click(inDialog('전화 걸기'));
    await userEvent.click(await within(dialog()).findByRole('button', { name: /에 예약$/ }));
    await waitFor(() => expect(callPosts('schedule')[0]?.body).toEqual({ at: '2099-11-29T23:00:00Z' }));
  });

  test('a held call whose suggested time has passed: working now → [전화 걸기]; still outside → the next working start', async () => {
    const held = draftCall({ ...DRAFT, status: 'blocked_hours', scheduled_at: '2020-01-01T00:00:00Z' });
    stubCalls([held]);
    showWith('7'); // 지금 근무 중(기본)
    await screen.findByRole('dialog', { name: '전화 걸기' });
    await waitFor(() => expect(inDialog('전화 걸기')).toBeEnabled());
    expect(within(dialog()).queryByText(/지금은 근무시간 밖입니다/)).toBeNull();
    await userEvent.click(inDialog('전화 걸기'));
    await waitFor(() => expect(callPosts('place')).toHaveLength(1));
    cleanup();

    stubCalls([held]);
    mockDetailOf(OFF);
    showWith('7');
    const d = await screen.findByRole('dialog', { name: '전화 걸기' });
    await userEvent.click(await within(d).findByRole('button', { name: '11/30(월) 08:00에 예약' }));
    await waitFor(() => expect(callPosts('schedule')[0]?.body).toEqual({ at: '2026-11-30T08:00:00+09:00' }));
  });

  test('a time the server refuses (past · holiday) shows its words and a picker for another start', async () => {
    stubCalls([DRAFT]);
    mockDetailOf(OFF);
    failCall((r) => r.url.endsWith('/schedule'), 422, { code: 'outside_hours', message: '근무시간 안의 시각을 골라 주세요' });
    showWith('7');
    const d = await screen.findByRole('dialog', { name: '전화 걸기' });
    await userEvent.click(await within(d).findByRole('button', { name: '11/30(월) 08:00에 예약' }));
    expect(await within(d).findByText('근무시간 안의 시각을 골라 주세요')).toHaveClass('is-bad');
    const pick = within(d).getByLabelText('다른 시각(한국 시각)');
    expect(pick).toHaveValue('2026-11-30T08:00');
    fireEvent.change(pick, { target: { value: '2026-12-01T09:30' } });
    await userEvent.click(within(d).getByRole('button', { name: '이 시각에 예약' }));
    await waitFor(() => expect(callPosts('schedule')).toHaveLength(2));
    expect(callPosts('schedule')[1].body).toEqual({ at: '2026-12-01T09:30:00+09:00' });
  });

  test('a schedule the server refuses for good shows its words (a call that could never go out)', async () => {
    stubCalls([DRAFT]);
    mockDetailOf(OFF);
    failCall((r) => r.url.endsWith('/schedule'), 409, { code: 'not_schedulable', message: '시험 모드라 허용한 번호에만 연락합니다' });
    showWith('7');
    const d = await screen.findByRole('dialog', { name: '전화 걸기' });
    await userEvent.click(await within(d).findByRole('button', { name: '11/30(월) 08:00에 예약' }));
    expect(await within(d).findByText('시험 모드라 허용한 번호에만 연락합니다')).toHaveClass('is-bad');
  });

  test('a schedule with no answer is 「not known」 (warning), and the row is read again', async () => {
    stubCalls([DRAFT]);
    mockDetailOf(OFF);
    failCall((r) => r.url.endsWith('/schedule'), 0);
    showWith('7');
    const d = await screen.findByRole('dialog', { name: '전화 걸기' });
    await userEvent.click(await within(d).findByRole('button', { name: '11/30(월) 08:00에 예약' }));
    expect(await within(d).findByText(SCHEDULE_UNKNOWN)).toHaveClass('is-warn');
    await waitFor(() => expect(callGets(7).length).toBeGreaterThanOrEqual(2));
  });

  test('working hours that cannot be read say so, and the server still decides', async () => {
    stubCalls([DRAFT]);
    failPerson();
    showWith('7');
    const d = await screen.findByRole('dialog', { name: '전화 걸기' });
    await waitFor(() => expect(within(d).getByText('근무시간', { selector: 'dt' }).nextElementSibling?.textContent).toBe('근무시간을 읽지 못했습니다'));
    expect(inDialog('전화 걸기')).toBeEnabled();
  });
});

describe('a request that never answers', () => {
  test('stops waiting after the time limit: 「not known」, and [닫기] works again', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'], shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    stubCalls([DRAFT]);
    showWith('7');
    await screen.findByRole('dialog', { name: '전화 걸기' });
    await waitFor(() => expect(inDialog('전화 걸기')).toBeEnabled());
    holdCall((r) => r.url.endsWith('/place')); // 끝내 답하지 않는다
    await user.click(inDialog('전화 걸기'));
    await waitFor(() => expect(callPosts('place')).toHaveLength(1));
    expect(inDialog('닫기')).toBeDisabled();
    await act(async () => void (await vi.advanceTimersByTimeAsync(CALL_TIMEOUT_MS)));
    expect(await within(dialog()).findByText(CALL_UNKNOWN)).toHaveClass('is-warn');
    await waitFor(() => expect(inDialog('닫기')).toBeEnabled());
    await user.click(inDialog('닫기'));
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});

describe('writing and rewriting', () => {
  test('a new call: write, save as a draft, then confirm and place', async () => {
    stubCalls([]);
    showWith();
    await userEvent.click(await screen.findByRole('button', { name: '전화 걸기' }));
    const d = dialog();
    await userEvent.type(within(d).getByRole('textbox', { name: '통화 목적' }), '타워크레인 일정 확인');
    await userEvent.type(within(d).getByRole('textbox', { name: '물어볼 것' }), '철근 반입 시간{enter}{enter}인원');
    await userEvent.type(within(d).getByRole('textbox', { name: '말하지 않을 것' }), '금액');
    await userEvent.selectOptions(within(d).getByRole('combobox', { name: '언어' }), 'en');
    await userEvent.dblClick(inDialog('저장'));
    await waitFor(() => expect(callPosts()).toHaveLength(1));
    expect(callPosts()[0]).toMatchObject({
      method: 'POST', url: '/api/schedules/1/outreach/calls',
      body: { contact_id: 1, purpose: '타워크레인 일정 확인', questions: ['철근 반입 시간', '인원'], avoid: ['금액'], language: 'en' },
    });
    await waitFor(() => expect(within(dialog()).getByText('통화 목적', { selector: 'dt' }).nextElementSibling?.textContent).toBe('타워크레인 일정 확인'));
    expect(callPosts('place')).toHaveLength(0);
    await userEvent.click(inDialog('전화 걸기'));
    await waitFor(() => expect(callPosts('place')).toHaveLength(1));
  });

  test('a phone number in the call text is refused by the server (422 has_phone) and the text stays to fix', async () => {
    stubCalls([]);
    showWith();
    await userEvent.click(await screen.findByRole('button', { name: '전화 걸기' }));
    await userEvent.type(within(dialog()).getByRole('textbox', { name: '통화 목적' }), '010-0000-0199 로 확인');
    await userEvent.click(inDialog('저장'));
    expect(await within(dialog()).findByText('전화번호는 넣을 수 없습니다 — 연락처에서 고릅니다')).toHaveClass('is-bad');
    expect(callPosts()).toHaveLength(1);
    expect(rowOf(900)).toBeUndefined();
    expect(within(dialog()).getByRole('textbox', { name: '통화 목적' })).toBeVisible();
  });

  test('[고치기] edits the draft (PATCH, not an approval) and shows what the server saved', async () => {
    stubCalls([{ ...DRAFT, activity: null }]); // 이 가짜 일정에는 작업이 없다(연결 칸이 연결을 풀지 않게)
    showWith('7');
    await screen.findByRole('dialog', { name: '전화 걸기' });
    await userEvent.click(await within(dialog()).findByRole('button', { name: '고치기' }));
    const purpose = within(dialog()).getByRole('textbox', { name: '통화 목적' });
    expect(purpose).toHaveValue(DRAFT.purpose);
    expect(within(dialog()).getByRole('textbox', { name: '물어볼 것' })).toHaveValue(DRAFT.questions.join('\n'));
    await userEvent.clear(purpose);
    await userEvent.type(purpose, '주말 작업 가능 여부');
    await userEvent.click(inDialog('저장'));
    await waitFor(() => expect(callPosts()).toHaveLength(1));
    expect(callPosts()[0]).toMatchObject({ method: 'PATCH', url: '/api/schedules/1/outreach/calls/7' });
    // 바꾼 칸만 보낸다 — 서버가 가린 글([번호])이 다른 칸을 고칠 때 되써지지 않게
    expect(callPosts()[0].body).toEqual({ purpose: '주말 작업 가능 여부' });
    await waitFor(() => expect(within(dialog()).getByText('통화 목적', { selector: 'dt' }).nextElementSibling?.textContent).toBe('주말 작업 가능 여부'));
    expect(rowOf(7)?.approved_by).toBeNull();
  });

  test('[에이전트에게 다시 쓰게] hands the draft to the chat — names, never a number', async () => {
    stubCalls([DRAFT]);
    showWith('7');
    await screen.findByRole('dialog', { name: '전화 걸기' });
    await userEvent.click(await within(dialog()).findByRole('button', { name: '에이전트에게 다시 쓰게' }));
    expect(open).toHaveBeenCalledTimes(1);
    const [program, params] = open.mock.calls[0] as [string, { ask: string }];
    expect(program).toBe('chat');
    expect(params.ask).toContain('박현장');
    expect(params.ask).toContain('#7');
    expect(params.ask).toContain(DRAFT.purpose);
    expect(params.ask).not.toMatch(/\d{3,4}-?\*{0,4}-?\d{4}/);
    expect(callPosts()).toHaveLength(0);
  });
});

/** 박현장의 자세히(근무시간·성별·음성) — stubCalls 뒤에 부른다. */
const mockDetailOf = (over: Parameters<typeof detail>[1]) => mockDetail(detail(PARK, over));

// Task 100 — 통화가 준비되지 않은 언어(진단 P10 전 — 중국어·베트남어)는 걸기 창이 「한국어로 겁니다」라고 말한다.
describe('language not ready for calls', () => {
  test('a Vietnamese draft says it goes in Korean; English and Korean do not', async () => {
    stubCalls([{ ...DRAFT, language: 'vi' }]);
    showWith('7');
    const d = await screen.findByRole('dialog', { name: '전화 걸기' });
    expect(await within(d).findByText(NOT_CALLABLE)).toHaveClass('is-warn');
    await userEvent.click(inDialog('고치기'));
    const pick = within(dialog()).getByRole('combobox', { name: '언어' });
    await userEvent.selectOptions(pick, 'en');
    expect(within(dialog()).queryByText(NOT_CALLABLE)).toBeNull();
    await userEvent.selectOptions(pick, 'zh');
    expect(within(dialog()).getByText(NOT_CALLABLE)).toBeVisible();
    await userEvent.selectOptions(pick, 'ko');
    expect(within(dialog()).queryByText(NOT_CALLABLE)).toBeNull();
  });

  test('a new call for a Chinese-speaking person starts in Chinese and says so', async () => {
    stubCalls([]);
    mockDetailOf({ language: 'zh' });
    showWith();
    await userEvent.click(await screen.findByRole('button', { name: '전화 걸기' }));
    expect(await within(dialog()).findByText(NOT_CALLABLE)).toBeVisible();
  });
});
