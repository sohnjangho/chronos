// 「알림 연결」(Task 70 계약대로 가짜 응답). 키·번호·Account ID 는 모두 가상.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test } from 'vitest';
import { json } from '../../test-helpers';
import type { Diagnosis, NotifyConnection } from './notifyApi';
import { renderAs, resetAll, sent } from './testKit';

const SENTINEL_KEY = 'kat-test-key-ZZZZ9999';
const ACCOUNT = 'AC-test-account-0001';
const KAT = 'https://api.koreaaitel.com';
const LIST = '/api/notify/connections';
const ONE = `${LIST}/3`;

const DEFAULT_LIMITS = {
  daily_sms_total: 50,
  daily_calls_total: 10,
  per_contact_sms_daily: 5,
  per_contact_calls_daily: 2,
  max_call_seconds: 300,
  max_call_seconds_unknown: 120,
  auto_reply_hourly: 5,
  auto_reply_daily: 20,
  inbound_burst_count: 5,
  inbound_burst_minutes: 10,
  reply_grace_minutes: 30,
  unknown_notice_daily: 1,
};

function conn(over: Partial<NotifyConnection> = {}): NotifyConnection {
  return {
    id: 3,
    name: '현장 알림',
    provider: 'koreaaitel',
    base_url: KAT,
    secret_last4: '9999',
    account_id_masked: '…0001',
    sender_number_masked: '070-****-0123',
    sender_index: 0,
    senders: ['070-****-0123', '070-****-0456'],
    kakao_channel: null,
    test_mode: true,
    allow_numbers: [{ index: 0, number_masked: '010-****-0199', kind: 'mobile', can_test_sms: true }],
    allow_numbers_version: 'v1',
    test_sms_index: 0,
    limits: DEFAULT_LIMITS,
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

const DIAG: Diagnosis = {
  ran_at: '2026-11-23T05:12:00Z',
  sent_real: false,
  sent_unknown: false,
  steps: [
    { id: 'P1', label: '인증·발신번호', ok: true, skipped: false, detail: '인증됨 · 발신번호 2개', latency_ms: 412, notes: ['senderNumbers: 2개 · approved 2'] },
    { id: 'P2', label: '문자 1건', ok: false, skipped: true, detail: '실제 문자를 켜지 않아 건너뜀', latency_ms: null, notes: [] },
    { id: 'P3', label: '상태 조회', ok: false, skipped: true, detail: 'P2 를 건너뛰어 건너뜀', latency_ms: null, notes: [] },
    { id: 'P4', label: '받은 문자 목록', ok: false, skipped: false, detail: 'http_403 · 권한이 없습니다', latency_ms: 230, notes: ['status 403'] },
  ],
};

const card = () => screen.getByRole('article', { name: '현장 알림' });
const nav = () => screen.getByRole('navigation', { name: '설정 구역' });

function open(over: Record<string, unknown> = {}) {
  return renderAs('admin', { section: 'notify' }, {
    [LIST]: [conn()],
    [`${ONE}/diagnosis`]: () => json(200, null),
    [`${ONE}/limits`]: { values: DEFAULT_LIMITS, defaults: DEFAULT_LIMITS, ranges: {} },
    ...over,
  });
}

async function findCard() {
  return screen.findByRole('article', { name: '현장 알림' });
}

afterEach(resetAll);

test('the nav has 알림 연결 after 정보 API 연결 and the card shows only the masked forms', async () => {
  open();
  const names = within(nav()).getAllByRole('button').map((b) => b.textContent);
  expect(names.indexOf('알림 연결')).toBe(names.indexOf('정보 API 연결') + 1);
  expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('알림 연결');
  const c = await findCard();
  for (const text of ['한국AI통신', '연결됨', KAT, '…0001', '070-****-0123', '기본 연결']) expect(within(c).getAllByText(text)[0]).toBeVisible();
  expect(within(c).getByText(/^•+9999$/)).toBeVisible();
  for (const name of ['연결 테스트', '연결 진단', 'URL 수정', '키 교체', '삭제']) expect(within(c).getByRole('button', { name })).toBeVisible();
});

test('the section is admin-only and a user never calls the notify API', () => {
  const { fetchMock } = renderAs('user', { section: 'notify' }, { [LIST]: [conn()] });
  expect(within(nav()).queryByRole('button', { name: '알림 연결' })).toBeNull();
  expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('내 정보');
  expect(fetchMock.mock.calls.some(([url]) => String(url).startsWith('/api/notify'))).toBe(false);
});

test('add posts name, address, key and account id once, then clears both secret fields', async () => {
  let rows: NotifyConnection[] = [];
  const { fetchMock } = open({
    [LIST]: () => json(200, rows),
    [`POST ${LIST}`]: () => {
      rows = [conn()];
      return json(201, { ...rows[0], error: null });
    },
  });
  await userEvent.click(await screen.findByRole('button', { name: '+ 연결 추가' }));
  const form = screen.getByRole('group', { name: '알림 연결 추가' });
  expect(within(form).getByLabelText('공급자')).toHaveDisplayValue('한국AI통신');
  expect(within(form).getByLabelText('주소')).toHaveValue(KAT);
  const key = within(form).getByLabelText(/^API Key/);
  const account = within(form).getByLabelText(/^Account ID/);
  expect(key).toHaveAttribute('type', 'password');
  await userEvent.clear(within(form).getByLabelText('이름'));
  await userEvent.type(within(form).getByLabelText('이름'), '현장 알림');
  await userEvent.type(key, SENTINEL_KEY);
  await userEvent.type(account, ACCOUNT);
  await userEvent.click(within(form).getByRole('button', { name: '저장하고 연결 테스트' }));
  expect(await findCard()).toBeVisible();
  expect(sent(fetchMock, `POST ${LIST}`)).toEqual([{ name: '현장 알림', base_url: KAT, secret: SENTINEL_KEY, account_id: ACCOUNT }]);
  expect(screen.queryByRole('group', { name: '알림 연결 추가' })).toBeNull();
  expect(document.body.innerHTML).not.toContain(SENTINEL_KEY);
  expect(document.body.innerHTML).not.toContain(ACCOUNT);
});

test('a rejected add shows the reason line, keeps the form and empties the key', async () => {
  const message = 'API 키는 8자 이상이고 공백·줄바꿈 같은 글자가 없어야 합니다.';
  open({ [LIST]: [], [`POST ${LIST}`]: () => json(422, { code: 'invalid_secret', message, detail: null }) });
  await userEvent.click(await screen.findByRole('button', { name: '+ 연결 추가' }));
  const form = screen.getByRole('group', { name: '알림 연결 추가' });
  await userEvent.type(within(form).getByLabelText(/^API Key/), 'short key');
  await userEvent.type(within(form).getByLabelText(/^Account ID/), ACCOUNT);
  await userEvent.click(within(form).getByRole('button', { name: '저장하고 연결 테스트' }));
  expect(await within(form).findByText(message)).toBeVisible();
  expect(within(form).getByText('invalid_secret')).toBeVisible();
  expect(within(form).getByLabelText(/^API Key/)).toHaveValue('');
  expect(within(form).getByLabelText(/^Account ID/)).toHaveValue('');
});

test('saved but the probe failed: the reason is shown', async () => {
  open({
    [LIST]: [],
    [`POST ${LIST}`]: () => json(201, { ...conn({ status: 'failed' }), error: { code: 'bad_key', message: 'API 키가 맞지 않습니다.' } }),
  });
  await userEvent.click(await screen.findByRole('button', { name: '+ 연결 추가' }));
  const form = screen.getByRole('group', { name: '알림 연결 추가' });
  await userEvent.type(within(form).getByLabelText(/^API Key/), SENTINEL_KEY);
  await userEvent.type(within(form).getByLabelText(/^Account ID/), ACCOUNT);
  await userEvent.click(within(form).getByRole('button', { name: '저장하고 연결 테스트' }));
  expect(await screen.findByText('저장했지만 연결 시험에 실패했습니다: API 키가 맞지 않습니다.')).toBeVisible();
});

test('연결 테스트 shows the result line', async () => {
  open({ [`POST ${ONE}/test`]: { ok: false, latency_ms: 30000, senders: [], error: { code: 'overseas_ip', message: '나라 밖 IP 에서는 보낼 수 없습니다.' } } });
  await userEvent.click(within(await findCard()).getByRole('button', { name: '연결 테스트' }));
  const result = await within(card()).findByRole('status', { name: '연결 테스트 결과' });
  expect(within(result).getByText('나라 밖 IP 에서는 보낼 수 없습니다.')).toBeVisible();
  expect(within(result).getByText('overseas_ip')).toBeVisible();
});

test('연결 진단 draws one line per step with notes collapsed and the run time', async () => {
  const { fetchMock } = open({ [`POST ${ONE}/diagnose`]: DIAG });
  await userEvent.click(within(await findCard()).getByRole('button', { name: '연결 진단' }));
  const result = await within(card()).findByRole('region', { name: '연결 진단 결과' });
  const lines = within(result).getAllByRole('listitem');
  expect(lines).toHaveLength(4);
  expect(lines[0]).toHaveTextContent(/P1.*OK.*인증됨 · 발신번호 2개.*412ms/);
  expect(lines[1]).toHaveTextContent(/P2.*건너뜀.*실제 문자를 켜지 않아 건너뜀/);
  expect(lines[3]).toHaveTextContent(/P4.*FAIL.*http_403 · 권한이 없습니다.*230ms/);
  expect(within(lines[0]).getByText('senderNumbers: 2개 · approved 2')).not.toBeVisible();
  expect(within(result).getByText(/돌린 시각/)).toBeVisible();
  expect(sent(fetchMock, `POST ${ONE}/diagnose`)).toEqual([{ send: false }]);
});

test('the last stored diagnosis is shown when the section is opened again', async () => {
  open({ [`${ONE}/diagnosis`]: DIAG });
  const result = await within(await findCard()).findByRole('region', { name: '연결 진단 결과' });
  expect(within(result).getAllByRole('listitem')[0]).toHaveTextContent(/P1.*OK/);
});

test('the real SMS switch is locked with a reason when no allowed number can receive it', async () => {
  open({ [LIST]: [conn({ allow_numbers: [], test_sms_index: null })] });
  const c = await findCard();
  expect(within(c).getByRole('switch', { name: /실제 문자 1건 보내기/ })).toBeDisabled();
  expect(within(c).getByText(/허용 번호를 먼저 넣어 주세요/)).toBeVisible();
  expect(within(c).getByRole('button', { name: '시험 문자' })).toBeDisabled();
});

test('a real SMS goes only through the confirmation that shows the masked number, once', async () => {
  let release: () => void = () => {};
  const { fetchMock } = open({
    [`POST ${ONE}/diagnose`]: () => new Promise<Response>((r) => (release = () => r(json(200, { ...DIAG, sent_real: true })))),
  });
  const c = await findCard();
  await userEvent.click(within(c).getByRole('switch', { name: /실제 문자 1건 보내기/ }));
  await userEvent.click(within(c).getByRole('button', { name: '연결 진단' }));
  let confirm = within(c).getByRole('group', { name: '실제 문자 확인' });
  expect(confirm).toHaveTextContent('010-****-0199');
  await userEvent.click(within(confirm).getByRole('button', { name: '취소' }));
  expect(sent(fetchMock, `POST ${ONE}/diagnose`)).toHaveLength(0);
  await userEvent.click(within(c).getByRole('button', { name: '연결 진단' }));
  confirm = within(c).getByRole('group', { name: '실제 문자 확인' });
  const go = within(confirm).getByRole('button', { name: '보내기' });
  await userEvent.dblClick(go);
  expect(sent(fetchMock, `POST ${ONE}/diagnose`)).toEqual([{ send: true }]);
  expect(within(c).getByRole('button', { name: '시험 문자' })).toBeDisabled();
  release();
  expect(await within(c).findByRole('region', { name: '연결 진단 결과' })).toBeVisible();
});

test('시험 문자 runs P2·P3 only after confirming and shows diagnosis_running', async () => {
  const message = '이 연결의 진단이 이미 돌고 있습니다. 끝난 뒤 다시 해 주세요.';
  const { fetchMock } = open({ [`POST ${ONE}/diagnose`]: () => json(409, { code: 'diagnosis_running', message, detail: null }) });
  const c = await findCard();
  expect(within(c).getByRole('button', { name: '시험 문자' })).toBeDisabled();
  await userEvent.click(within(c).getByRole('switch', { name: /실제 문자 1건 보내기/ }));
  await userEvent.click(within(c).getByRole('button', { name: '시험 문자' }));
  await userEvent.click(within(within(c).getByRole('group', { name: '실제 문자 확인' })).getByRole('button', { name: '보내기' }));
  expect(await within(c).findByText(message)).toBeVisible();
  expect(sent(fetchMock, `POST ${ONE}/diagnose`)).toEqual([{ steps: ['P2', 'P3'], send: true }]);
});

test('sent but outcome unknown is shown as such, not as a failure', async () => {
  const unknown: Diagnosis = {
    ...DIAG,
    sent_unknown: true,
    steps: [{ id: 'P2', label: '문자 1건', ok: false, skipped: false, detail: 'ReadTimeout · 보냈는지 알 수 없음', latency_ms: 15000, notes: [] }],
  };
  open({ [`${ONE}/diagnosis`]: unknown });
  const result = await within(await findCard()).findByRole('region', { name: '연결 진단 결과' });
  const line = within(result).getAllByRole('listitem')[0];
  expect(line).toHaveTextContent(/P2.*확인 필요/);
  expect(line).not.toHaveTextContent('FAIL');
  expect(within(result).getByText(/다시 누르면 두 번째 문자가 갈 수 있습니다/)).toBeVisible();
});

test('switching SMS to 위임 asks first and sends agent_sms delegate; KakaoTalk stays locked', async () => {
  const { fetchMock } = open({ [`PATCH ${ONE}`]: { ...conn({ agent_sms: 'delegate' }), error: null } });
  const c = await findCard();
  const sms = within(c).getByRole('radiogroup', { name: '문자 발송 권한' });
  expect(within(sms).getByRole('radio', { name: '승인 받기' })).toBeChecked();
  await userEvent.click(within(sms).getByRole('radio', { name: '위임' }));
  const confirm = within(c).getByRole('group', { name: '위임 확인' });
  expect(confirm).toHaveTextContent('에이전트가 사람 확인 없이 보냅니다');
  await userEvent.click(within(confirm).getByRole('button', { name: '위임으로 바꾸기' }));
  await waitFor(() => expect(sent(fetchMock, `PATCH ${ONE}`)).toEqual([{ agent_sms: 'delegate' }]));
  const kakao = within(c).getByRole('radiogroup', { name: '카카오톡 발송 권한' });
  for (const r of within(kakao).getAllByRole('radio')) expect(r).toBeDisabled();
  expect(within(c).getAllByText(/카카오톡\(알림톡\)은 아직 쓸 수 없습니다/)[0]).toBeVisible();
  expect(within(c).getByLabelText('카카오톡 채널')).toBeDisabled();
});

test('turning test mode off asks first; cancelling sends nothing', async () => {
  const { fetchMock } = open({ [`PATCH ${ONE}`]: { ...conn({ test_mode: false }), error: null } });
  const c = await findCard();
  const toggle = within(c).getByRole('switch', { name: '시험 모드' });
  expect(toggle).toBeChecked();
  await userEvent.click(toggle);
  let confirm = within(c).getByRole('group', { name: '시험 모드 끄기 확인' });
  expect(confirm).toHaveTextContent('허용 번호가 아닌 사람에게도 실제로 나갑니다');
  await userEvent.click(within(confirm).getByRole('button', { name: '취소' }));
  expect(sent(fetchMock, `PATCH ${ONE}`)).toHaveLength(0);
  await userEvent.click(toggle);
  confirm = within(c).getByRole('group', { name: '시험 모드 끄기 확인' });
  await userEvent.click(within(confirm).getByRole('button', { name: '시험 모드 끄기' }));
  await waitFor(() => expect(sent(fetchMock, `PATCH ${ONE}`)).toEqual([{ test_mode: false }]));
});

test('allowed numbers are added by text and removed by index with the version', async () => {
  const two = conn({
    allow_numbers: [
      { index: 0, number_masked: '010-****-0199', kind: 'mobile', can_test_sms: true },
      { index: 1, number_masked: '02-****-0000', kind: 'landline', can_test_sms: false },
    ],
  });
  const { fetchMock } = open({ [LIST]: [two], [`PATCH ${ONE}`]: { ...two, error: null } });
  const c = await findCard();
  const list = within(c).getByRole('list', { name: '허용 번호' });
  await userEvent.click(within(within(list).getAllByRole('listitem')[1]).getByRole('button', { name: '빼기' }));
  await waitFor(() => expect(sent(fetchMock, `PATCH ${ONE}`)).toEqual([{ allow_numbers_remove: [1], allow_numbers_version: 'v1' }]));
  const input = within(c).getByLabelText('허용 번호 더하기');
  await userEvent.type(input, '010-0000-0199');
  await userEvent.click(within(c).getByRole('button', { name: '더하기' }));
  await waitFor(() => expect(sent(fetchMock, `PATCH ${ONE}`)[1]).toEqual({ allow_numbers_add: ['010-0000-0199'] }));
  await waitFor(() => expect(input).toHaveValue(''));
});

test('a changed allow list (409) reloads and asks again without retrying', async () => {
  const message = '허용 번호 목록이 그사이 바뀌었습니다. 새로 불러온 뒤 다시 지워 주세요.';
  const { fetchMock } = open({ [`PATCH ${ONE}`]: () => json(409, { code: 'allow_list_changed', message, detail: null }) });
  const c = await findCard();
  const reads = () => fetchMock.mock.calls.filter(([url, init]) => String(url) === LIST && !init?.method).length;
  const before = reads();
  await userEvent.click(within(within(c).getByRole('list', { name: '허용 번호' })).getByRole('button', { name: '빼기' }));
  expect(await within(c).findByText(message)).toBeVisible();
  await waitFor(() => expect(reads()).toBe(before + 1));
  expect(sent(fetchMock, `PATCH ${ONE}`)).toHaveLength(1);
});

test('the sender number is chosen by index', async () => {
  const { fetchMock } = open({ [`PATCH ${ONE}`]: { ...conn({ sender_index: 1 }), error: null } });
  const c = await findCard();
  await userEvent.selectOptions(within(c).getByRole('combobox', { name: '발신번호' }), '070-****-0456');
  await waitFor(() => expect(sent(fetchMock, `PATCH ${ONE}`)).toEqual([{ sender_index: 1 }]));
});

test('URL 수정 sends the address with the key; 키 교체 sends the key; both clear it', async () => {
  const { fetchMock } = open({ [`PATCH ${ONE}`]: { ...conn(), error: null } });
  const c = await findCard();
  await userEvent.click(within(c).getByRole('button', { name: 'URL 수정' }));
  let form = within(c).getByRole('group', { name: 'URL 수정' });
  const url = within(form).getByLabelText('주소');
  await userEvent.clear(url);
  await userEvent.type(url, 'https://api2.koreaaitel.com');
  await userEvent.type(within(form).getByLabelText(/^API Key/), SENTINEL_KEY);
  await userEvent.click(within(form).getByRole('button', { name: '저장' }));
  expect(await within(c).findByText('저장했습니다.')).toBeVisible();
  await userEvent.click(within(c).getByRole('button', { name: '키 교체' }));
  form = within(c).getByRole('group', { name: '키 교체' });
  await userEvent.type(within(form).getByLabelText(/^API Key/), SENTINEL_KEY);
  await userEvent.click(within(form).getByRole('button', { name: '저장' }));
  await waitFor(() =>
    expect(sent(fetchMock, `PATCH ${ONE}`)).toEqual([{ base_url: 'https://api2.koreaaitel.com', secret: SENTINEL_KEY }, { secret: SENTINEL_KEY }]),
  );
  expect(document.body.innerHTML).not.toContain(SENTINEL_KEY);
});

test('삭제 with history shows the server reason', async () => {
  const message = '연락 기록이 있어 지울 수 없습니다';
  open({ [`DELETE ${ONE}`]: () => json(409, { code: 'has_history', message, detail: null }) });
  const c = await findCard();
  await userEvent.click(within(c).getByRole('button', { name: '삭제' }));
  await userEvent.click(within(within(c).getByRole('group', { name: '연결 삭제 확인' })).getByRole('button', { name: '삭제' }));
  expect(await within(c).findByText(message)).toBeVisible();
});

test('the limits group uses the shared form for this connection', async () => {
  open();
  const c = await findCard();
  await userEvent.click(within(c).getByText(/^상한 —/));
  expect(await within(c).findByRole('spinbutton', { name: /^하루 문자/ })).toHaveValue(50);
});
