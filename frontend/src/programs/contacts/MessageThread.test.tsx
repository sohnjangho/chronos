// 연락처 대화 칸(Task 78): 보낸 것 오른쪽·받은 것 왼쪽, 발신 글·상태 글, 에이전트 초안 [버리기][고치기][보내기], 예약 [취소],
// 실패·확인 필요 [다시 보내기](새 초안), 번역 줄·답 표시·사건 접힌 줄, 15초 다시 읽기, 이전 대화 더 보기, 읽음 처리, 수신 거부, 넘침.
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { useCurrentSchedule } from '../../os/currentSchedule';
import { register, type ProgramManifest } from '../../os/registry';
import { useUiContext } from '../../os/uiContext';
import { useWindows } from '../../os/windowStore';
import Contacts from './Contacts';
import { detail, JUNG, LEE, mockDetail, mockReveal, PARK, reveals } from './testKit';
import css from './thread.css?raw';
import {
  acts, agentDraft, arrive, failNext, gets, holdNext, message, nextSend, reads, received, rowsOf, setUnread, stubThread,
} from './threadKit';
import ThreadPane from './ThreadPane';
import { POLL_MS } from './useThread';

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
  Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true });
});

const show = (person = PARK, tab: 'messages' | 'calls' = 'messages') =>
  render(<ThreadPane scheduleId={1} person={person} tab={tab} onChanged={onChanged} />);
const log = () => screen.getByRole('log', { name: '문자 · 카카오톡 대화' });
const bubble = (text: string | RegExp) => screen.getByText(text).closest('article') as HTMLElement;
const findBubble = async (text: string | RegExp) => (await screen.findByText(text)).closest('article') as HTMLElement;
const button = (el: HTMLElement, name: string) => within(el).getByRole('button', { name });

const SENT = message({ id: 1, body: '투입 준비를 확인해 주세요.', channel: 'sms', status: 'delivered', fallback_sms: true, created_at: '2026-11-23T08:30:00Z' });
const REPLY = received({ id: 2, body: '네 확인했습니다. 인원 6명 준비됩니다.', created_at: '2026-11-23T08:52:00Z' });
const APPROVED = message({
  id: 3, origin: 'agent', origin_name: '에이전트', send_mode: 'approved', approved_by: '김공정', status: 'accepted', body: '11/24 체크인 — 진행 상황을 알려 주세요.',
  activity: { id: 'A1210', name: '지상 골조' }, field_item_id: 31, created_at: '2026-11-23T23:02:00Z',
});
const DELEGATED = message({ id: 4, origin: 'agent', origin_name: '에이전트', send_mode: 'delegated', status: 'delivered', body: '철근 반입 시간을 알려 주세요.', created_at: '2026-11-23T23:30:00Z' });
const DRAFT = agentDraft({ id: 7, body: '타워크레인 일정을 맞추겠습니다.', created_at: '2026-11-24T00:00:00Z' });

describe('thread', () => {
  test('sent on the right, received on the left, under KST day lines, each with who sent it, the channel and the time', async () => {
    stubThread({ 1: [SENT, REPLY, APPROVED, DELEGATED] });
    show();
    const mine = await findBubble('투입 준비를 확인해 주세요.');
    expect(mine).toHaveClass('is-me');
    expect(within(mine).getByText('[김공정 발신]')).toBeVisible();
    expect(within(mine).getByText('문자')).toBeVisible();
    expect(within(mine).getByText('17:30')).toBeVisible();
    expect(within(mine).getByText('카카오톡 실패 → 문자로 대신 보냄 · 도착')).toBeVisible();
    const theirs = bubble('네 확인했습니다. 인원 6명 준비됩니다.');
    expect(theirs).toHaveClass('is-them');
    expect(within(theirs).getByText('[상대 발신]')).toBeVisible();
    expect(within(bubble(/11\/24 체크인/)).getByText('[에이전트 발신] · 김공정 승인')).toBeVisible();
    expect(within(bubble(/11\/24 체크인/)).getByText('접수')).toBeVisible();
    expect(within(bubble('철근 반입 시간을 알려 주세요.')).getByText('[에이전트 발신 · 위임]')).toBeVisible();
    expect(within(log()).getAllByRole('heading', { level: 3 }).map((h) => h.textContent)).toEqual(['2026년 11월 23일 월요일', '2026년 11월 24일 화요일']);
    expect(gets()[0].url).toBe('/api/schedules/1/outreach/threads/1');
  });

  test('drawing a thread logs no React warning (keys, act)', async () => {
    const errors = vi.spyOn(console, 'error');
    stubThread({ 1: [SENT, REPLY, APPROVED, DRAFT] });
    show();
    await screen.findByText('타워크레인 일정을 맞추겠습니다.');
    expect(errors).not.toHaveBeenCalled();
  });

  test('an empty thread says so, and the composer slot is there', async () => {
    stubThread({});
    show();
    expect(await screen.findByText('아직 주고받은 문자가 없습니다.')).toBeVisible();
    expect(document.querySelector('[data-slot="composer"]')).not.toBeNull();
  });

  test('the calls tab shows a placeholder and reads no messages', async () => {
    stubThread({ 1: [SENT] });
    show(PARK, 'calls');
    expect(screen.getByText('박현장 님과의 통화 기록이 여기에 보입니다.')).toBeVisible();
    expect(screen.queryByRole('log')).toBeNull();
    await act(async () => {});
    expect(gets()).toHaveLength(0);
  });

  test('the first read failing shows the reason and a retry, never an empty thread', async () => {
    stubThread({ 1: [SENT] });
    failNext((c) => c.method === 'GET', 0);
    show();
    expect(await screen.findByRole('alert')).toHaveTextContent('서버에 연결할 수 없습니다.');
    expect(screen.queryByText('아직 주고받은 문자가 없습니다.')).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: '다시 읽기' }));
    expect(await screen.findByText('투입 준비를 확인해 주세요.')).toBeVisible();
  });

  test('translation line, the reply marker, and received text drawn as plain text with no link', async () => {
    const foreign = received({ id: 5, body: 'Xin chào <img src=x onerror=alert(1)> https://example.invalid/a', body_ko: '안녕하세요', reply_to_id: 3, created_at: '2026-11-23T23:40:00Z' });
    stubThread({ 1: [APPROVED, foreign] });
    show();
    const b = await findBubble(/Xin chào/);
    expect(within(b).getByText('Xin chào <img src=x onerror=alert(1)> https://example.invalid/a')).toBeVisible();
    expect(b.querySelector('img, a')).toBeNull();
    expect(within(b).getByText('안녕하세요')).toBeVisible();
    expect(within(b).getByText('번역')).toBeVisible();
    expect(within(b).getByText('↩ 11/24 A1210 지상 골조 요청에 대한 답')).toBeVisible();
  });

  test('harness events sit in one collapsed line that opens to the full list', async () => {
    const scheduled = message({
      id: 6, status: 'scheduled', scheduled_at: '2026-11-29T23:00:00Z', body: '월요일 투입 인원을 알려 주세요.', created_at: '2026-11-27T10:00:00Z',
      events: [{ rule: 'working_hours', verdict: 'blocked', detail: '근무시간 밖이라 다음 근무 시작에 보냅니다' }],
    });
    stubThread({ 1: [scheduled] });
    show();
    const b = await findBubble('월요일 투입 인원을 알려 주세요.');
    const line = within(b).getByText('근무시간 밖 → 월 08:00 예약');
    const box = line.closest('details') as HTMLDetailsElement;
    expect(box.open).toBe(false);
    expect(within(box).getByText('근무시간 — 근무시간 밖이라 다음 근무 시작에 보냅니다')).toBeInTheDocument();
    expect(within(b).getByText('예약됨 11/30(월) 08:00')).toBeVisible();
  });

  test('the linked activity opens the schedule program; with no such program it is plain text', async () => {
    stubThread({ 1: [APPROVED] });
    const view = show();
    const b = await findBubble(/11\/24 체크인/);
    expect(within(b).getByText('A1210 지상 골조')).toBeVisible();
    expect(within(b).queryByRole('button', { name: /A1210/ })).toBeNull();
    view.unmount();
    register({ id: 'schedule-table', name: '스케줄' } as ProgramManifest);
    register({ id: 'progress', name: '공정률' } as ProgramManifest);
    show();
    const again = await findBubble(/11\/24 체크인/);
    await userEvent.click(button(again, 'A1210 지상 골조 — 스케줄에서 열기'));
    expect(open).toHaveBeenCalledWith('schedule-table', { id: '1', activity: 'A1210' });
    await userEvent.click(button(again, '현장 항목 #31 — 공정률에서 열기'));
    expect(open).toHaveBeenCalledWith('progress', { id: '1', view: 'field' });
  });

  test('long words and names cannot widen the pane', () => {
    expect(css).toMatch(/\.th-bub\s*\{[^}]*overflow-wrap:\s*anywhere/);
    expect(css).toMatch(/\.th-bub\s*\{[^}]*white-space:\s*pre-wrap/);
    expect(css).toMatch(/\.th-b\s*\{[^}]*min-width:\s*0/);
    expect(css).toMatch(/\.th-scroll\s*\{[^}]*overflow-x:\s*hidden/);
    expect(css).toMatch(/\.th-scroll\s*\{[^}]*overflow-y:\s*auto/);
    expect(css).toMatch(/\.th-chip\s*\{[^}]*overflow-wrap:\s*anywhere/);
    expect(css).not.toMatch(/#[0-9a-f]{3,8}\b/i);
  });
});

describe('agent draft', () => {
  test('a dashed draft says where it came from and offers discard, edit, send', async () => {
    stubThread({ 1: [REPLY, DRAFT, agentDraft({ id: 8, kind: 'auto_reply', chat: null, reply_to_id: 2, body: '확인 감사합니다.', created_at: '2026-11-24T00:01:00Z' })] });
    show();
    const b = await findBubble('타워크레인 일정을 맞추겠습니다.');
    expect(b).toHaveClass('is-draft');
    expect(within(b).getByText('에이전트 초안')).toBeVisible();
    expect(within(b).getByText('아직 보내지 않음 · 대화 「주간 점검」에서')).toBeVisible();
    expect(within(b).getAllByRole('button').map((x) => x.textContent)).toEqual(['버리기', '고치기', '보내기']);
    expect(within(bubble('확인 감사합니다.')).getByText('아직 보내지 않음 · 들어온 문자에 대한 답 초안')).toBeVisible();
  });

  test('send posts once, stays locked until the answer, then shows the outcome and the state the server now reports', async () => {
    stubThread({ 1: [DRAFT] });
    show();
    const b = await findBubble('타워크레인 일정을 맞추겠습니다.');
    const release = holdNext((c) => c.url.endsWith('/send'));
    await userEvent.dblClick(button(b, '보내기'));
    expect(acts()).toEqual([{ method: 'POST', url: '/api/schedules/1/outreach/messages/7/send', body: undefined }]);
    expect(within(b).getByRole('button', { name: '보내는 중…' })).toBeDisabled();
    expect(button(b, '버리기')).toBeDisabled();
    expect(within(b).queryByText('접수')).toBeNull(); // 답이 오기 전에는 「보냄」으로 그리지 않는다
    release();
    const sent = await findBubble('타워크레인 일정을 맞추겠습니다.');
    await waitFor(() => expect(within(sent).getByText('접수')).toBeVisible());
    expect(within(sent).getByRole('status')).toHaveTextContent('보냈습니다');
    expect(within(sent).getByText('[에이전트 발신] · 김하늘 승인')).toBeVisible();
    expect(within(sent).queryByRole('button', { name: '보내기' })).toBeNull();
    expect(acts()).toHaveLength(1);
  });

  test('two clicks landing before the screen redraws still make one request', async () => {
    stubThread({ 1: [DRAFT] });
    show();
    const send = button(await findBubble('타워크레인 일정을 맞추겠습니다.'), '보내기');
    await act(async () => {
      send.click();
      send.click();
    });
    await waitFor(() => expect(within(bubble('타워크레인 일정을 맞추겠습니다.')).getByText('접수')).toBeVisible());
    expect(acts()).toHaveLength(1);
  });

  test('a slower re-read that left before the send cannot put the sent row back to a draft', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
    stubThread({ 1: [DRAFT] });
    show();
    await findBubble('타워크레인 일정을 맞추겠습니다.');
    const release = holdNext((c) => c.method === 'GET'); // 초안이던 때의 답이 늦게 온다
    await act(async () => void vi.advanceTimersByTime(POLL_MS));
    expect(gets()).toHaveLength(2);
    await userEvent.click(button(bubble('타워크레인 일정을 맞추겠습니다.'), '보내기'));
    await waitFor(() => expect(within(bubble('타워크레인 일정을 맞추겠습니다.')).getByText('접수')).toBeVisible());
    await act(async () => release());
    await act(async () => {});
    const b = bubble('타워크레인 일정을 맞추겠습니다.');
    expect(within(b).getByText('접수')).toBeVisible();
    expect(b).not.toHaveClass('is-draft');
    expect(within(b).queryByRole('button', { name: '보내기' })).toBeNull();
  });

  test('an unsure result is drawn as 확인 필요, not as sent and not as failed', async () => {
    stubThread({ 1: [DRAFT] });
    nextSend({ code: 'unsure', message: '보냈는지 확인 필요', scheduled_at: null }, { status: 'unconfirmed', fail_reason: '보냈는지 확인 필요', send_mode: 'approved', approved_by: '김하늘' });
    show();
    await userEvent.click(button(await findBubble('타워크레인 일정을 맞추겠습니다.'), '보내기'));
    const b = await findBubble('타워크레인 일정을 맞추겠습니다.');
    await waitFor(() => expect(within(b).getByText('확인 필요 — 보냈는지 알 수 없음', { selector: '.th-chip' })).toBeVisible());
    expect(within(b).getByText('확인 필요 — 보냈는지 알 수 없음', { selector: '.th-chip' })).toHaveClass('is-warn');
    expect(within(b).queryByText(/^실패/)).toBeNull();
    expect(within(b).queryByText(/접수|도착|보냈습니다/)).toBeNull();
    expect(button(b, '다시 보내기')).toBeEnabled();
  });

  test('a failed result shows the reason; a busy/duplicate result is the server text and the draft stays a draft', async () => {
    stubThread({ 1: [DRAFT, agentDraft({ id: 9, body: '두 번째 초안입니다.', created_at: '2026-11-24T00:02:00Z' })] });
    nextSend({ code: 'failed', message: '제공사에 연결하지 못했습니다', scheduled_at: null }, { status: 'failed', fail_reason: '제공사에 연결하지 못했습니다' });
    nextSend({ code: 'duplicate', message: '이미 보내는 중이거나 잠시 뒤 다시 해 보세요', scheduled_at: null }, {});
    show();
    await userEvent.click(button(await findBubble('타워크레인 일정을 맞추겠습니다.'), '보내기'));
    await waitFor(() => expect(within(bubble('타워크레인 일정을 맞추겠습니다.')).getByText('실패 — 제공사에 연결하지 못했습니다', { selector: '.th-chip' })).toHaveClass('is-bad'));
    await userEvent.click(button(bubble('두 번째 초안입니다.'), '보내기'));
    const second = bubble('두 번째 초안입니다.');
    await waitFor(() => expect(within(second).getByRole('status')).toHaveTextContent('이미 보내는 중이거나 잠시 뒤 다시 해 보세요'));
    expect(within(second).getByRole('status')).toHaveClass('is-warn');
    expect(second).toHaveClass('is-draft');
    expect(within(second).queryByText(/보냈습니다|접수/)).toBeNull();
    expect(button(second, '보내기')).toBeEnabled();
  });

  test('a send whose request never got an answer says it is not known whether it went out, stays locked until the re-read, never red', async () => {
    stubThread({ 1: [DRAFT] });
    failNext((c) => c.url.endsWith('/send'), 0);
    const reread = holdNext((c) => c.method === 'GET' && gets().length === 2);
    show();
    await userEvent.click(button(await findBubble('타워크레인 일정을 맞추겠습니다.'), '보내기'));
    const b = bubble('타워크레인 일정을 맞추겠습니다.');
    await waitFor(() => expect(gets()).toHaveLength(2)); // 실패 뒤 곧바로 다시 읽는다
    expect(within(b).getByRole('button', { name: '보내는 중…' })).toBeDisabled(); // 다시 읽기가 끝날 때까지 잠김
    reread();
    await waitFor(() => expect(within(bubble('타워크레인 일정을 맞추겠습니다.')).getByRole('status')).toHaveTextContent('보냈는지 확인하지 못했습니다 — 다시 읽은 뒤 상태를 확인해 주세요'));
    const after = bubble('타워크레인 일정을 맞추겠습니다.');
    expect(within(after).getByRole('status')).toHaveClass('is-warn');
    expect(within(after).queryByText('서버에 연결할 수 없습니다.')).toBeNull();
    expect(acts()).toHaveLength(1);
  });

  test.each(['500', 'unreadable 200'])('a send answered with %s is also 「not known whether it went out」 in the warning tone, locked until the re-read', async (kind) => {
    stubThread({ 1: [DRAFT] });
    if (kind === '500') failNext((c) => c.url.endsWith('/send'), 500, { code: 'internal_error', message: '서버 오류가 났습니다.' });
    else {
      const inner = globalThis.fetch;
      vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
        String(input).endsWith('/send') ? Promise.resolve(new Response('<html>proxy</html>', { status: 200 })) : inner(input, init)));
    }
    const reread = holdNext((c) => c.method === 'GET' && gets().length === 2);
    show();
    await userEvent.click(button(await findBubble('타워크레인 일정을 맞추겠습니다.'), '보내기'));
    await waitFor(() => expect(gets()).toHaveLength(2));
    expect(within(bubble('타워크레인 일정을 맞추겠습니다.')).getByRole('button', { name: '보내는 중…' })).toBeDisabled();
    reread();
    const note = async () => within(bubble('타워크레인 일정을 맞추겠습니다.')).getByRole('status');
    await waitFor(async () => expect(await note()).toHaveTextContent('보냈는지 확인하지 못했습니다 — 다시 읽은 뒤 상태를 확인해 주세요'));
    expect(await note()).toHaveClass('is-warn');
    expect(screen.queryByText('서버 오류가 났습니다.')).toBeNull();
  });

  test('a blocked send shows the gate text and the schedule outcome shows the time', async () => {
    stubThread({ 1: [DRAFT] });
    nextSend({ code: 'scheduled', message: '근무시간 밖이라 다음 근무 시작에 보냅니다', scheduled_at: '2026-11-30T08:00:00+09:00' }, { status: 'scheduled', scheduled_at: '2026-11-29T23:00:00Z', send_mode: 'approved', approved_by: '김하늘' });
    show();
    await userEvent.click(button(await findBubble('타워크레인 일정을 맞추겠습니다.'), '보내기'));
    const b = bubble('타워크레인 일정을 맞추겠습니다.');
    await waitFor(() => expect(within(b).getByRole('status')).toHaveTextContent('근무시간 밖이라 다음 근무 시작에 보냅니다 · 11/30(월) 08:00'));
    expect(within(b).getByText('예약됨 11/30(월) 08:00')).toBeVisible();
    expect(button(b, '취소')).toBeEnabled();
  });

  test('a row the server already finished answers 409: its message is shown and the thread is re-read', async () => {
    stubThread({ 1: [DRAFT] });
    show();
    const b = await findBubble('타워크레인 일정을 맞추겠습니다.');
    rowsOf()[0].status = 'accepted'; // 그 사이 다른 곳에서 나갔다
    await userEvent.click(button(b, '보내기'));
    await waitFor(() => expect(within(bubble('타워크레인 일정을 맞추겠습니다.')).getByRole('status')).toHaveTextContent('이미 처리된 메시지입니다.'));
    expect(within(bubble('타워크레인 일정을 맞추겠습니다.')).getByText('접수')).toBeVisible();
  });

  test('discard deletes the draft and it leaves the thread', async () => {
    stubThread({ 1: [REPLY, DRAFT] });
    show();
    await userEvent.click(button(await findBubble('타워크레인 일정을 맞추겠습니다.'), '버리기'));
    await waitFor(() => expect(screen.queryByText('타워크레인 일정을 맞추겠습니다.')).toBeNull());
    expect(acts()).toEqual([{ method: 'DELETE', url: '/api/schedules/1/outreach/messages/7', body: undefined }]);
    expect(screen.getByText('네 확인했습니다. 인원 6명 준비됩니다.')).toBeVisible();
  });

  test('edit patches the body only; the edited draft has no approver', async () => {
    stubThread({ 1: [DRAFT] });
    show();
    const b = await findBubble('타워크레인 일정을 맞추겠습니다.');
    await userEvent.click(button(b, '고치기'));
    const box = within(b).getByRole('textbox', { name: '초안 고치기' });
    expect(box).toHaveValue('타워크레인 일정을 맞추겠습니다.');
    expect(within(b).queryByRole('button', { name: '보내기' })).toBeNull();
    await userEvent.clear(box);
    expect(button(b, '저장')).toBeDisabled();
    await userEvent.type(box, '오후 2시에 맞추겠습니다.');
    await userEvent.click(button(b, '저장'));
    const edited = await findBubble('오후 2시에 맞추겠습니다.');
    expect(acts()).toEqual([{ method: 'PATCH', url: '/api/schedules/1/outreach/messages/7', body: { body: '오후 2시에 맞추겠습니다.' } }]);
    expect(within(edited).queryByText(/승인/)).toBeNull();
    expect(button(edited, '보내기')).toBeEnabled();
  });
});

describe('schedule and resend', () => {
  test('a scheduled row can be cancelled back to a draft with no approver', async () => {
    const scheduled = message({ id: 6, origin: 'agent', origin_name: '에이전트', send_mode: 'approved', approved_by: '김공정', status: 'scheduled', scheduled_at: '2026-11-29T23:00:00Z', body: '월요일 투입 인원을 알려 주세요.' });
    stubThread({ 1: [scheduled] });
    show();
    const b = await findBubble('월요일 투입 인원을 알려 주세요.');
    expect(within(b).getByText('[에이전트 발신] · 김공정 승인')).toBeVisible();
    await userEvent.click(button(b, '취소'));
    await waitFor(() => expect(bubble('월요일 투입 인원을 알려 주세요.')).toHaveClass('is-draft'));
    expect(acts()).toEqual([{ method: 'POST', url: '/api/schedules/1/outreach/messages/6/cancel', body: undefined }]);
    expect(within(bubble('월요일 투입 인원을 알려 주세요.')).queryByText(/김공정 승인/)).toBeNull();
    expect(within(bubble('월요일 투입 인원을 알려 주세요.')).getByRole('status')).toHaveTextContent('예약을 취소했습니다');
  });

  test('resending a failed row makes a new draft at once and says it has not been sent', async () => {
    stubThread({ 1: [message({ id: 5, status: 'failed', fail_reason: '제공사에 연결하지 못했습니다', body: '자재 반입 일정을 알려 주세요.' })] });
    show();
    const b = await findBubble('자재 반입 일정을 알려 주세요.');
    expect(within(b).getByText('실패 — 제공사에 연결하지 못했습니다')).toHaveClass('is-bad');
    await userEvent.click(button(b, '다시 보내기'));
    expect(screen.queryByRole('dialog')).toBeNull();
    await waitFor(() => expect(screen.getAllByText('자재 반입 일정을 알려 주세요.')).toHaveLength(2));
    expect(acts()).toEqual([{ method: 'POST', url: '/api/schedules/1/outreach/messages/5/resend', body: undefined }]);
    const draft = screen.getAllByText('자재 반입 일정을 알려 주세요.')[1].closest('article') as HTMLElement;
    expect(draft).toHaveClass('is-draft');
    expect(within(draft).getByRole('status')).toHaveTextContent('새 초안을 만들었습니다 — 아직 보내지 않았습니다. [보내기]를 눌러야 나갑니다.');
    expect(button(draft, '보내기')).toBeEnabled();
    expect(within(b).getByText('실패 — 제공사에 연결하지 못했습니다')).toBeVisible(); // 옛 줄은 그대로
  });

  test('resending an unconfirmed row first asks, saying it may already have gone out; cancel sends nothing', async () => {
    stubThread({ 1: [message({ id: 5, status: 'unconfirmed', fail_reason: '보냈는지 확인 필요', body: '자재 반입 일정을 알려 주세요.' })] });
    show();
    const b = await findBubble('자재 반입 일정을 알려 주세요.');
    expect(within(b).getByText('확인 필요 — 보냈는지 알 수 없음')).toHaveClass('is-warn');
    await userEvent.click(button(b, '다시 보내기'));
    const dialog = screen.getByRole('dialog', { name: '다시 보내기 확인' });
    expect(dialog).toHaveTextContent('이미 나갔을 수 있습니다');
    expect(acts()).toHaveLength(0);
    await userEvent.click(within(dialog).getByRole('button', { name: '취소' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(acts()).toHaveLength(0);
    await userEvent.click(button(b, '다시 보내기'));
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: '새 초안 만들기' }));
    await waitFor(() => expect(screen.getAllByText('자재 반입 일정을 알려 주세요.')).toHaveLength(2));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(acts()).toEqual([{ method: 'POST', url: '/api/schedules/1/outreach/messages/5/resend', body: undefined }]);
    const draft = screen.getAllByText('자재 반입 일정을 알려 주세요.')[1].closest('article') as HTMLElement;
    expect(within(draft).getByRole('status')).toHaveTextContent('이미 나갔을 수 있습니다 · 새 초안을 만들었습니다 — 아직 보내지 않았습니다.');
    expect(within(b).getByText('확인 필요 — 보냈는지 알 수 없음')).toBeVisible();
  });

  test('test-mode rows and delivered rows offer no send action', async () => {
    stubThread({ 1: [message({ id: 5, status: 'blocked_test', body: '시험 글입니다.' }), SENT] });
    show();
    const b = await findBubble('시험 글입니다.');
    expect(within(b).getByText('시험 모드로 보내지 않음')).toHaveClass('is-warn');
    expect(within(b).queryByRole('button')).toBeNull();
    expect(within(bubble('투입 준비를 확인해 주세요.')).queryByRole('button')).toBeNull();
  });
});

describe('do not contact', () => {
  test('the thread is readable and drafts show, but send and resend are off with the reason', async () => {
    stubThread({ 4: [received({ id: 2, body: '연락하지 말아 주세요.' }), agentDraft({ id: 7, body: '알겠습니다.' }), message({ id: 8, status: 'failed', fail_reason: '보내지 못했습니다', body: '실패한 글' })] });
    show(JUNG);
    const draft = await findBubble('알겠습니다.');
    expect(screen.getByText('연락하지 말아 주세요.')).toBeVisible();
    expect(button(draft, '보내기')).toBeDisabled();
    expect(button(draft, '보내기')).toHaveAccessibleDescription('수신 거부한 사람에게는 보낼 수 없습니다.');
    expect(button(bubble('실패한 글'), '다시 보내기')).toBeDisabled();
    expect(button(draft, '버리기')).toBeEnabled();
    expect(screen.getByText('수신 거부 — 이 사람에게는 보낼 수 없습니다. 주고받은 기록은 볼 수 있습니다.')).toBeVisible();
  });
});

describe('reading again', () => {
  const tick = () => act(async () => void vi.advanceTimersByTime(POLL_MS));
  const hide = (state: 'hidden' | 'visible') => {
    Object.defineProperty(document, 'visibilityState', { value: state, configurable: true });
    act(() => void document.dispatchEvent(new Event('visibilitychange')));
  };

  test('every 15 seconds with one timer; a new reply appears; unmounting stops it', async () => {
    expect(POLL_MS).toBe(15_000);
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
    stubThread({ 1: [SENT] });
    const view = show();
    await screen.findByText('투입 준비를 확인해 주세요.');
    expect(gets()).toHaveLength(1);
    arrive(1, REPLY);
    await tick();
    expect(await screen.findByText('네 확인했습니다. 인원 6명 준비됩니다.')).toBeVisible();
    expect(gets()).toHaveLength(2);
    await tick();
    expect(gets()).toHaveLength(3);
    view.unmount();
    await tick();
    await tick();
    expect(gets()).toHaveLength(3);
    expect(vi.getTimerCount()).toBe(0);
  });

  test('nothing is read while the browser tab is hidden or the window is minimized; coming back reads at once', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
    stubThread({ 1: [SENT] });
    const frame = document.createElement('div');
    document.body.append(frame);
    render(<ThreadPane scheduleId={1} person={PARK} tab="messages" onChanged={onChanged} />, { container: frame });
    await screen.findByText('투입 준비를 확인해 주세요.');
    hide('hidden');
    expect(vi.getTimerCount()).toBe(0);
    await tick();
    expect(gets()).toHaveLength(1);
    hide('visible');
    await waitFor(() => expect(gets()).toHaveLength(2));
    expect(vi.getTimerCount()).toBe(1);
    frame.hidden = true; // 최소화한 창(os Window 가 hidden 을 건다)
    await tick();
    expect(gets()).toHaveLength(2);
    frame.hidden = false;
    await tick();
    expect(gets()).toHaveLength(3);
    frame.remove();
  });

  test('a failed re-read keeps the thread and says it could not read anew; the next good one clears that', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
    stubThread({ 1: [SENT] });
    show();
    await screen.findByText('투입 준비를 확인해 주세요.');
    failNext((c) => c.method === 'GET', 500);
    await tick();
    expect(await screen.findByText(/새로 읽지 못했습니다/)).toBeVisible();
    expect(screen.getByText('투입 준비를 확인해 주세요.')).toBeVisible();
    await tick();
    await waitFor(() => expect(screen.queryByText(/새로 읽지 못했습니다/)).toBeNull());
  });

  test('an answer for the person shown before is dropped', async () => {
    stubThread({ 1: [SENT], 3: [received({ id: 30, origin_name: '이전기', body: '전기 배선은 내일 끝납니다.' })] });
    const release = holdNext((c) => c.url.includes('/threads/1'));
    const view = show();
    view.rerender(<ThreadPane scheduleId={1} person={LEE} tab="messages" onChanged={onChanged} />);
    expect(await screen.findByText('전기 배선은 내일 끝납니다.')).toBeVisible();
    await act(async () => release());
    await act(async () => {});
    expect(screen.queryByText('투입 준비를 확인해 주세요.')).toBeNull();
    expect(screen.getByText('전기 배선은 내일 끝납니다.')).toBeVisible();
  });

  test('opening marks received texts read and tells the address book; nothing unread means no call', async () => {
    stubThread({ 1: [REPLY], 3: [] });
    setUnread(1, 2);
    const view = show();
    await waitFor(() => expect(reads()).toEqual([{ method: 'POST', url: '/api/schedules/1/contacts/people/1/read', body: undefined }]));
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
    view.unmount();
    show(LEE);
    await screen.findByText('아직 주고받은 문자가 없습니다.');
    expect(reads()).toHaveLength(1);
  });
});

describe('older messages', () => {
  const many = (n: number) => Array.from({ length: n }, (_, i) => message({ id: i + 1, body: `가상 글 ${i + 1}`, created_at: `2026-11-${String(1 + Math.floor(i / 20)).padStart(2, '0')}T01:00:00Z` }));

  test('the newest 50 come first, at the bottom; 이전 대화 더 보기 reads the ones before and keeps the place', async () => {
    vi.spyOn(HTMLElement.prototype, 'scrollHeight', 'get').mockImplementation(function (this: HTMLElement) {
      return this.querySelectorAll('article').length * 100;
    });
    stubThread({ 1: many(120) });
    show();
    await screen.findByText('가상 글 120');
    expect(screen.queryByText('가상 글 70')).toBeNull();
    expect(within(log()).getAllByRole('article')).toHaveLength(50);
    await waitFor(() => expect(log().scrollTop).toBe(5000));
    log().scrollTop = 40;
    await userEvent.click(screen.getByRole('button', { name: '이전 대화 더 보기' }));
    await screen.findByText('가상 글 21');
    expect(gets()[1].url).toBe('/api/schedules/1/outreach/threads/1?before=71');
    expect(within(log()).getAllByRole('article')).toHaveLength(100);
    expect(log().scrollTop).toBe(40 + 5000);
    await userEvent.click(screen.getByRole('button', { name: '이전 대화 더 보기' }));
    await screen.findByText('가상 글 1');
    expect(within(log()).getAllByRole('article')).toHaveLength(120);
    expect(screen.queryByRole('button', { name: '이전 대화 더 보기' })).toBeNull();
  });

  test('send, discard and cancel on rows of an older page show the state the server answered (the re-read covers only the newest 50)', async () => {
    const rows = many(60);
    rows[4] = agentDraft({ id: 5, body: '앞쪽 초안 — 보낼 것', created_at: rows[4].created_at });
    rows[5] = agentDraft({ id: 6, body: '앞쪽 초안 — 버릴 것', created_at: rows[5].created_at });
    rows[6] = message({ id: 7, body: '앞쪽 예약 — 취소할 것', status: 'scheduled', scheduled_at: '2026-11-29T23:00:00Z', send_mode: 'manual', created_at: rows[6].created_at });
    stubThread({ 1: rows });
    show();
    await screen.findByText('가상 글 60');
    await userEvent.click(screen.getByRole('button', { name: '이전 대화 더 보기' }));
    const toSend = await findBubble('앞쪽 초안 — 보낼 것');

    await userEvent.click(button(toSend, '보내기'));
    await waitFor(() => expect(within(bubble('앞쪽 초안 — 보낼 것')).getByText('접수')).toBeVisible());
    expect(bubble('앞쪽 초안 — 보낼 것')).not.toHaveClass('is-draft');
    expect(within(bubble('앞쪽 초안 — 보낼 것')).queryByRole('button', { name: '보내기' })).toBeNull();

    await userEvent.click(button(bubble('앞쪽 초안 — 버릴 것'), '버리기'));
    await waitFor(() => expect(screen.queryByText('앞쪽 초안 — 버릴 것')).toBeNull());

    await userEvent.click(button(bubble('앞쪽 예약 — 취소할 것'), '취소'));
    await waitFor(() => expect(within(bubble('앞쪽 예약 — 취소할 것')).getByRole('status')).toHaveTextContent('예약을 취소했습니다'));
    const cancelled = bubble('앞쪽 예약 — 취소할 것');
    expect(cancelled).toHaveClass('is-draft');
    expect(within(cancelled).queryByText(/예약됨/)).toBeNull();
    expect(within(cancelled).queryByRole('button', { name: '취소' })).toBeNull();
    expect(screen.getByText('가상 글 1')).toBeInTheDocument();
  });

  test('saving an edit on an older-page draft shows the new text', async () => {
    const rows = many(60);
    rows[4] = agentDraft({ id: 5, body: '앞쪽 초안 — 고칠 것', created_at: rows[4].created_at });
    stubThread({ 1: rows });
    show();
    await screen.findByText('가상 글 60');
    await userEvent.click(screen.getByRole('button', { name: '이전 대화 더 보기' }));
    const b = await findBubble('앞쪽 초안 — 고칠 것');
    await userEvent.click(button(b, '고치기'));
    const box = within(b).getByRole('textbox', { name: '초안 고치기' });
    await userEvent.clear(box);
    await userEvent.type(box, '앞쪽 초안 — 고친 글');
    await userEvent.click(button(b, '저장'));
    expect(await screen.findByText('앞쪽 초안 — 고친 글')).toBeVisible();
    expect(screen.queryByText('앞쪽 초안 — 고칠 것')).toBeNull();
  });

  test('a re-read after loading older pages keeps them and still knows there is no more', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
    stubThread({ 1: many(60) });
    show();
    await screen.findByText('가상 글 60');
    await userEvent.click(screen.getByRole('button', { name: '이전 대화 더 보기' }));
    await screen.findByText('가상 글 1');
    arrive(1, message({ id: 61, body: '가상 글 61', created_at: '2026-11-24T01:00:00Z' }));
    await act(async () => void vi.advanceTimersByTime(POLL_MS));
    await screen.findByText('가상 글 61');
    expect(screen.getByText('가상 글 1')).toBeInTheDocument();
    expect(within(log()).getAllByRole('article')).toHaveLength(61);
    expect(screen.queryByRole('button', { name: '이전 대화 더 보기' })).toBeNull();
  });
});

describe('header', () => {
  test('working hours and language come from the address book; the number shows in full only after a click and hides again', async () => {
    stubThread({ 1: [SENT] });
    mockDetail(detail(PARK, { hours_label: '근무 중 · 18:00 까지', language: 'vi' }));
    show();
    expect(await screen.findByText('근무 중 · 18:00 까지')).toBeVisible();
    expect(screen.getByText('베트남어')).toBeVisible();
    expect(screen.queryByText('010-0000-0000')).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: '번호 눌러서 보기' }));
    expect(await screen.findByText('010-0000-0000')).toBeVisible();
    expect(reveals()).toHaveLength(1);
    await userEvent.click(screen.getByRole('button', { name: '번호 가리기' }));
    expect(screen.queryByText('010-0000-0000')).toBeNull();
  });

  test('a number shown for one person is gone when the pane shows another', async () => {
    stubThread({ 1: [SENT], 3: [] });
    const view = show();
    await userEvent.click(await screen.findByRole('button', { name: '번호 눌러서 보기' }));
    expect(await screen.findByText('010-0000-0000')).toBeVisible();
    view.rerender(<ThreadPane scheduleId={1} person={LEE} tab="messages" onChanged={onChanged} />);
    expect(screen.queryByText('010-0000-0000')).toBeNull();
    expect(screen.getByRole('button', { name: '번호 눌러서 보기' })).toBeVisible();
  });

  test('over the reveal limit the server text is shown and no number', async () => {
    stubThread({ 1: [SENT] });
    mockReveal(429, { code: 'too_many_reveals', message: '번호 보기는 10분에 30번까지입니다. 잠시 뒤에 다시 해 주세요.' });
    show();
    await userEvent.click(await screen.findByRole('button', { name: '번호 눌러서 보기' }));
    expect(await screen.findByText('번호 보기는 10분에 30번까지입니다. 잠시 뒤에 다시 해 주세요.')).toBeVisible();
    expect(screen.queryByText('010-0000-0000')).toBeNull();
  });

  test('a person without a number has nothing to reveal', async () => {
    stubThread({});
    show({ ...PARK, has_phone: false, phone_masked: '번호 없음' });
    await screen.findByText('아직 주고받은 문자가 없습니다.');
    expect(screen.queryByRole('button', { name: '번호 눌러서 보기' })).toBeNull();
  });
});

describe('inside the contacts window', () => {
  test('choosing a person shows their thread; choosing another drops the revealed number', async () => {
    stubThread({ 1: [SENT], 3: [received({ id: 30, body: '전기 배선은 내일 끝납니다.' })] });
    render(<Contacts windowId="w1" params={{ contact: '1' }} />);
    expect(await screen.findByText('투입 준비를 확인해 주세요.')).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: '번호 눌러서 보기' }));
    expect(await screen.findByText('010-0000-0000')).toBeVisible();
    await userEvent.click(within(screen.getByRole('navigation', { name: '주소록' })).getByRole('button', { name: /이전기/ }));
    expect(await screen.findByText('전기 배선은 내일 끝납니다.')).toBeVisible();
    expect(screen.queryByText('투입 준비를 확인해 주세요.')).toBeNull();
    expect(screen.queryByText('010-0000-0000')).toBeNull();
    await userEvent.click(within(screen.getByRole('navigation', { name: '주소록' })).getByRole('button', { name: /박현장/ }));
    await screen.findByText('투입 준비를 확인해 주세요.');
    expect(screen.queryByText('010-0000-0000')).toBeNull();
    expect(screen.getByRole('button', { name: '번호 눌러서 보기' })).toBeVisible();
  });

  test('the head above the pane: a name cut short can be read in full, the masked number never breaks, the line wraps on a phone', async () => {
    stubThread({ 1: [SENT] });
    render(<Contacts windowId="w1" params={{ contact: '1' }} />);
    await screen.findByText('투입 준비를 확인해 주세요.');
    expect(screen.getByRole('heading', { name: '박현장' })).toHaveAttribute('title', '박현장');
    expect(screen.getByText('문자·전화 가능')).toHaveAttribute('title', '문자·전화 가능');
    expect(css).toMatch(/\.ct-head-line\.ct-head-sub\s*\{[^}]*flex-wrap:\s*wrap/);
    expect(css).toMatch(/\.ct-head-sub \.ct-num\s*\{[^}]*white-space:\s*nowrap/);
  });

  test('switching the project unmounts the pane: no more reads for the old project', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
    stubThread({ 1: [SENT] });
    render(<Contacts windowId="w1" params={{ contact: '1' }} />);
    await screen.findByText('투입 준비를 확인해 주세요.');
    act(() => useCurrentSchedule.setState({ current: { id: 2, name: '가상 부품 공장' } }));
    await screen.findByText('가상 부품 공장의 주소록');
    const before = gets().length;
    await act(async () => void vi.advanceTimersByTime(POLL_MS * 2));
    expect(gets()).toHaveLength(before);
    expect(screen.queryByText('투입 준비를 확인해 주세요.')).toBeNull();
  });
});
