// 연락처 대화 칸 아래 입력창(Task 79, 시안 ①): 문자 | 카카오톡(카카오톡은 늘 잠김 — 까닭), 연결할 작업(분류+찾기), 글자 수·건 종류,
// [에이전트에게 초안 맡기기](자리만), [보내기]. 보낸 뒤 결과 줄은 서버 판정 그대로(「확인 필요」는 「보냄」이 아니고, 「잠시 뒤 다시」는
// 「이미 보냈습니다」가 아니다). 한 번 누르면 요청 하나. 글은 서버가 줄을 만들었다고 답했을 때만 비운다.
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { useCurrentSchedule } from '../../os/currentSchedule';
import { useWindows } from '../../os/windowStore';
import type { Activity, ScheduleView } from '../../shared/schedule/scheduleApi';
import type { Message, MessageIn, Outcome } from '../../shared/outreach/outreachApi';
import { json } from '../../test-helpers';
import Contacts from './Contacts';
import { SEND_UNKNOWN } from './MessageThread';
import { CHOI, JUNG, KIM, LEE, mockStatus, PARK, person, STATUS } from './testKit';
import { arrive, gets, holdNext, message, stubThread } from './threadKit';
import ThreadPane, { DNC_REASON } from './ThreadPane';

const KAKAO_LOCKED = '카카오톡은 채널·문안 승인 뒤 쓸 수 있습니다 — 지금은 문자로 보냅니다';
const BAND = '시험 모드 — 허용 번호가 아니면 실제로 나가지 않고 기록만 남습니다';
const LONG_NAME = '지하 2층 기계실 배관·덕트·전기 트레이 통합 설치 및 시운전 전 사전 점검과 보완 작업(야간 포함)';

const act_ = (id: string, name: string, wbs: string): Activity => ({
  id, name, kind: 'task', wbs, od: 5, rd: null, progress: 0, actual_start: null, actual_finish: null, constraint: null, resources: [], tags: [],
  es: '2026-11-24', ef: '2026-11-28', plan_start: null, plan_finish: null, tf: 0, ff: 0, critical: false, status: 'on_plan', weight: 1,
});
const SCHEDULE = {
  id: 1, name: '5층 사무동 신축', domain: 'building', level: 'L2', version: 3, data_date: null, finish: '2027-03-31', plan_finish: null,
  wbs: [{ code: 'A', name: '골조', parent: null }, { code: 'B', name: '설비', parent: null }, { code: 'C', name: '전기', parent: null }],
  activities: [
    act_('A1100', '지하 골조', 'A'), act_('A1210', '지상 골조', 'A'), act_('A1220', '옥탑 골조', 'A'),
    act_('B2100', '급수 배관', 'B'), act_('B2200', LONG_NAME, 'B'), act_('C3100', '간선 배선', 'C'),
  ],
  relations: [], resources: [], summary: { critical_count: 0, negative_float_count: 0, warning_count: 0 },
} as ScheduleView;

type Script = { outcome: Outcome; row: Partial<Message> } | { status: number; body: unknown } | 'network' | 'garbled';
let posts: MessageIn[];
let scheduleGets: string[];
let script: Script[];
let held: Promise<void> | null;
let nextId: number;

const OK: Script = { outcome: { code: 'accepted', message: '보냈습니다', scheduled_at: null }, row: { status: 'accepted' } };

/** 대화(threadKit) + 일정 1 읽기 + POST …/outreach/messages(만든 줄을 대화에 넣고 판정을 돌려준다). */
function stub(rows: Record<number, Message[]> = {}) {
  stubThread(rows);
  const inner = globalThis.fetch;
  posts = [];
  scheduleGets = [];
  script = [];
  held = null;
  nextId = 500;
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? 'GET';
      if (method === 'GET' && /^\/api\/schedules\/\d+$/.test(url)) {
        scheduleGets.push(url);
        return json(200, SCHEDULE);
      }
      if (method === 'POST' && url === '/api/schedules/1/outreach/messages') {
        const body = JSON.parse(String(init!.body)) as MessageIn;
        posts.push(body);
        const s = script.shift() ?? OK;
        if (held) await held;
        if (s === 'network') throw new TypeError('network');
        if (s === 'garbled') return new Response('<html>proxy</html>', { status: 200 }); // 200 인데 읽을 수 없는 몸
        if ('status' in s) return json(s.status, s.body);
        const activity = body.activity_id ? { id: body.activity_id, name: SCHEDULE.activities.find((a) => a.id === body.activity_id)?.name ?? null } : null;
        const row = message({ id: nextId++, body: body.body, channel: body.channel, origin_name: '김하늘', activity, created_at: '2026-11-24T01:00:00Z', ...s.row });
        arrive(body.contact_id, row);
        return json(200, { message: row, outcome: s.outcome });
      }
      return inner(input, init);
    }),
  );
}
function holdCreate(): () => void {
  let release!: () => void;
  held = new Promise<void>((r) => (release = r));
  return release;
}

beforeEach(() => {
  useWindows.setState({ open: vi.fn(), setTitle: vi.fn() } as never);
  useCurrentSchedule.setState({ current: { id: 1, name: '5층 사무동 신축' } });
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  useCurrentSchedule.setState({ current: null });
});

const show = (who = PARK, extra: { compose?: string; activity?: string } = {}) =>
  render(<ThreadPane scheduleId={1} person={who} tab="messages" onChanged={vi.fn()} {...extra} />);
const composer = () => screen.getByRole('region', { name: '메시지 입력' });
const box = () => within(composer()).getByRole('textbox', { name: '보낼 글' });
const sendBtn = () => within(composer()).getByRole('button', { name: /^보내기$|^보내는 중…$/ });
const result = () => within(composer()).getByRole('status');
const ready = async () => {
  await screen.findByText(/아직 주고받은 문자가 없습니다|가상/);
  await within(composer()).findByText(BAND);
};
async function type(text: string) {
  const user = userEvent.setup();
  await user.click(box());
  await user.paste(text);
  return user;
}

describe('channel switch', () => {
  test('문자 is chosen; 카카오톡 is shown but cannot be chosen, with the reason', async () => {
    stub();
    show();
    await ready();
    const sw = within(composer()).getByRole('group', { name: '보낼 통로' });
    expect(within(sw).getByRole('button', { name: '문자' })).toHaveAttribute('aria-pressed', 'true');
    const kakao = within(sw).getByRole('button', { name: '카카오톡' });
    expect(kakao).toBeDisabled();
    expect(kakao).toHaveAttribute('aria-pressed', 'false');
    expect(kakao).toHaveAccessibleDescription(KAKAO_LOCKED);
    expect(within(composer()).getByText(KAKAO_LOCKED)).toBeVisible();
    await type('내일 오전 확인 부탁드립니다.');
    await userEvent.click(sendBtn());
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0].channel).toBe('sms');
  });

  test('when KakaoTalk is ready and the person takes it, it can be chosen and the request says kakao', async () => {
    stub();
    mockStatus({ ...STATUS, kakao_ready: true });
    show();
    await ready();
    const kakao = within(composer()).getByRole('button', { name: '카카오톡' });
    await waitFor(() => expect(kakao).toBeEnabled());
    expect(within(composer()).queryByText(KAKAO_LOCKED)).toBeNull();
    await userEvent.click(kakao);
    expect(kakao).toHaveAttribute('aria-pressed', 'true');
    await type('알림');
    await userEvent.click(sendBtn());
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0].channel).toBe('kakao');
  });

  test('a channel the person cannot receive is locked with its reason', async () => {
    stub();
    mockStatus({ ...STATUS, kakao_ready: true });
    show(person({ channels: ['sms', 'call'] }));
    await ready();
    const kakao = within(composer()).getByRole('button', { name: '카카오톡' });
    await waitFor(() => expect(kakao).toHaveAccessibleDescription('이 사람은 카카오톡을 받지 않게 되어 있습니다'));
    expect(kakao).toBeDisabled();
  });

  test('a landline person: 문자 is locked with the reason and nothing can be typed or sent', async () => {
    stub();
    show(LEE);
    await screen.findByText('아직 주고받은 문자가 없습니다.');
    const sms = within(composer()).getByRole('button', { name: '문자' });
    await waitFor(() => expect(sms).toHaveAccessibleDescription('유선 번호라 문자를 받을 수 없습니다'));
    expect(sms).toBeDisabled();
    expect(box()).toBeDisabled();
    expect(sendBtn()).toBeDisabled();
    expect(within(composer()).queryByText(BAND)).toBeNull();
  });
});

describe('locked input', () => {
  test('a person with no number: the input is locked with 「번호 없음」 and nothing is sent', async () => {
    stub();
    show(CHOI, { compose: '철근 반입 시간 알려 주세요' });
    await screen.findByText('아직 주고받은 문자가 없습니다.');
    expect(within(composer()).getByText(/^번호 없음/)).toBeVisible();
    expect(box()).toBeDisabled();
    expect(box()).toHaveAccessibleDescription(/^번호 없음/);
    expect(within(composer()).queryByTestId('sms-count')).toBeNull(); // 보낼 수 없는 글의 건수는 세지 않는다
    expect(sendBtn()).toBeDisabled();
    fireEvent.click(sendBtn());
    expect(posts).toHaveLength(0);
  });

  test('a do-not-contact person: locked with the reason the pane gives', async () => {
    stub();
    show(JUNG);
    await screen.findByText('아직 주고받은 문자가 없습니다.');
    expect(within(composer()).getByText(DNC_REASON)).toBeVisible();
    expect(box()).toBeDisabled();
    expect(sendBtn()).toBeDisabled();
  });

  test('a number marked wrong: locked with 「번호 오류」', async () => {
    stub();
    show(person({ ...KIM, phone_kind: 'mobile', channels: ['sms'] }));
    await screen.findByText('아직 주고받은 문자가 없습니다.');
    expect(within(composer()).getByText(/^번호 오류/)).toBeVisible();
    expect(box()).toBeDisabled();
  });
});

describe('test-mode band', () => {
  test('shown above the input while the status says test mode is on', async () => {
    stub();
    show();
    await ready();
    expect(within(composer()).getByText(BAND)).toHaveClass('th-strip', 'is-warn');
  });

  test('not shown when test mode is off', async () => {
    stub();
    mockStatus({ ...STATUS, test_mode: false });
    show();
    await screen.findByText('아직 주고받은 문자가 없습니다.');
    await waitFor(() => expect(within(composer()).getByRole('button', { name: '카카오톡' })).toHaveAccessibleDescription(KAKAO_LOCKED));
    expect(within(composer()).queryByText(BAND)).toBeNull();
  });
});

describe('counter', () => {
  test('characters, bytes and the kind of message as it is typed', async () => {
    stub();
    show();
    await ready();
    const counter = () => within(composer()).getByTestId('sms-count');
    expect(counter()).toHaveTextContent('0자 · 0/90바이트 · 문자 1건');
    await type('가'.repeat(45));
    expect(counter()).toHaveTextContent('45자 · 90/90바이트 · 문자 1건');
    await userEvent.type(box(), '나');
    expect(counter()).toHaveTextContent('46자 · 92바이트 · 장문 문자로 나갑니다');
    await userEvent.clear(box());
    await type('a'.repeat(90));
    expect(counter()).toHaveTextContent('90자 · 90/90바이트 · 문자 1건');
    expect(counter()).toHaveAttribute('title', expect.stringContaining('90바이트'));
  });
});

describe('send', () => {
  test('one request with the contact, channel, text, linked activity and send: true; the text clears and the thread re-reads', async () => {
    stub();
    show(PARK, { activity: 'A1210' });
    await ready();
    await waitFor(() => expect(within(composer()).getByRole('button', { name: /연결할 작업/ })).toHaveTextContent('연결할 작업: A1210 지상 골조'));
    await type('철근 반입 시간을 알려 주세요.');
    const before = gets().length;
    await userEvent.click(sendBtn());
    await waitFor(() => expect(result()).toHaveTextContent('보냈습니다'));
    expect(posts).toEqual([{ contact_id: 1, channel: 'sms', body: '철근 반입 시간을 알려 주세요.', activity_id: 'A1210', send: true }]);
    expect(result()).toHaveClass('is-ok');
    expect(box()).toHaveValue('');
    await waitFor(() => expect(gets().length).toBeGreaterThan(before));
    // 줄의 상태는 다시 읽은 줄이 그린다
    expect(await screen.findByText('접수')).toBeVisible();
    expect(screen.getByText('철근 반입 시간을 알려 주세요.')).toBeVisible();
  });

  test('params.compose prefills the text', async () => {
    stub();
    show(PARK, { compose: '내일 08시 반입 가능할까요?' });
    await ready();
    expect(box()).toHaveValue('내일 08시 반입 가능할까요?');
  });

  test('[보내기] is off while the text is empty or blank', async () => {
    stub();
    show();
    await ready();
    expect(sendBtn()).toBeDisabled();
    await type('   \n ');
    expect(sendBtn()).toBeDisabled();
  });

  test('the agent-draft button is only a placeholder', async () => {
    stub();
    show();
    await ready();
    expect(within(composer()).getByRole('button', { name: '에이전트에게 초안 맡기기' })).toBeDisabled();
  });

  const BLOCKED: [string, Script, string, string][] = [
    ['scheduled',
      { outcome: { code: 'scheduled', message: '근무시간 밖이라 다음 근무 시작에 보냅니다', scheduled_at: '2026-11-30T08:00:00+09:00' }, row: { status: 'scheduled', scheduled_at: '2026-11-29T23:00:00Z', send_mode: 'manual' } },
      '예약됨 11/30(월) 08:00 — 근무시간 밖이라 다음 근무 시작에 보냅니다', 'is-info'],
    ['test mode',
      { outcome: { code: 'blocked_test', message: '시험 모드라 허용한 번호에만 연락합니다', scheduled_at: null }, row: { status: 'blocked_test', fail_reason: '시험 모드라 허용한 번호에만 연락합니다' } },
      '시험 모드로 보내지 않음 — 시험 모드라 허용한 번호에만 연락합니다', 'is-warn'],
    ['daily limit',
      { outcome: { code: 'limit_daily', message: '오늘 보낼 수 있는 수를 모두 썼습니다', scheduled_at: null }, row: { status: 'draft', fail_reason: '오늘 보낼 수 있는 수를 모두 썼습니다' } },
      '아직 보내지 않음 — 오늘 보낼 수 있는 수를 모두 썼습니다', 'is-warn'],
    ['do not contact',
      { outcome: { code: 'do_not_contact', message: '수신 거부한 번호입니다', scheduled_at: null }, row: { status: 'draft', fail_reason: '수신 거부한 번호입니다' } },
      '아직 보내지 않음 — 수신 거부한 번호입니다', 'is-warn'],
    ['blocked number',
      { outcome: { code: 'blocked_number', message: '차단한 번호입니다', scheduled_at: null }, row: { status: 'draft', fail_reason: '차단한 번호입니다' } },
      '아직 보내지 않음 — 차단한 번호입니다', 'is-warn'],
    ['unsure',
      { outcome: { code: 'unsure', message: '보냈는지 확인 필요', scheduled_at: null }, row: { status: 'unconfirmed' } },
      '확인 필요 — 보냈는지 알 수 없음', 'is-warn'],
    ['duplicate busy',
      { outcome: { code: 'duplicate', message: '이미 보내는 중이거나 잠시 뒤 다시 해 보세요', scheduled_at: null }, row: { status: 'draft' } },
      '아직 보내지 않음 — 이미 보내는 중이거나 잠시 뒤 다시 해 보세요', 'is-warn'],
    ['failed',
      { outcome: { code: 'failed', message: '받는 쪽 번호가 없는 번호입니다', scheduled_at: null }, row: { status: 'failed', fail_reason: '받는 쪽 번호가 없는 번호입니다' } },
      '실패 — 받는 쪽 번호가 없는 번호입니다', 'is-bad'],
  ];
  test.each(BLOCKED)('result line, %s: the server outcome as it is', async (_name, s, text, tone) => {
    stub();
    script.push(s);
    show();
    await ready();
    await type('확인 부탁드립니다.');
    await userEvent.click(sendBtn());
    await waitFor(() => expect(result()).toHaveTextContent(text));
    expect(result().textContent).toBe(text);
    expect(result()).toHaveClass(tone);
    expect(result().textContent).not.toMatch(/보냄|이미 보냈습니다|보냈습니다$/);
    // 서버가 줄을 만들었다 — 그 줄이 대화에 있으니 입력창은 비운다
    expect(box()).toHaveValue('');
  });

  test('an HTTP error shows the server message and keeps the text', async () => {
    stub();
    script.push({ status: 422, body: { code: 'invalid_text', message: '문자 글에는 보이지 않는 제어 글자나 글 방향을 바꾸는 글자를 쓸 수 없습니다.', detail: { field: 'body' } } });
    show();
    await ready();
    await type('확인 부탁드립니다.');
    await userEvent.click(sendBtn());
    await waitFor(() => expect(result()).toHaveTextContent('문자 글에는 보이지 않는 제어 글자나 글 방향을 바꾸는 글자를 쓸 수 없습니다.'));
    expect(result()).toHaveClass('is-bad');
    expect(box()).toHaveValue('확인 부탁드립니다.');
  });

  test('no answer (network): 「보냈는지 확인하지 못했습니다」 in the warning tone, the text stays, [보내기] stays locked until the re-read ends', async () => {
    stub();
    script.push('network');
    show();
    await ready();
    await type('확인 부탁드립니다.');
    const release = holdNext((c) => c.method === 'GET' && c.url.includes('/outreach/threads/1'));
    await userEvent.click(sendBtn());
    await waitFor(() => expect(result()).toHaveTextContent(SEND_UNKNOWN));
    expect(result()).toHaveClass('is-warn');
    expect(result().textContent).not.toMatch(/서버에 연결할 수 없습니다/);
    expect(box()).toHaveValue('확인 부탁드립니다.');
    expect(sendBtn()).toBeDisabled();
    expect(sendBtn()).toHaveTextContent('보내는 중…');
    fireEvent.click(sendBtn());
    await act(async () => release());
    await waitFor(() => expect(sendBtn()).toBeEnabled());
    expect(sendBtn()).toHaveTextContent('보내기');
    expect(posts).toHaveLength(1);
  });

  test.each([
    ['a server error (500)', { status: 500, body: { code: 'internal_error', message: '서버 오류가 났습니다.' } } as Script],
    ['a 200 whose body cannot be read', 'garbled' as Script],
  ])('%s: not known whether it went out — warning tone, text kept, locked until the re-read', async (_name, s) => {
    stub();
    script.push(s);
    show();
    await ready();
    await type('확인 부탁드립니다.');
    const release = holdNext((c) => c.method === 'GET' && c.url.includes('/outreach/threads/1'));
    await userEvent.click(sendBtn());
    await waitFor(() => expect(result()).toHaveTextContent(SEND_UNKNOWN));
    expect(result().textContent).toBe(SEND_UNKNOWN);
    expect(result()).toHaveClass('is-warn');
    expect(box()).toHaveValue('확인 부탁드립니다.');
    expect(sendBtn()).toBeDisabled();
    await act(async () => release());
    await waitFor(() => expect(sendBtn()).toBeEnabled());
    expect(posts).toHaveLength(1);
  });

  test('a double click and fast repeated clicks make one request; [보내기] is locked until the answer', async () => {
    stub();
    show();
    await ready();
    await type('확인 부탁드립니다.');
    const release = holdCreate();
    const btn = sendBtn();
    // 두 번이 화면을 다시 그리기 전에 닿는다(단추가 아직 켜져 있을 때)
    await act(async () => {
      btn.click();
      btn.click();
    });
    fireEvent.click(sendBtn());
    await userEvent.dblClick(sendBtn());
    expect(sendBtn()).toBeDisabled();
    expect(box()).toHaveValue('확인 부탁드립니다.');
    await act(async () => release());
    await waitFor(() => expect(result()).toHaveTextContent('보냈습니다'));
    expect(posts).toHaveLength(1);
  });

  test('holding Enter on [보내기] makes one request', async () => {
    stub();
    show();
    await ready();
    const user = await type('확인 부탁드립니다.');
    const release = holdCreate();
    sendBtn().focus();
    await user.keyboard('{Enter>4/}');
    await act(async () => release());
    await waitFor(() => expect(result()).toHaveTextContent('보냈습니다'));
    expect(posts).toHaveLength(1);
  });
});

describe('activity picker', () => {
  test('lists only the current schedule\'s activities, grouped by WBS, and finds by name or id', async () => {
    stub();
    show();
    await ready();
    const user = userEvent.setup();
    const pick = within(composer()).getByRole('button', { name: /연결할 작업/ });
    expect(pick).toHaveTextContent('연결할 작업: 없음');
    await user.click(pick);
    expect(pick).toHaveAttribute('aria-expanded', 'true');
    const search = await within(composer()).findByRole('searchbox', { name: '작업 찾기' });
    expect(search).toHaveFocus();
    await waitFor(() => expect(within(composer()).getAllByRole('group', { name: /골조|설비|전기/ })).toHaveLength(3));
    expect(scheduleGets).toEqual(['/api/schedules/1']);
    const fit = within(composer()).getByRole('group', { name: 'B 설비' });
    expect(within(fit).getAllByRole('option').map((o) => o.textContent)).toEqual(['B2100급수 배관', `B2200${LONG_NAME}`]);
    await user.type(search, '배관');
    expect(within(composer()).getAllByRole('option').map((o) => o.textContent)).toEqual(['B2100급수 배관', `B2200${LONG_NAME}`]);
    await user.clear(search);
    await user.type(search, 'a12');
    expect(within(composer()).getAllByRole('option').map((o) => o.textContent)).toEqual(['A1210지상 골조', 'A1220옥탑 골조']);
    await user.clear(search);
    await user.type(search, '없는작업');
    expect(within(composer()).getByText('찾는 작업이 없습니다.')).toBeVisible();
  });

  test('choosing links the activity (long names are cut on the button but readable in full); 「연결 안 함」 unlinks', async () => {
    stub();
    show();
    await ready();
    const user = userEvent.setup();
    const pick = within(composer()).getByRole('button', { name: /연결할 작업/ });
    await user.click(pick);
    await user.click(await within(composer()).findByRole('option', { name: new RegExp(LONG_NAME.slice(0, 10)) }));
    expect(pick).toHaveAttribute('aria-expanded', 'false');
    expect(pick).toHaveTextContent(`연결할 작업: B2200 ${LONG_NAME}`);
    expect(pick).toHaveAttribute('title', `B2200 ${LONG_NAME}`);
    expect(pick).toHaveFocus();
    await type('배관 점검 일정 확인 부탁드립니다.');
    await user.click(sendBtn());
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0].activity_id).toBe('B2200');
    await user.click(pick);
    await user.click(within(composer()).getByRole('option', { name: '연결 안 함' }));
    expect(pick).toHaveTextContent('연결할 작업: 없음');
    await type('다른 글');
    await user.click(sendBtn());
    await waitFor(() => expect(posts).toHaveLength(2));
    expect(posts[1]).not.toHaveProperty('activity_id');
  });

  test('Escape closes the list and gives focus back to the button', async () => {
    stub();
    show();
    await ready();
    const user = userEvent.setup();
    const pick = within(composer()).getByRole('button', { name: /연결할 작업/ });
    await user.click(pick);
    await within(composer()).findByRole('searchbox', { name: '작업 찾기' });
    await user.keyboard('{Escape}');
    expect(within(composer()).queryByRole('searchbox')).toBeNull();
    expect(pick).toHaveFocus();
  });

  test('an activity handed in that this schedule does not have is not linked, and says so', async () => {
    stub();
    show(PARK, { activity: 'Z9999' });
    await ready();
    expect(await within(composer()).findByText('넘겨받은 작업 Z9999 을(를) 이 일정에서 찾지 못해 연결하지 않았습니다.')).toBeVisible();
    expect(within(composer()).getByRole('button', { name: /연결할 작업/ })).toHaveTextContent('연결할 작업: 없음');
    await type('글');
    await userEvent.click(sendBtn());
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).not.toHaveProperty('activity_id');
  });
});

describe('handed-over text and activity (params.compose · params.activity)', () => {
  const book = () => screen.getByRole('navigation', { name: '주소록' });
  const choose = async (name: string) => userEvent.click(await within(book()).findByRole('button', { name: new RegExp(name) }));
  const openFor = () => render(<Contacts windowId="w1" params={{ contact: '1', compose: '철근 반입 시간을 알려 주세요.', activity: 'A1210' }} />);
  const picker = () => within(composer()).getByRole('button', { name: /연결할 작업/ });

  test('fill only the person they were handed over for, never another person', async () => {
    stub();
    openFor();
    await waitFor(() => expect(box()).toHaveValue('철근 반입 시간을 알려 주세요.'));
    await waitFor(() => expect(picker()).toHaveTextContent('연결할 작업: A1210 지상 골조'));
    await choose('이전기');
    await screen.findByRole('region', { name: '이전기 대화' });
    expect(box()).toHaveValue('');
    expect(picker()).toHaveTextContent('연결할 작업: 없음');
    await choose('김설비');
    await screen.findByRole('region', { name: '김설비 대화' });
    expect(box()).toHaveValue('');
  });

  test('a person opened without params.contact gets nothing handed over', async () => {
    stub();
    render(<Contacts windowId="w1" params={{ compose: '누구에게나?', activity: 'A1210' }} />);
    await choose('박현장');
    await screen.findByRole('region', { name: '박현장 대화' });
    expect(box()).toHaveValue('');
    expect(picker()).toHaveTextContent('연결할 작업: 없음');
  });

  test('used once: after sending to that person, leaving and coming back leaves the composer empty', async () => {
    stub();
    openFor();
    await waitFor(() => expect(box()).toHaveValue('철근 반입 시간을 알려 주세요.'));
    await within(composer()).findByText(BAND);
    await userEvent.click(sendBtn());
    await waitFor(() => expect(result()).toHaveTextContent('보냈습니다'));
    expect(box()).toHaveValue('');
    await choose('이전기');
    await screen.findByRole('region', { name: '이전기 대화' });
    await choose('박현장');
    await screen.findByRole('region', { name: '박현장 대화' });
    await within(composer()).findByText(BAND);
    expect(box()).toHaveValue('');
    expect(picker()).toHaveTextContent('연결할 작업: 없음');
    expect(posts).toHaveLength(1);
  });

  test('used once: coming back before sending does not fill it again either', async () => {
    stub();
    openFor();
    await waitFor(() => expect(box()).toHaveValue('철근 반입 시간을 알려 주세요.'));
    await choose('이전기');
    await screen.findByRole('region', { name: '이전기 대화' });
    await choose('박현장');
    await screen.findByRole('region', { name: '박현장 대화' });
    await within(composer()).findByText(BAND);
    expect(box()).toHaveValue('');
  });
});
