// 「카카오톡 채널과 문안」 묶음(Task 101 계약대로 가짜 응답). 카카오톡은 쓰지 않는다 — 이 묶음은 상태를 보이기만 한다.
// 채널·문안·번호는 모두 가상이고 실제 제공사를 부르지 않는다.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { Mock } from 'vitest';
import { afterEach, expect, test } from 'vitest';
import { json } from '../../test-helpers';
import type { KakaoState, KakaoTemplate, NotifyConnection } from './notifyApi';
import { renderAs, resetAll, sent } from './testKit';

const LIST = '/api/notify/connections';
const ONE = `${LIST}/3`;
const KAKAO = `${ONE}/kakao`;
const BAND = '카카오톡은 아직 쓰지 않습니다 — 채널·문안이 승인되면 켤 수 있습니다. 지금은 모두 문자로 나갑니다';
const NO_PATH = '채널·문안 목록을 읽는 길을 확인하지 못했습니다.';
const NO_REPLY_IN = '카카오톡으로 온 답은 받을 수 없습니다. 답은 문자로 받습니다';
const LIMITS = { max_call_seconds: 300, daily_sms_total: 50, daily_calls_total: 10 };

function conn(over: Partial<NotifyConnection> = {}): NotifyConnection {
  return {
    id: 3,
    name: '현장 알림',
    provider: 'koreaaitel',
    base_url: 'https://api.koreaaitel.com',
    secret_last4: '9999',
    account_id_masked: '…0001',
    sender_number_masked: '070-****-0123',
    sender_index: 0,
    senders: [{ index: 0, number_masked: '070-****-0123', kind: 'internet', label: '발신번호 1' }],
    kakao_channel: null,
    test_mode: true,
    allow_numbers: [{ index: 0, number_masked: '010-****-0199', kind: 'mobile', can_test_sms: true }],
    allow_numbers_version: 'v1',
    test_sms_index: 0,
    limits: LIMITS,
    agent_sms: 'approve',
    agent_kakao: 'approve',
    agent_call: 'approve',
    inbound_mode: 'off',
    handoff_number_masked: null,
    is_default: true,
    status: 'ok',
    checked_at: null,
    latency_ms: 312,
    used_today: { sms: 0, call: 0 },
    ...over,
  };
}

/** 지금(목록 길 미확인) 서버가 주는 그대로. */
const UNCONFIRMED: KakaoState = { available: false, reason: NO_PATH, channels: [], templates: [], synced_at: null, ready: false };

function tpl(over: Partial<KakaoTemplate> & Pick<KakaoTemplate, 'id' | 'body' | 'status'>): KakaoTemplate {
  return {
    channel: 'ch-1',
    provider_template_id: `tpl-${over.id}`,
    use: null,
    variables: [],
    reply_line: true,
    usable: false,
    fallback_body: null,
    ...over,
  };
}

const LONG = `[크로노스 공정 알림]\n#{이름}님, #{현장} #{날짜} 작업 체크인을 부탁드립니다.\n- 작업: #{작업}\n- 확인할 것: 오늘 투입 인원, 시작 시각, 막히는 점\n답은 이 번호로 문자 주세요: 070-****-0123`;

const FILLED: KakaoState = {
  available: true,
  reason: null,
  channels: [{ id: 'ch-1', name: '크로노스 공정 알림', status: 'connected' }],
  templates: [
    tpl({ id: 1, body: LONG, status: 'approved', use: '체크인 요청', variables: ['이름', '현장', '날짜', '작업'], usable: true, fallback_body: '#{이름}님, #{현장} #{날짜} 체크인 부탁드립니다.' }),
    tpl({ id: 2, body: '[크로노스 공정 알림] 3일 뒤 #{작업} 투입 준비를 확인해 주세요.', status: 'reviewing', reply_line: false }),
    tpl({ id: 3, body: '[크로노스 공정 알림] 승인 대기 #{건수}건이 있습니다. 답은 이 번호로 문자 주세요.', status: 'rejected' }),
    tpl({ id: 4, body: '[크로노스 공정 알림] 옛 일정 변경 알림. 답은 이 번호로 문자 주세요.', status: 'dormant', use: '일정 변경 알림' }),
  ],
  synced_at: '2026-11-24T01:00:00Z',
  ready: false,
};

const card = () => screen.getByRole('article', { name: '현장 알림' });
const reread = (b: HTMLElement) => within(b).getByRole('button', { name: '채널·문안 다시 읽기' });

function open(kakao: object = UNCONFIRMED, over: Record<string, unknown> = {}) {
  return renderAs('admin', { section: 'notify' }, {
    [LIST]: [conn()],
    [`${ONE}/diagnosis`]: () => json(200, null),
    [`${ONE}/limits`]: { values: LIMITS, defaults: LIMITS, ranges: {} },
    [`${ONE}/voice/diagnosis`]: () => json(200, null),
    [KAKAO]: kakao,
    ...over,
  });
}

/** 상태를 읽어 그려질 때까지 기다린다. */
async function findBlock(text: string | RegExp) {
  const b = await screen.findByRole('region', { name: '카카오톡 채널과 문안' });
  await within(b).findByText(text);
  return b;
}

/** 채널·문안이 있는 상태가 표까지 그려질 때까지 기다린다. */
async function findFilled() {
  const b = await screen.findByRole('region', { name: '카카오톡 채널과 문안' });
  await within(b).findByRole('table', { name: '카카오톡 문안' });
  return b;
}

/** 보낸 모든 요청(방법 · 주소 · 본문). */
function requests(fetchMock: Mock) {
  return fetchMock.mock.calls.map(([url, init]) => {
    const i = init as RequestInit | undefined;
    return { method: i?.method ?? 'GET', url: String(url), body: typeof i?.body === 'string' ? i.body : '' };
  });
}

afterEach(resetAll);

test('with no channel the band, 「연결된 채널 없음」, the steps and the reply note show, and there is no template table', async () => {
  open();
  const b = await findBlock('연결된 채널 없음');
  expect(within(b).getByText(BAND)).toBeVisible();
  expect(within(b).getByText(NO_REPLY_IN)).toBeVisible();
  expect(within(b).queryByRole('table')).toBeNull();
  const steps = within(b).getByRole('list', { name: '준비 차례' });
  expect(within(steps).getAllByRole('listitem').map((li) => li.textContent?.slice(0, 1))).toEqual(['①', '②', '③', '④']);
  expect(within(b).getByText('준비 안 됨')).toBeVisible();
  expect(within(b).getByText(/아직 읽은 적 없음/)).toBeVisible();
});

test('the band stays first in the block even when channels and templates exist', async () => {
  open(FILLED);
  const b = await findFilled();
  const band = within(b).getByText(BAND);
  const table = within(b).getByRole('table', { name: '카카오톡 문안' });
  expect(band.compareDocumentPosition(table) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(within(b).getByText('준비 안 됨')).toBeVisible();
});

test('re-reading is locked while the listing path is unconfirmed, with the reason, and nothing is asked of the server', async () => {
  const { fetchMock } = open();
  const b = await findBlock('연결된 채널 없음');
  expect(reread(b)).toBeDisabled();
  expect(within(b).getByText(NO_PATH)).toBeVisible();
  expect(sent(fetchMock, `POST ${KAKAO}/sync`)).toEqual([]);
});

test('without a server reason the locked re-read says 「목록을 읽는 길을 확인하지 못했습니다」', async () => {
  open({ ...UNCONFIRMED, reason: null });
  const b = await findBlock('연결된 채널 없음');
  expect(reread(b)).toBeDisabled();
  expect(within(b).getByText(/^목록을 읽는 길을 확인하지 못했습니다/)).toBeVisible();
});

test('channels and templates draw a 쓰는 곳 | 문안 | 상태 table with all four states', async () => {
  open(FILLED);
  const b = await findFilled();
  const channels = within(b).getByRole('list', { name: '연결된 채널' });
  expect(channels).toHaveTextContent('크로노스 공정 알림');
  expect(channels).toHaveTextContent('연결됨');
  expect(within(b).queryByText('연결된 채널 없음')).toBeNull();
  const table = within(b).getByRole('table', { name: '카카오톡 문안' });
  expect(within(table).getAllByRole('columnheader').map((h) => h.textContent)).toEqual(['쓰는 곳', '문안', '상태']);
  const rows = within(table).getAllByRole('row').slice(1);
  expect(rows).toHaveLength(4);
  expect(rows.map((r) => within(r).getByRole('combobox', { name: '쓰는 곳' }))).toHaveLength(4);
  expect(within(rows[0]).getByText('승인')).toBeVisible();
  expect(within(rows[1]).getByText('검수 중')).toBeVisible();
  expect(within(rows[2]).getByText('반려')).toBeVisible();
  expect(within(rows[3]).getByText('휴면')).toBeVisible();
  expect(within(rows[0]).getByRole('combobox', { name: '쓰는 곳' })).toHaveDisplayValue('체크인 요청');
  expect(within(rows[1]).getByRole('combobox', { name: '쓰는 곳' })).toHaveDisplayValue('잇지 않음');
});

test('a long body is cut in the row and the whole text, variables and fallback SMS fold open; ids stay folded', async () => {
  open(FILLED);
  const b = await findFilled();
  const row = within(within(b).getByRole('table', { name: '카카오톡 문안' })).getAllByRole('row')[1];
  const more = within(row).getByText('전문 보기');
  const whole = within(row).getByLabelText('문안 전문');
  expect(whole).not.toBeVisible();
  await userEvent.click(more);
  expect(whole).toBeVisible();
  expect(whole).toHaveTextContent('막히는 점');
  expect(within(row).getByText(/변수 #\{이름\} #\{현장\} #\{날짜\} #\{작업\}/)).toBeVisible();
  expect(within(row).getByText(/#\{이름\}님, #\{현장\} #\{날짜\} 체크인 부탁드립니다\./)).toBeVisible();
  expect(within(row).getByText(/tpl-1/)).toBeVisible();
});

test('picking 쓰는 곳 PATCHes only use, and 잇지 않음 sends null', async () => {
  const { fetchMock } = open(FILLED, {
    [`PATCH ${KAKAO}/templates/2`]: (init?: RequestInit) => {
      const use = (JSON.parse(String(init?.body)) as { use: string | null }).use;
      return json(200, { ...FILLED.templates[1], use });
    },
  });
  const b = await findFilled();
  const row = () => within(within(b).getByRole('table', { name: '카카오톡 문안' })).getAllByRole('row')[2];
  await userEvent.selectOptions(within(row()).getByRole('combobox', { name: '쓰는 곳' }), 'D-3 준비 확인');
  await waitFor(() => expect(within(row()).getByRole('combobox', { name: '쓰는 곳' })).toHaveDisplayValue('D-3 준비 확인'));
  await userEvent.selectOptions(within(row()).getByRole('combobox', { name: '쓰는 곳' }), '잇지 않음');
  await waitFor(() => expect(sent(fetchMock, `PATCH ${KAKAO}/templates/2`)).toEqual([{ use: 'D-3 준비 확인' }, { use: null }]));
  expect(within(row()).getByRole('combobox', { name: '쓰는 곳' })).toHaveDisplayValue('잇지 않음');
});

test('a refused 쓰는 곳 shows the server reason and keeps the old value', async () => {
  const message = '쓰는 곳은 50자까지입니다.';
  open(FILLED, { [`PATCH ${KAKAO}/templates/2`]: () => json(422, { code: 'too_long', message, detail: { field: 'use', max: 50 } }) });
  const b = await findFilled();
  const select = within(within(b).getByRole('table', { name: '카카오톡 문안' })).getAllByRole('row')[2].querySelector('select') as HTMLSelectElement;
  await userEvent.selectOptions(select, '승인 대기 알림');
  expect(await within(b).findByText(message)).toBeVisible();
  expect(select).toHaveDisplayValue('잇지 않음');
});

test('a template without a 「reply by SMS」 line is flagged 문자 회신 안내 없음, the others are not', async () => {
  open(FILLED);
  const b = await findFilled();
  const rows = within(within(b).getByRole('table', { name: '카카오톡 문안' })).getAllByRole('row').slice(1);
  expect(within(rows[1]).getByText('문자 회신 안내 없음')).toBeVisible();
  for (const i of [0, 2, 3]) expect(within(rows[i]).queryByText('문자 회신 안내 없음')).toBeNull();
});

test('when the path is confirmed re-reading posts sync once and draws the result; a cut listing is said', async () => {
  let release: () => void = () => {};
  const { fetchMock } = open({ ...FILLED, channels: [], templates: [] }, {
    [`POST ${KAKAO}/sync`]: () => new Promise<Response>((r) => (release = () => r(json(200, { ...FILLED, truncated: true })))),
  });
  const b = await findBlock('연결된 채널 없음');
  expect(reread(b)).toBeEnabled();
  await userEvent.click(reread(b));
  expect(within(b).getByRole('button', { name: '읽는 중…' })).toBeDisabled();
  expect(within(card()).getByRole('button', { name: '연결 진단' })).toBeDisabled();
  release();
  expect(await within(b).findByRole('table', { name: '카카오톡 문안' })).toBeVisible();
  expect(within(b).getByText(/일부만 읽었습니다/)).toBeVisible();
  expect(sent(fetchMock, `POST ${KAKAO}/sync`)).toHaveLength(1);
  expect(within(card()).getByRole('button', { name: '연결 진단' })).toBeEnabled();
});

test('a 501 from sync shows the server reason (not a generic error) and locks re-reading', async () => {
  const message = '채널·문안 목록을 읽는 길을 확인하지 못했습니다.';
  open({ ...FILLED, channels: [], templates: [] }, {
    [`POST ${KAKAO}/sync`]: () => json(501, { code: 'kakao_listing_unconfirmed', message, detail: null }),
  });
  const b = await findBlock('연결된 채널 없음');
  await userEvent.click(reread(b));
  expect(await within(b).findByText(message)).toBeVisible();
  expect(within(b).queryByText('요청을 처리할 수 없습니다.')).toBeNull();
  expect(within(b).queryByRole('alert')).toBeNull();
  expect(reread(b)).toBeDisabled();
});

test('409 diagnosis_running and 502 from sync show the server text', async () => {
  const running = '이 연결의 진단이 이미 돌고 있습니다. 끝난 뒤 다시 해 주세요.';
  let n = 0;
  open({ ...FILLED, channels: [], templates: [] }, {
    [`POST ${KAKAO}/sync`]: () =>
      ++n === 1
        ? json(409, { code: 'diagnosis_running', message: running, detail: null })
        : json(502, { code: 'kakao_sync_failed', message: '채널·문안을 읽지 못했습니다.', detail: { reason: 'timeout' } }),
  });
  const b = await findBlock('연결된 채널 없음');
  await userEvent.click(reread(b));
  expect(await within(b).findByText(running)).toBeVisible();
  await userEvent.click(reread(b));
  expect(await within(b).findByText('채널·문안을 읽지 못했습니다.')).toBeVisible();
});

test('while the connection diagnosis runs, re-reading and every 쓰는 곳 are locked', async () => {
  let release: () => void = () => {};
  const DIAG = { ran_at: '2026-11-24T01:00:00Z', state: 'done', by: null, sends: [], sent_real: false, sent_unknown: false, steps: [] };
  open(FILLED, { [`POST ${ONE}/diagnose`]: () => new Promise<Response>((r) => (release = () => r(json(200, DIAG)))) });
  const b = await findFilled();
  await userEvent.click(within(card()).getByRole('button', { name: '연결 진단' }));
  expect(reread(b)).toBeDisabled();
  for (const s of within(b).getAllByRole('combobox', { name: '쓰는 곳' })) expect(s).toBeDisabled();
  release();
  await waitFor(() => expect(reread(b)).toBeEnabled());
  for (const s of within(b).getAllByRole('combobox', { name: '쓰는 곳' })) expect(s).toBeEnabled();
});

test('nothing here sends, enables or marks KakaoTalk ready — only the read and the use PATCH go out', async () => {
  const { fetchMock } = open(FILLED, { [`PATCH ${KAKAO}/templates/3`]: { ...FILLED.templates[2], use: '승인 대기 알림' } });
  const b = await findFilled();
  await userEvent.selectOptions(within(within(b).getByRole('table', { name: '카카오톡 문안' })).getAllByRole('row')[3].querySelector('select') as HTMLSelectElement, '승인 대기 알림');
  await waitFor(() => expect(sent(fetchMock, `PATCH ${KAKAO}/templates/3`)).toHaveLength(1));
  const kakaoCalls = requests(fetchMock).filter((r) => r.url.includes('/kakao'));
  expect(kakaoCalls.map((r) => `${r.method} ${r.url}`)).toEqual([`GET ${KAKAO}`, `PATCH ${KAKAO}/templates/3`]);
  for (const r of requests(fetchMock)) expect(r.body).not.toMatch(/"channel"\s*:\s*"kakao"|"agent_kakao"|"ready"/);
  expect(within(b).getByText('준비 안 됨')).toBeVisible();
  expect(within(b).queryByRole('switch')).toBeNull();
});

test('a failed read still shows the band and keeps re-reading locked', async () => {
  open(() => json(500, { code: 'internal', message: '서버 오류입니다.', detail: null }));
  const b = await findBlock('서버 오류입니다.');
  expect(within(b).getByText(BAND)).toBeVisible();
  expect(reread(b)).toBeDisabled();
});
