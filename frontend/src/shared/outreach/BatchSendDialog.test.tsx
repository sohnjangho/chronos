// 여러 명에게 한 번에(Task 103): 받는 사람 고르기(협력사별·찾기·공종 미리 고름·보낼 수 없는 사람은 흐리게 + 까닭) → 내용 확인 →
// [n명에게 보내기](한 번 누름 = 요청 하나, 같은 요청 번호) → 사람별 결과 표(「확인 필요」·거절은 「보냄」이 아님) + 「묶음 #n · …명 중 …명 회신」.
// 자료는 모두 가상(번호는 가린 꼴만 온다).
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { json, signInAsDemo } from '../../test-helpers';
import BatchSendDialog, { batchLine, type BatchPreset } from './BatchSendDialog';

interface P {
  id: number; name: string; role_title?: string; phone_masked?: string; has_phone?: boolean; phone_kind?: string | null;
  channels?: string[]; do_not_contact?: boolean; phone_invalid?: boolean; hidden?: boolean;
}
const person = (p: P, company_id: number) => ({
  role_title: '공무', phone_masked: '010-****-0199', has_phone: true, phone_kind: 'mobile', channels: ['sms', 'kakao', 'call'],
  unread: 0, do_not_contact: false, phone_invalid: false, last_line: null, hidden: false, company_id, ...p,
});
const company = (id: number, name: string, trade: string, people: P[]) =>
  ({ id, name, trade, note: '', hidden: false, people: people.map((p) => person(p, id)) });

const BOOK = {
  proposals_pending: 0, reports_open: 0,
  companies: [
    company(1, '가람철근', '철근', [
      { id: 11, name: '김공정' }, { id: 12, name: '이설비', phone_masked: '010-****-0201' },
      { id: 13, name: '정배선', do_not_contact: true },
    ]),
    company(2, '한빛전기', '전기', [
      { id: 21, name: '박전기' }, { id: 22, name: '최반장', has_phone: false, phone_masked: '번호 없음', phone_kind: null, channels: [] },
      { id: 23, name: '오유선', phone_masked: '02-****-0000', phone_kind: 'landline', channels: ['call'] },
      { id: 24, name: '한오류', phone_invalid: true },
    ]),
  ],
};
const STATUS = { ready: true, test_mode: true, allow_count: 2, agent: { sms: 'approve', kakao: 'approve', call: 'approve' }, inbound_mode: 'off', kakao_ready: false };
const TEMPLATES = { ready: false, reason: '카카오톡(알림톡)은 아직 쓸 수 없습니다', templates: [] };
const BATCH_URL = '/api/schedules/7/outreach/batches';

type Answer = { status: number; body: unknown } | 'network';
let posts: Record<string, unknown>[];
let answers: Answer[];
let held: Promise<void> | null;
let book: unknown;

const ok = (contact_id: number, name: string, code = 'accepted', message = '보냈습니다') =>
  ({ contact_id, name, outcome: { code, message, scheduled_at: null } });

function stub() {
  posts = [];
  answers = [];
  held = null;
  book = BOOK;
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? 'GET';
    if (url === '/api/schedules/7/contacts') return json(200, book);
    if (url === '/api/notify/status') return json(200, STATUS);
    if (url === '/api/notify/templates') return json(200, TEMPLATES);
    if (method === 'GET' && url === `${BATCH_URL}/31`) return json(200, { total: 3, sent: 1, replied: 0 });
    if (method === 'POST' && url === BATCH_URL) {
      const body = JSON.parse(String(init!.body)) as Record<string, unknown>;
      posts.push(body);
      if (held) await held;
      const a = answers.shift() ?? { status: 200, body: { batch_id: 31, replayed: false, results: [] } };
      if (a === 'network') throw new TypeError('network');
      return json(a.status, a.body);
    }
    return json(404, { code: 'not_found', message: '찾을 수 없습니다.', detail: null });
  }));
}

function open(preset: BatchPreset = {}) {
  const onClose = vi.fn();
  render(<BatchSendDialog scheduleId={7} title="작업 A1100 관계자에게 연락" preset={preset} onClose={onClose} />);
  return onClose;
}

const box = (name: string) => screen.getByRole('checkbox', { name: new RegExp(`^${name}`) });
const toConfirm = async (user: ReturnType<typeof userEvent.setup>) => user.click(screen.getByRole('button', { name: /^다음/ }));

beforeEach(() => {
  sessionStorage.clear();
  signInAsDemo('user');
  stub();
});
afterEach(() => {
  vi.unstubAllGlobals();
  sessionStorage.clear();
});

describe('받는 사람 고르기', () => {
  test('공종이 넘어오면 그 공종 협력사의 보낼 수 있는 사람만 미리 고른다', async () => {
    open({ trade: '철근' });
    await screen.findByRole('group', { name: /가람철근/ });

    expect(box('김공정')).toBeChecked();
    expect(box('이설비')).toBeChecked();
    expect(box('정배선')).not.toBeChecked();
    expect(box('박전기')).not.toBeChecked();
    expect(screen.getByText('공종 「철근」 협력사 사람 2명을 미리 골랐습니다.')).toBeInTheDocument();
    expect(screen.getByText('2명 고름 · 한 번에 20명까지')).toBeInTheDocument();
  });

  test('보낼 수 없는 사람은 흐리게, 고를 수 없고, 까닭이 보인다', async () => {
    open();
    await screen.findByRole('group', { name: /한빛전기/ });

    const reasons: [string, string][] = [
      ['정배선', '수신 거부'], ['최반장', '번호 없음'], ['오유선', '유선 번호라 문자를 받을 수 없음'], ['한오류', '번호 오류'],
    ];
    for (const [name, why] of reasons) {
      const check = box(name);
      expect(check).toBeDisabled();
      expect(check.closest('label')).toHaveClass('is-off');
      expect(check).toHaveAccessibleDescription(why);
    }
    expect(box('박전기')).toBeEnabled();
  });

  test('협력사별로 묶이고, 이름·협력사·공종으로 찾는다', async () => {
    const user = userEvent.setup();
    open();
    const groups = await screen.findAllByRole('group');
    expect(groups.map((g) => g.getAttribute('aria-label'))).toEqual(['가람철근 · 철근 · 3명', '한빛전기 · 전기 · 4명']);

    await user.type(screen.getByRole('searchbox', { name: '사람 찾기' }), '전기');
    expect(screen.queryByRole('group', { name: /가람철근/ })).not.toBeInTheDocument();
    expect(screen.getByRole('group', { name: /한빛전기/ })).toBeInTheDocument();

    await user.clear(screen.getByRole('searchbox', { name: '사람 찾기' }));
    await user.type(screen.getByRole('searchbox', { name: '사람 찾기' }), '이설');
    expect(screen.getAllByRole('checkbox').filter((c) => !c.closest('.bs-co-all'))).toHaveLength(1);
    await user.clear(screen.getByRole('searchbox', { name: '사람 찾기' }));
    await user.type(screen.getByRole('searchbox', { name: '사람 찾기' }), '없는 사람');
    expect(screen.getByText('찾는 사람이 없습니다.')).toBeInTheDocument();
  });

  test('협력사 「모두 고르기」는 보낼 수 있는 사람만, 그리고 20명에서 멈춘다', async () => {
    const user = userEvent.setup();
    const many = Array.from({ length: 22 }, (_, i) => ({ id: 100 + i, name: `가상${String(i).padStart(2, '0')}` }));
    book = { ...BOOK, companies: [company(9, '큰협력사', '형틀', many), ...BOOK.companies] };
    open();
    await screen.findByRole('group', { name: /큰협력사/ });

    await user.click(screen.getByRole('checkbox', { name: '큰협력사 모두 고르기' }));
    expect(screen.getByText('20명 고름 · 한 번에 20명까지')).toBeInTheDocument();
    expect(box('가상20')).not.toBeChecked();
    expect(box('가상20')).toBeDisabled();
    expect(box('가상20')).toHaveAccessibleDescription('한 번에 20명까지 보낼 수 있습니다');

    await user.click(screen.getByRole('checkbox', { name: '가람철근 모두 고르기' }));
    expect(box('김공정')).not.toBeChecked();
  });

  test('아무도 고르지 않으면 다음으로 갈 수 없다', async () => {
    open();
    await screen.findByRole('group', { name: /가람철근/ });
    expect(screen.getByRole('button', { name: /^다음/ })).toBeDisabled();
  });
});

describe('내용 확인과 보내기', () => {
  test('넘겨받은 글·연결로 한 번에 요청 하나, 사람별 결과 표와 묶음 줄', async () => {
    const user = userEvent.setup();
    answers = [{ status: 200, body: { batch_id: 31, replayed: false, results: [
      ok(11, '김공정'), ok(12, '이설비', 'unsure', '보냈는지 확인 필요'), ok(21, '박전기', 'do_not_contact', '수신 거부한 번호입니다'),
    ] } }];
    open({ trade: '철근', body: '내일 3층 타설 가능하신가요?', activityId: 'A1100', fieldItemId: 5, approvalId: 9 });
    await screen.findByRole('group', { name: /가람철근/ });
    await user.click(box('박전기'));
    await toConfirm(user);

    expect(screen.getByRole('textbox', { name: '보낼 글' })).toHaveValue('내일 3층 타설 가능하신가요?');
    expect(screen.getByText('시험 모드 — 허용 번호가 아니면 실제로 나가지 않고 기록만 남습니다')).toBeInTheDocument();
    expect(screen.getByText('받는 사람 3명')).toBeInTheDocument();
    const go = screen.getByRole('button', { name: '3명에게 보내기' });
    await user.dblClick(go);

    const table = await screen.findByRole('table', { name: '사람별 결과' });
    expect(posts).toHaveLength(1);
    expect(posts[0]).toMatchObject({ contact_ids: [11, 12, 21], channel: 'sms', body: '내일 3층 타설 가능하신가요?',
      activity_id: 'A1100', field_item_id: 5, approval_id: 9 });
    expect(String(posts[0].request_key)).toMatch(/^[A-Za-z0-9_-]{8,64}$/);
    const rows = within(table).getAllByRole('row').slice(1).map((r) => within(r).getAllByRole('cell').map((c) => c.textContent));
    expect(rows).toEqual([
      ['김공정', '가람철근', '보냈습니다'],
      ['이설비', '가람철근', '확인 필요 — 보냈는지 알 수 없음'],
      ['박전기', '한빛전기', '수신 거부한 번호입니다'],
    ]);
    expect(within(table).getAllByText('보냈습니다')).toHaveLength(1);
    expect(screen.getByText('보냄 1 · 확인 필요 1 · 보내지 않음 1')).toBeInTheDocument();
    expect(await screen.findByText('묶음 #31 · 3명 중 0명 회신')).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/0100000|010-0000/);
  });

  test('보내는 동안 단추는 잠기고 Enter·두 번 눌러도 요청은 하나', async () => {
    const user = userEvent.setup();
    let release!: () => void;
    held = new Promise((r) => (release = r));
    open({ trade: '철근', body: '안내' });
    await screen.findByRole('group', { name: /가람철근/ });
    await toConfirm(user);
    const go = screen.getByRole('button', { name: '2명에게 보내기' });
    await user.click(go);
    expect(screen.getByRole('button', { name: '보내는 중…' })).toBeDisabled();
    expect(screen.getByRole('textbox', { name: '보낼 글' })).toHaveAttribute('readonly');
    await user.keyboard('{Enter}');
    await act(async () => release());
    await screen.findByRole('table', { name: '사람별 결과' });
    expect(posts).toHaveLength(1);
  });

  test('답을 못 받으면 「보냄」도 「실패」도 아니고, 다시 물을 때는 같은 요청 번호로만', async () => {
    const user = userEvent.setup();
    answers = ['network', { status: 200, body: { batch_id: 31, replayed: true, results: [ok(11, '김공정'), ok(12, '이설비', 'not_sent', '아직 보내지 않았습니다 — 그 사람의 대화에 초안으로 남아 있습니다')] } }];
    open({ trade: '철근', body: '안내' });
    await screen.findByRole('group', { name: /가람철근/ });
    await toConfirm(user);
    await user.click(screen.getByRole('button', { name: '2명에게 보내기' }));

    const note = await screen.findByRole('status');
    expect(note).toHaveTextContent('보냈는지 확인하지 못했습니다');
    expect(note).toHaveClass('is-warn');
    expect(screen.getByRole('textbox', { name: '보낼 글' })).toHaveAttribute('readonly');
    expect(screen.queryByRole('button', { name: '뒤로' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: '결과 다시 받기' }));

    await screen.findByRole('table', { name: '사람별 결과' });
    expect(posts).toHaveLength(2);
    expect(posts[1]).toEqual(posts[0]);
    expect(screen.getByText('이미 받은 요청입니다 — 저장된 결과이며 이번에 다시 보내지 않았습니다.')).toBeInTheDocument();
    expect(screen.getByText('아직 보내지 않았습니다 — 그 사람의 대화에 초안으로 남아 있습니다')).toBeInTheDocument();
  });

  test('서버가 거절한 입력(422·404)은 빨간 글로, 고쳐서 다시 보낼 수 있다', async () => {
    const user = userEvent.setup();
    answers = [{ status: 404, body: { code: 'not_found', message: '연락처를 찾을 수 없습니다.', detail: null } }];
    open({ trade: '철근', body: '안내' });
    await screen.findByRole('group', { name: /가람철근/ });
    await toConfirm(user);
    await user.click(screen.getByRole('button', { name: '2명에게 보내기' }));

    const note = await screen.findByRole('status');
    expect(note).toHaveTextContent('연락처를 찾을 수 없습니다.');
    expect(note).toHaveClass('is-bad');
    expect(screen.getByRole('textbox', { name: '보낼 글' })).not.toHaveAttribute('readonly');
    expect(screen.getByRole('button', { name: '2명에게 보내기' })).toBeEnabled();
  });

  test('빈 글이면 보낼 수 없고, 카카오톡은 준비 전이라 잠겨 까닭이 보인다', async () => {
    const user = userEvent.setup();
    open({ trade: '철근', templateUse: '체크인 요청' });
    await screen.findByRole('group', { name: /가람철근/ });
    await toConfirm(user);

    expect(screen.getByRole('button', { name: '2명에게 보내기' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '카카오톡' })).toBeDisabled();
    expect(screen.getByText(/카카오톡 문안 「체크인 요청」은 지금 쓸 수 없어 문자 글로 보냅니다/)).toBeInTheDocument();
    await user.type(screen.getByRole('textbox', { name: '보낼 글' }), '체크인 부탁드립니다');
    expect(screen.getByRole('button', { name: '2명에게 보내기' })).toBeEnabled();
  });

  test('Esc 는 보내는 중이 아니면 닫는다', async () => {
    const user = userEvent.setup();
    const onClose = open();
    await screen.findByRole('group', { name: /가람철근/ });
    await user.keyboard('{Escape}');
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  });
});

describe('고침 1 — 보내는 중·확인하지 못한 채 닫기·이전 묶음', () => {
  const IN_PROGRESS = '보내는 중일 수 있습니다 — 잠시 뒤 다시 확인해 주세요';
  const ASK_CLOSE = '결과를 확인하지 않고 닫을까요? 다시 보내면 같은 문자가 또 나갈 수 있습니다';
  const sendTwo = async (user: ReturnType<typeof userEvent.setup>) => {
    await screen.findByRole('group', { name: /가람철근/ });
    await toConfirm(user);
    await user.click(screen.getByRole('button', { name: '2명에게 보내기' }));
  };

  test('첫 요청이 아직 보내는 중이면 그렇다고 말하고, [다시 확인]은 같은 요청 번호·같은 몸', async () => {
    const user = userEvent.setup();
    answers = [
      { status: 200, body: { batch_id: 31, replayed: true, in_progress: true, results: [ok(11, '김공정'), ok(12, '이설비', 'in_progress', IN_PROGRESS)] } },
      { status: 200, body: { batch_id: 31, replayed: true, in_progress: false, results: [ok(11, '김공정'), ok(12, '이설비')] } },
    ];
    open({ trade: '철근', body: '안내' });
    await sendTwo(user);

    const table = await screen.findByRole('table', { name: '사람별 결과' });
    expect(within(table).getByText(IN_PROGRESS)).toHaveClass('is-warn');
    expect(screen.getByText('보냄 1 · 보내는 중일 수 있음 1')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '다시 확인' }));

    await waitFor(() => expect(screen.getByText('보냄 2')).toBeInTheDocument());
    expect(posts).toHaveLength(2);
    expect(posts[1]).toEqual(posts[0]);
    expect(screen.queryByRole('button', { name: '다시 확인' })).not.toBeInTheDocument();
  });

  test('답을 못 받은 채 Esc·[닫기]는 먼저 묻는다', async () => {
    const user = userEvent.setup();
    answers = ['network'];
    const onClose = open({ trade: '철근', body: '안내' });
    await sendTwo(user);
    await screen.findByRole('button', { name: '결과 다시 받기' });

    await user.keyboard('{Escape}');
    const ask = screen.getByRole('alertdialog', { name: '닫기 확인' });
    expect(ask).toHaveTextContent(ASK_CLOSE);
    expect(onClose).not.toHaveBeenCalled();
    await user.click(within(ask).getByRole('button', { name: '닫지 않기' }));
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();

    await user.keyboard('{Escape}');
    await user.click(within(screen.getByRole('alertdialog', { name: '닫기 확인' })).getByRole('button', { name: '그래도 닫기' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  test('확인하지 못한 묶음은 이 일정의 창을 다시 열면 [이전 묶음 결과 확인]으로 같은 요청을 다시 묻는다', async () => {
    const user = userEvent.setup();
    answers = ['network'];
    const first = render(<BatchSendDialog scheduleId={7} title="연락" preset={{ trade: '철근', body: '안내' }} onClose={vi.fn()} />);
    await sendTwo(user);
    await screen.findByRole('button', { name: '결과 다시 받기' });
    first.unmount();

    answers = [{ status: 200, body: { batch_id: 31, replayed: true, in_progress: false, results: [ok(11, '김공정'), ok(12, '이설비')] } }];
    const again = render(<BatchSendDialog scheduleId={7} title="연락" preset={{}} onClose={vi.fn()} />);
    await screen.findByRole('group', { name: /가람철근/ });
    expect(screen.getByText(/확인하지 못한 묶음이 있습니다/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '이전 묶음 결과 확인' }));

    await screen.findByRole('table', { name: '사람별 결과' });
    expect(posts).toHaveLength(2);
    expect(posts[1]).toEqual(posts[0]);
    again.unmount();

    // 결과를 받았으니 다음에 열면 더 묻지 않는다
    render(<BatchSendDialog scheduleId={7} title="연락" preset={{}} onClose={vi.fn()} />);
    await screen.findByRole('group', { name: /가람철근/ });
    expect(screen.queryByRole('button', { name: '이전 묶음 결과 확인' })).not.toBeInTheDocument();
  });

  test('다른 일정의 창에는 이전 묶음을 보이지 않고, 서버가 거절한 요청(4xx)은 남기지 않는다', async () => {
    const user = userEvent.setup();
    answers = [{ status: 409, body: { code: 'key_reused', message: '이 요청 번호는 다른 내용의 묶음에 이미 쓰였습니다.', detail: null } }];
    const first = render(<BatchSendDialog scheduleId={7} title="연락" preset={{ trade: '철근', body: '안내' }} onClose={vi.fn()} />);
    await sendTwo(user);
    expect(await screen.findByRole('status')).toHaveClass('is-bad');
    first.unmount();
    sessionStorage.setItem('chronos.batchPending.8', JSON.stringify({ request_key: 'k-other-0001', contact_ids: [1], channel: 'sms', body: 'x' }));
    render(<BatchSendDialog scheduleId={7} title="연락" preset={{}} onClose={vi.fn()} />);
    await screen.findByRole('group', { name: /가람철근/ });
    expect(screen.queryByRole('button', { name: '이전 묶음 결과 확인' })).not.toBeInTheDocument();
  });

  test('찾는 중에는 협력사 머리의 수와 [모두 고르기]가 보이는 사람만 따른다', async () => {
    const user = userEvent.setup();
    open();
    await screen.findByRole('group', { name: /가람철근/ });
    await user.type(screen.getByRole('searchbox', { name: '사람 찾기' }), '김공');

    expect(screen.getByRole('group', { name: '가람철근 · 철근 · 3명 중 1명' })).toBeInTheDocument();
    await user.click(screen.getByRole('checkbox', { name: '가람철근 모두 고르기' }));
    expect(screen.getByText('1명 고름 · 한 번에 20명까지')).toBeInTheDocument();
  });
});

test('batchLine', () => {
  expect(batchLine({ id: 31, total: 3, replied: 2 })).toBe('묶음 #31 · 3명 중 2명 회신');
});
