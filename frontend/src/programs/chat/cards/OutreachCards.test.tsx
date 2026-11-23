// 대화의 연락 카드(Task 83): 문자 초안(outreach_draft) · 전화 초안(outreach_call_draft) · 위임으로 보낸 결과(outreach_sent).
// 카드 자료는 서버 도구(backend/app/tools/notify/**)가 내는 꼴 그대로 — 번호 칸은 없다. 메시지 API 는 Task 73 계약 꼴로 답하는 가짜.
// 초안 카드의 [보내기]는 연락처 대화 칸과 같다: 한 번 누름 = 요청 하나, 답과 다시 읽기가 끝날 때까지 잠김, 결과는 서버 판정 그대로
// (「확인 필요」는 보냄이 아님, 「잠시 뒤 다시」는 「이미 보냈습니다」가 아님), 답이 없으면 「확인하지 못했습니다」. 사람·현장은 가상.
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { useWindows } from '../../../os/windowStore';
import { SEND_UNKNOWN, UNSURE_TEXT } from '../../../shared/outreach/labels';
import type { Message, Outcome } from '../../../shared/outreach/outreachApi';
import { json, signInAsDemo } from '../../../test-helpers';
import { CardView, type CardCtx } from './index';

const PARK = { id: 7, name: '박현장', role_title: '골조 팀장', company: '대한골조' };
const DRAFT = {
  kind: 'outreach_draft', schedule_id: 1, message_id: 41, contact: PARK, channel: 'sms',
  body: '내일 오전 철근 반입 시간을 알려 주시면 타워크레인 일정을 맞추겠습니다.', body_ko: null, needs_approval: true,
};
const CALL = {
  kind: 'outreach_call_draft', schedule_id: 1, call_id: 12, contact: PARK, purpose: 'A1210 만회안 B(주말 작업 2일) 가능 여부 확인',
  questions: ['이번 주말 인원 투입이 가능한지', '가능한 인원'], avoid: ['계약·금액', '다른 협력사 이야기'], language: 'vi', needs_approval: true,
};
const SENT = { kind: 'outreach_sent', schedule_id: 1, message_id: 41, contact: PARK, channel: 'sms', outcome: 'accepted', message: '보냈습니다' };

function row(over: Partial<Message> = {}): Message {
  return {
    id: 41, direction: 'out', channel: 'sms', kind: 'normal', body: DRAFT.body, body_ko: null, has_media: false, origin: 'agent',
    origin_name: '에이전트', send_mode: null, approved_by: null, status: 'draft', fail_reason: null, fallback_sms: false, template_id: null,
    reply_to_id: null, activity: null, field_item_id: null, approval_id: null, chat: { id: 4, title: '주간 점검' }, batch: null, events: [],
    scheduled_at: null, sent_at: null, delivered_at: null, created_at: '2026-11-24T00:00:00Z', ...over,
  };
}

// ── 가짜 메시지 API(그 사람의 줄을 쥐고 있어 보낸 뒤 다시 읽으면 바뀐 줄이 온다) ──
type Answer = { outcome: Outcome; row: Partial<Message> } | { http: number; body: unknown } | 'network' | 'garbled';
let rows: Message[];
let calls: { method: string; url: string }[];
let sendScript: Answer[];
let readFails: number;
let holdSend: Promise<void> | null;
let holdRead: Promise<void> | null;

function stubServer(initial: Message[] = [row()]) {
  rows = initial.map((m) => ({ ...m }));
  calls = [];
  sendScript = [];
  readFails = 0;
  holdSend = null;
  holdRead = null;
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? 'GET';
      calls.push({ method, url });
      const read = url.match(/^\/api\/schedules\/1\/outreach\/threads\/7\?(.*)$/);
      if (method === 'GET' && read) {
        const q = new URLSearchParams(read[1]);
        const before = Number(q.get('before') ?? Infinity);
        const limit = Number(q.get('limit') ?? 50);
        const reply = { contact: { id: 7, name: '박현장' }, messages: rows.filter((m) => m.id < before).slice(-limit), has_more: false };
        if (holdRead) await holdRead;
        if (readFails > 0) {
          readFails -= 1;
          throw new TypeError('network');
        }
        return json(200, reply);
      }
      const send = url.match(/^\/api\/schedules\/1\/outreach\/messages\/(\d+)\/send$/);
      if (method === 'POST' && send) {
        const m = rows.find((r) => r.id === Number(send[1]));
        const s = sendScript.shift();
        let reply: Response;
        if (s === 'network' || s === 'garbled') reply = new Response('<html>proxy</html>', { status: 200 });
        else if (s && 'http' in s) reply = json(s.http, s.body);
        else if (!m) reply = json(404, { code: 'not_found', message: '메시지를 찾을 수 없습니다.' });
        else if (!['draft', 'scheduled', 'sending'].includes(m.status)) reply = json(409, { code: 'not_sendable', message: '이미 처리된 메시지입니다.' });
        else {
          Object.assign(m, s?.row ?? { status: 'accepted', send_mode: 'approved', approved_by: '김하늘', sent_at: '2026-11-24T00:10:00Z' });
          reply = json(200, { message: m, outcome: s?.outcome ?? { code: 'accepted', message: '보냈습니다', scheduled_at: null } });
        }
        if (holdSend) await holdSend;
        if (s === 'network') throw new TypeError('network');
        return reply;
      }
      const del = url.match(/^\/api\/schedules\/1\/outreach\/messages\/(\d+)$/);
      if (method === 'DELETE' && del) {
        const m = rows.find((r) => r.id === Number(del[1]));
        if (!m) return json(404, { code: 'not_found', message: '메시지를 찾을 수 없습니다.' });
        if (m.status !== 'draft') return json(409, { code: 'not_draft', message: '초안만 고치거나 지울 수 있습니다.' });
        rows = rows.filter((r) => r !== m);
        return new Response(null, { status: 204 });
      }
      return json(404, { code: 'not_found', message: '찾을 수 없습니다.' });
    }),
  );
}
const sends = () => calls.filter((c) => c.method === 'POST' && c.url.endsWith('/send'));
const deletes = () => calls.filter((c) => c.method === 'DELETE');
const reads = () => calls.filter((c) => c.method === 'GET');
function hold(which: 'send' | 'read'): () => void {
  let release!: () => void;
  const gate = new Promise<void>((r) => (release = r));
  if (which === 'send') holdSend = gate;
  else holdRead = gate;
  return () => {
    if (which === 'send') holdSend = null;
    else holdRead = null;
    release();
  };
}

let openSpy: ReturnType<typeof vi.fn>;
function renderCard(data: Record<string, unknown>) {
  const ctx: CardCtx = { sessionId: 4, sendText: async () => true, failedQuestionnaire: null, retryResume: () => {} };
  return render(<CardView event="card" data={data} ctx={ctx} />);
}
const card = (name: string) => screen.getByRole('region', { name });
const sendBtn = () => within(card('문자 초안')).getByRole('button', { name: /^보내기$|^보내는 중…$/ });
const note = () => within(card('문자 초안')).getByRole('status');
/** 처음 그린 뒤 지금 상태를 한 번 읽는다 — 그 읽기가 끝날 때까지 기다린다. */
const settled = async () => waitFor(() => expect(reads().length).toBeGreaterThan(0)).then(() => act(async () => {}));

beforeEach(() => {
  signInAsDemo('admin');
  openSpy = vi.fn(() => 'w9');
  useWindows.setState({ open: openSpy } as never);
});
afterEach(() => vi.unstubAllGlobals());

describe('three cards are drawn from the tool card data', () => {
  test('text draft: who it goes to, the channel, the text and its translation; approval mode has 버리기·고치기·보내기; no number', async () => {
    stubServer([row({ body: 'Xin vui lòng cho biết giờ nhập thép.', body_ko: '철근 반입 시간을 알려 주세요.' })]);
    const { container } = renderCard({ ...DRAFT, body: 'Xin vui lòng cho biết giờ nhập thép.', body_ko: '철근 반입 시간을 알려 주세요.' });
    const c = card('문자 초안');
    expect(within(c).getByText('승인 받기')).toBeVisible();
    expect(within(c).getByText('박현장 · 골조 팀장 · 대한골조')).toBeVisible();
    expect(within(c).getByText('Xin vui lòng cho biết giờ nhập thép.')).toBeVisible();
    expect(within(c).getByText('철근 반입 시간을 알려 주세요.')).toBeVisible();
    expect(within(c).getByText('번역')).toBeVisible();
    for (const name of ['버리기', '고치기', '보내기']) expect(within(c).getByRole('button', { name })).toBeEnabled();
    await settled();
    expect(container.textContent).not.toMatch(/010|\*\*\*\*/);
    expect(screen.queryByText(/이 화면에서 보일 수 없는 카드/)).toBeNull();
  });

  test('a delegated text draft has no buttons — the agent sends it, and its result comes as its own card', async () => {
    stubServer();
    renderCard({ ...DRAFT, needs_approval: false });
    await settled();
    const c = card('문자 초안');
    expect(within(c).getByText('위임')).toBeVisible();
    expect(within(c).queryByRole('button')).toBeNull();
  });

  test('call draft: purpose, questions, what not to say, language; [전화 걸기 창 열기] opens the calls tab of that person with the call', async () => {
    stubServer();
    renderCard(CALL);
    const c = card('전화 초안');
    expect(within(c).getByText('A1210 만회안 B(주말 작업 2일) 가능 여부 확인')).toBeVisible();
    expect(within(c).getByText('이번 주말 인원 투입이 가능한지')).toBeVisible();
    expect(within(c).getByText('가능한 인원')).toBeVisible();
    expect(within(c).getByText('계약·금액')).toBeVisible();
    expect(within(c).getByText('다른 협력사 이야기')).toBeVisible();
    expect(within(c).getByText('베트남어')).toBeVisible();
    expect(within(c).getByText('박현장 · 골조 팀장 · 대한골조')).toBeVisible();
    await userEvent.click(within(c).getByRole('button', { name: '전화 걸기 창 열기' }));
    expect(openSpy).toHaveBeenCalledWith('contacts', { id: '1', contact: '7', tab: 'calls', call: '12' });
    expect(calls).toEqual([]); // 전화를 걸지 않는다 — 창만 연다
  });

  test.each([
    ['accepted', '보냈습니다', '보냈습니다', 'is-ok'],
    ['queued', '전화를 걸 차례에 넣었습니다', '전화를 걸 차례에 넣었습니다', 'is-ok'],
    ['unsure', '보냈는지 확인 필요', UNSURE_TEXT, 'is-warn'],
    ['blocked_test', '시험 모드라 허용한 번호에만 연락합니다', '시험 모드라 허용한 번호에만 연락합니다', 'is-warn'],
    ['failed', '받는 쪽 번호가 없는 번호입니다', '실패 — 받는 쪽 번호가 없는 번호입니다', 'is-bad'],
    ['teleported', '처음 보는 판정입니다', '처음 보는 판정입니다', 'is-warn'],
    ['teleported', '', 'teleported', 'is-warn'],
  ])('sent card (%s): [에이전트 발신 · 위임] and the result as the server said it; never a [보내기]', (code, message, text, tone) => {
    stubServer();
    renderCard({ ...SENT, outcome: code, message });
    const c = card('연락 결과');
    expect(within(c).getByText('[에이전트 발신 · 위임]')).toBeVisible();
    expect(within(c).getByText('박현장 · 골조 팀장 · 대한골조')).toBeVisible();
    const line = within(c).getByText(text);
    expect(line).toHaveClass(tone);
    expect(within(c).queryByRole('button')).toBeNull();
    expect(calls).toEqual([]);
  });

  test('sent card for a call says 전화, and a deleted person does not break it', () => {
    stubServer();
    renderCard({ kind: 'outreach_sent', schedule_id: 1, call_id: 12, contact: null, channel: 'call', outcome: 'queued', message: '전화를 걸 차례에 넣었습니다' });
    const c = card('연락 결과');
    expect(within(c).getByText('전화')).toBeVisible();
    expect(within(c).getByText('지워진 연락처')).toBeVisible();
  });

  test('cards with fields missing still draw (no 「보일 수 없는 카드」)', () => {
    stubServer();
    renderCard({ kind: 'outreach_draft' });
    renderCard({ kind: 'outreach_call_draft' });
    renderCard({ kind: 'outreach_sent' });
    expect(screen.queryByText(/이 화면에서 보일 수 없는 카드/)).toBeNull();
    expect(screen.queryByRole('button', { name: '보내기' })).toBeNull();
  });
});

describe('[보내기] on a text draft behaves like the conversation pane', () => {
  test('one request for a double click; locked until the answer and the re-read; the outcome as it is; then the current state instead of buttons', async () => {
    stubServer();
    renderCard(DRAFT);
    await settled();
    const release = hold('send');
    const btn = sendBtn();
    await act(async () => {
      btn.click();
      btn.click();
    });
    fireEvent.click(sendBtn());
    await userEvent.dblClick(sendBtn());
    expect(sendBtn()).toBeDisabled();
    expect(sendBtn()).toHaveTextContent('보내는 중…');
    expect(within(card('문자 초안')).getByRole('button', { name: '버리기' })).toBeDisabled();
    const releaseRead = hold('read');
    await act(async () => release());
    await waitFor(() => expect(note()).toHaveTextContent('보냈습니다'));
    // 답의 줄이 이미 초안이 아니다 — 대화 칸처럼 단추가 곧바로 사라지고, 다시 읽은 줄이 지금 상태를 말한다
    expect(within(card('문자 초안')).queryByRole('button')).toBeNull();
    await act(async () => releaseRead());
    expect(note()).toHaveClass('is-ok');
    expect(within(card('문자 초안')).getByText('지금 상태: 접수 · [에이전트 발신] · 김하늘 승인')).toBeVisible();
    expect(sends()).toHaveLength(1);
  });

  test('holding Enter on [보내기] makes one request', async () => {
    stubServer();
    renderCard(DRAFT);
    await settled();
    const release = hold('send');
    const user = userEvent.setup();
    sendBtn().focus();
    await user.keyboard('{Enter>4/}');
    await act(async () => release());
    await waitFor(() => expect(note()).toHaveTextContent('보냈습니다'));
    expect(sends()).toHaveLength(1);
  });

  test.each([
    // 「확인 필요」는 지금 상태 줄이 말한다(결과 줄에 같은 말을 되풀이하지 않음 — 대화 칸과 같다)
    ['unsure', { outcome: { code: 'unsure', message: '보냈는지 확인 필요', scheduled_at: null }, row: { status: 'unconfirmed' } }, `지금 상태: ${UNSURE_TEXT} · [에이전트 발신]`, 'is-warn', false],
    ['duplicate', { outcome: { code: 'duplicate', message: '이미 보내는 중이거나 잠시 뒤 다시 해 보세요', scheduled_at: null }, row: {} }, '이미 보내는 중이거나 잠시 뒤 다시 해 보세요', 'is-warn', true],
    ['daily limit', { outcome: { code: 'limit_daily', message: '오늘 보낼 수 있는 수를 모두 썼습니다', scheduled_at: null }, row: {} }, '오늘 보낼 수 있는 수를 모두 썼습니다', 'is-warn', true],
    ['test mode', { outcome: { code: 'blocked_test', message: '시험 모드라 허용한 번호에만 연락합니다', scheduled_at: null }, row: { status: 'blocked_test' } }, '시험 모드라 허용한 번호에만 연락합니다', 'is-warn', false],
    ['scheduled', { outcome: { code: 'scheduled', message: '근무시간 밖이라 다음 근무 시작에 보냅니다', scheduled_at: '2026-11-30T08:00:00+09:00' }, row: { status: 'scheduled', scheduled_at: '2026-11-29T23:00:00Z' } }, '근무시간 밖이라 다음 근무 시작에 보냅니다 · 11/30(월) 08:00', 'is-info', false],
    ['an outcome code nobody knows', { outcome: { code: 'teleported', message: '처음 보는 판정입니다', scheduled_at: null }, row: {} }, '처음 보는 판정입니다', 'is-warn', true],
  ] as [string, Answer, string, string, boolean][])('result %s: the server outcome as it is (never 「보냄」); buttons stay only while it is still a draft', async (_n, answer, text, tone, stillDraft) => {
    stubServer();
    sendScript.push(answer);
    renderCard(DRAFT);
    await settled();
    await userEvent.click(sendBtn());
    const c = card('문자 초안');
    const line = await within(c).findByText(text);
    expect(line).toHaveClass(tone);
    if (line !== note()) expect(note().textContent).toBe('');
    await waitFor(() => expect(reads().length).toBe(2));
    await act(async () => {});
    expect(c.textContent).not.toMatch(/보냄|이미 보냈습니다/);
    if (stillDraft) expect(within(c).getByRole('button', { name: '보내기' })).toBeEnabled();
    else expect(within(c).queryByRole('button')).toBeNull();
  });

  test.each([
    ['no answer (network)', 'network' as Answer],
    ['a server error (500)', { http: 500, body: { code: 'internal_error', message: '서버 오류가 났습니다.' } } as Answer],
    ['a 200 whose body cannot be read', 'garbled' as Answer],
  ])('%s: 「보냈는지 확인하지 못했습니다」 in the warning tone, then the re-read says the state', async (_n, answer) => {
    stubServer();
    sendScript.push(answer);
    renderCard(DRAFT);
    await settled();
    const releaseRead = hold('read');
    await userEvent.click(sendBtn());
    await waitFor(() => expect(note().textContent).toBe(SEND_UNKNOWN));
    expect(note()).toHaveClass('is-warn');
    expect(note().textContent).not.toMatch(/서버에 연결할 수 없습니다|서버 오류/);
    expect(sendBtn()).toBeDisabled();
    await act(async () => releaseRead());
    await waitFor(() => expect(sendBtn()).toBeEnabled()); // 다시 읽은 줄이 아직 초안
    expect(sends()).toHaveLength(1);
  });

  test('another HTTP error shows the server message and keeps the buttons', async () => {
    stubServer();
    sendScript.push({ http: 403, body: { code: 'field_no_contacts', message: '현장 관리자는 연락처를 쓸 수 없습니다.' } });
    renderCard(DRAFT);
    await settled();
    await userEvent.click(sendBtn());
    await waitFor(() => expect(note().textContent).toBe('현장 관리자는 연락처를 쓸 수 없습니다.'));
    expect(note()).toHaveClass('is-bad');
    await waitFor(() => expect(sendBtn()).toBeEnabled());
  });
});

describe('a stale card shows the current state in one line instead of buttons', () => {
  test('sent from the conversation pane after the card was drawn: the 409 becomes the current state line', async () => {
    stubServer();
    renderCard(DRAFT);
    await settled();
    expect(sendBtn()).toBeEnabled();
    Object.assign(rows[0], { status: 'delivered', send_mode: 'approved', approved_by: '이담당' }); // 다른 곳에서 보냄
    await userEvent.click(sendBtn());
    const c = card('문자 초안');
    await waitFor(() => expect(within(c).getByText('지금 상태: 도착 · [에이전트 발신] · 이담당 승인')).toBeVisible());
    expect(within(c).queryByRole('button')).toBeNull();
    expect(c.textContent).not.toMatch(/이미 처리된 메시지입니다/);
    expect(sends()).toHaveLength(1);
  });

  test('discarded elsewhere: the 404 says the draft is no longer there', async () => {
    stubServer();
    renderCard(DRAFT);
    await settled();
    rows = [];
    await userEvent.click(within(card('문자 초안')).getByRole('button', { name: '버리기' }));
    const c = card('문자 초안');
    await waitFor(() => expect(within(c).getByText('지금 상태: 이 초안은 이제 없습니다(버렸거나 지웠습니다)')).toBeVisible());
    expect(within(c).queryByRole('button')).toBeNull();
  });

  test('a card opened after its draft was already sent shows the state at once, without buttons; the latest text is shown', async () => {
    stubServer([row({ status: 'unconfirmed', send_mode: 'approved', approved_by: '김하늘', body: '고친 글입니다.' }), row({ id: 42, status: 'received', direction: 'in', origin: 'peer' })]);
    renderCard(DRAFT);
    const c = card('문자 초안');
    await waitFor(() => expect(within(c).getByText(`지금 상태: ${UNSURE_TEXT} · [에이전트 발신] · 김하늘 승인`)).toBeVisible());
    expect(within(c).getByText('지금 상태: 확인 필요 — 보냈는지 알 수 없음 · [에이전트 발신] · 김하늘 승인')).toHaveClass('is-warn');
    expect(within(c).getByText('고친 글입니다.')).toBeVisible();
    expect(within(c).queryByRole('button')).toBeNull();
    // 그 줄 하나만 읽는다(그 id 바로 뒤에서 하나)
    expect(reads()[0].url).toBe('/api/schedules/1/outreach/threads/7?before=42&limit=1');
  });

  test('a card whose draft is gone shows that at once', async () => {
    stubServer([row({ id: 40, status: 'delivered', origin: 'user', origin_name: '김하늘', send_mode: 'manual' })]);
    renderCard(DRAFT);
    const c = card('문자 초안');
    await waitFor(() => expect(within(c).getByText('지금 상태: 이 초안은 이제 없습니다(버렸거나 지웠습니다)')).toBeVisible());
    expect(within(c).queryByRole('button')).toBeNull();
  });

  test('when the state cannot be read, the card keeps its buttons (the server still decides on send)', async () => {
    stubServer();
    readFails = 1;
    renderCard(DRAFT);
    await settled();
    expect(sendBtn()).toBeEnabled();
  });
});

describe('the other buttons', () => {
  test('[버리기] deletes once, then says the draft is gone', async () => {
    stubServer();
    renderCard(DRAFT);
    await settled();
    await userEvent.dblClick(within(card('문자 초안')).getByRole('button', { name: '버리기' }));
    const c = card('문자 초안');
    await waitFor(() => expect(within(c).getByText('지금 상태: 이 초안은 이제 없습니다(버렸거나 지웠습니다)')).toBeVisible());
    expect(deletes()).toHaveLength(1);
    expect(sends()).toHaveLength(0);
  });

  test('[고치기] opens the contacts program on that person\'s messages tab', async () => {
    stubServer();
    renderCard(DRAFT);
    await settled();
    await userEvent.click(within(card('문자 초안')).getByRole('button', { name: '고치기' }));
    expect(openSpy).toHaveBeenCalledWith('contacts', { id: '1', contact: '7', tab: 'messages' });
    expect(sends()).toHaveLength(0);
  });
});
