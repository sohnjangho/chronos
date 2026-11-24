// 「AI 전화」 묶음(Task 90 계약대로 가짜 응답). 키·번호는 모두 가상이고 실제 제공사를 부르지 않는다.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test } from 'vitest';
import { json } from '../../test-helpers';
import type { NotifyConnection } from './notifyApi';
import type { VoiceDiagnosis, VoiceModels, VoiceSettings, VoiceStep, VoiceStepId } from './voiceApi';
import { renderAs, resetAll, sent } from './testKit';
import { voiceStatus } from './VoiceBlock';
import { limitMs } from './VoiceDiagnosis';

const SENTINEL_KEY = 'gemini-test-key-QQQQ7777';
const LIST = '/api/notify/connections';
const ONE = `${LIST}/3`;
const VOICE = `${ONE}/voice`;
const FREE = '무료 등급 키로 한 통화의 내용은 구글의 제품 개선에 쓰일 수 있습니다. 실제 협력사와 통화하기 전에 유료 등급 키로 바꿔 주세요.';
const BAND = '음성 SDK 가 설치돼 있지 않습니다 — 설치는 PM 승인 뒤에 합니다';
const RUNNING = '이 연결의 진단이 이미 돌고 있습니다. 끝난 뒤 다시 해 주세요.';
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

function voice(over: Partial<VoiceSettings> = {}): VoiceSettings {
  return {
    connection_id: 3,
    provider: 'google',
    has_secret: true,
    secret_last4: '1234',
    model: '',
    agent_number_masked: '070-****-0456',
    agent_number_kind: 'internet',
    voice_male_contact: null,
    voice_female_contact: null,
    voice_unknown: null,
    voices_by_language: {},
    status: 'unknown',
    checked_at: null,
    sdk_installed: true,
    test_call_index: 0,
    key_notice: { code: 'google_free_tier', message: FREE },
    call_limits: { calls_per_request: 2, ring_seconds: 20, call_seconds: 60, inbound_wait_default: 90, inbound_wait_min: 10, inbound_wait_max: 180 },
    saved: true,
    model_effective: 'gemini-3.8-live',
    agent_number_effective_masked: '070-****-0456',
    agent_number_source: 'voice',
    ...over,
  };
}

const LABELS: Record<VoiceStepId, string> = {
  P5: '음성 SDK · 플랫폼 연결',
  P6: '한국어 시험 통화',
  P7: '통화 중 받아쓰기',
  P8: '통화 중 도구 호출',
  P9: '음성 목록 · 샘플',
  P10: '둘째 언어 통화',
  P11: 'AI 전화 번호를 에이전트에 묶기',
  P12: '걸려 온 통화 받기',
  P13: '건 번호 읽기',
  P14: '받지 않고 거절하기',
};
const RAN = '2026-11-24T01:00:00Z';
const notRun = (id: VoiceStepId): VoiceStep => ({
  id,
  label: LABELS[id],
  ok: false,
  skipped: true,
  detail: '이번에는 확인하지 않았습니다.',
  latency_ms: null,
  notes: [],
  code: 'skipped_not_requested',
  maybe_sent: false,
  pending: false,
  data: {},
  ran_at: null,
});
const IDS: VoiceStepId[] = ['P5', 'P6', 'P7', 'P8', 'P9', 'P10', 'P11', 'P12', 'P13', 'P14'];

function diag(over: Partial<Record<VoiceStepId, Partial<VoiceStep>>> = {}, rest: Partial<VoiceDiagnosis> = {}): VoiceDiagnosis {
  return {
    state: 'done',
    part: 'connection',
    ran_at: RAN,
    by: '김하늘',
    steps: IDS.map((id) => ({ ...notRun(id), ...(over[id] ? { ran_at: RAN } : {}), ...over[id] })),
    called_real: false,
    call_unknown: false,
    calls: [],
    ...rest,
  };
}

const CONNECTED = diag({
  P5: { ok: true, skipped: false, code: 'ok', detail: '음성 SDK 1.4 · 플랫폼에 연결됐습니다.', latency_ms: 840, data: { sdk_version: '1.4' }, notes: ['세션: GeminiRealtime'] },
  P9: { skipped: true, code: 'not_supported', detail: '플랫폼이 음성 목록을 주지 않아 확인하지 않았습니다.' },
  P11: { ok: false, skipped: false, code: 'bad_number', detail: 'AI 전화 번호가 거절됐습니다.', latency_ms: 120 },
});

const block = () => screen.getByRole('region', { name: 'AI 전화' });
const results = () => within(block()).getByRole('region', { name: '음성 진단 결과' });
const card = () => screen.getByRole('article', { name: '현장 알림' });
const posts = (fetchMock: ReturnType<typeof open>['fetchMock']) => sent(fetchMock, `POST ${VOICE}/diagnose`);

function open(over: Record<string, unknown> = {}) {
  return renderAs('admin', { section: 'notify' }, {
    [LIST]: [conn()],
    [`${ONE}/diagnosis`]: () => json(200, null),
    [`${ONE}/limits`]: { values: LIMITS, defaults: LIMITS, ranges: {} },
    [VOICE]: voice(),
    [`${VOICE}/diagnosis`]: () => json(200, null),
    [`${VOICE}/models`]: MODELS,
    ...over,
  });
}

const MODELS: VoiceModels = { models: ['gemini-3.8-live', 'gemini-x-live'], default: 'gemini-3.8-live', fallback: false, refused: false, no_live: false, reason: null };

/** 저장된 음성 설정을 읽어 카드가 그려질 때까지 기다린다. */
async function findBlock() {
  const b = await screen.findByRole('region', { name: 'AI 전화' });
  await within(b).findByRole('button', { name: '변경' });
  return b;
}

/** 카드의 [변경]으로 고치기 폼을 연다. */
async function editForm(b: HTMLElement) {
  await userEvent.click(within(b).getByRole('button', { name: '변경' }));
  return within(b).getByRole('group', { name: 'AI 전화 설정 고치기' });
}

/** 「실제 통화 포함」을 켜고 단추를 누른다(확인 창까지). */
async function askReal(b: HTMLElement, button: '시험 전화' | '받는 통화 확인') {
  await userEvent.click(within(b).getByRole('switch', { name: /실제 통화 포함/ }));
  await userEvent.click(within(b).getByRole('button', { name: button }));
}

afterEach(resetAll);

test('saved settings are a card: provider · model, the number and its source, only the last four of the key, status and buttons', async () => {
  open();
  const b = await findBlock();
  expect(within(b).queryByRole('combobox')).toBeNull(); // 폼은 [변경]으로만 연다
  expect(within(b).queryByLabelText(/^음성 모델 키/)).toBeNull();
  expect(within(b).getByText('구글 Gemini Live')).toBeVisible();
  expect(within(b).getByText('gemini-3.8-live · 기본값')).toBeVisible();
  expect(within(b).getByText('070-****-0456 · 따로 넣은 번호')).toBeVisible();
  expect(within(b).getByText('••••••••••••1234')).toBeVisible();
  expect(within(b).getByText('아직 진단 안 함', { selector: '.ui-badge' })).toBeVisible();
  expect(within(b).getByText(/300초/)).toBeVisible();
  expect(within(b).getByText(FREE)).toBeVisible();
  for (const name of ['음성 진단', '변경', '삭제']) expect(within(b).getByRole('button', { name })).toBeEnabled();
  expect(within(b).getByRole('button', { name: '시험 전화' })).toBeDisabled(); // 「실제 통화 포함」을 켜야 열린다(그대로)
  const form = await editForm(b);
  expect(within(form).getByRole('combobox', { name: '음성 모델 공급자' })).toHaveDisplayValue('구글 Gemini Live');
  expect(within(form).getByText('끝 4자리 ••••1234')).toBeVisible();
  const key = within(form).getByLabelText(/^음성 모델 키/);
  expect(key).toHaveAttribute('type', 'password');
  expect(key).toHaveAttribute('autocomplete', 'off');
  expect(key).toHaveValue('');
  expect(await within(form).findByRole('combobox', { name: '모델' })).toHaveValue('gemini-3.8-live');
  for (const name of ['음성 진단', '시험 전화', '변경', '삭제']) expect(within(b).getByRole('button', { name })).toBeDisabled();
});

test('saving a key sends only the key, empties the field and never shows it back', async () => {
  const { fetchMock } = open({ [`PUT ${VOICE}`]: voice({ secret_last4: '7777' }) });
  const b = await findBlock();
  const form = await editForm(b);
  await within(form).findByRole('combobox', { name: '모델' });
  const key = within(form).getByLabelText(/^음성 모델 키/);
  await userEvent.type(key, SENTINEL_KEY);
  await userEvent.click(within(form).getByRole('button', { name: '저장' }));
  expect(await within(b).findByText('••••••••••••7777')).toBeVisible();
  expect(sent(fetchMock, `PUT ${VOICE}`)).toEqual([{ secret: SENTINEL_KEY }]);
  expect(key).not.toBeInTheDocument(); // 저장하면 폼이 닫히고 카드로 돌아간다
  expect(document.body.innerHTML).not.toContain(SENTINEL_KEY);
  expect(fetchMock.mock.calls.some(([url]) => String(url).includes(SENTINEL_KEY))).toBe(false);
});

test('a refused key shows the server reason under the key field, empties it and does not echo it', async () => {
  const message = '음성 모델 키는 8자 이상이고 공백·줄바꿈 같은 글자가 없어야 합니다.';
  open({ [`PUT ${VOICE}`]: () => json(422, { code: 'invalid_secret', message, detail: null }) });
  const b = await findBlock();
  const form = await editForm(b);
  const key = within(form).getByLabelText(/^음성 모델 키/);
  await userEvent.type(key, 'bad key 1');
  await userEvent.click(within(form).getByRole('button', { name: '저장' }));
  const field = key.closest('.ui-field') as HTMLElement;
  expect(await within(field).findByText(message)).toBeVisible();
  expect(key).toHaveValue('');
  expect(document.body.innerHTML).not.toContain('bad key 1');
});

test('a refused 070 number is reported under the number field', async () => {
  const message = '번호 형식이 올바르지 않거나 쓸 수 없는 번호입니다.';
  open({ [`PUT ${VOICE}`]: () => json(422, { code: 'invalid_number', message, detail: { field: 'agent_number' } }) });
  const b = await findBlock();
  const form = await editForm(b);
  const num = within(form).getByLabelText('AI 전화 번호');
  await userEvent.type(num, '060-0000-0000');
  await userEvent.click(within(form).getByRole('button', { name: '저장' }));
  const field = num.closest('.ui-field') as HTMLElement;
  expect(await within(field).findByText(message)).toBeVisible();
});

test('changing the provider asks for the key again before it can be saved', async () => {
  const { fetchMock } = open({ [`PUT ${VOICE}`]: voice({ provider: 'openai', key_notice: null, secret_last4: '7777' }) });
  const b = await findBlock();
  const form = await editForm(b);
  await userEvent.selectOptions(within(form).getByRole('combobox', { name: '음성 모델 공급자' }), 'OpenAI Realtime');
  expect(within(form).getByText(/공급자를 바꾸면 음성 모델 키를 다시 넣어 주세요/)).toBeVisible();
  expect(within(form).getByLabelText('모델')).toHaveAttribute('placeholder', expect.stringContaining('기본 모델')); // OpenAI 는 지금처럼 글 칸
  const save = within(form).getByRole('button', { name: '저장' });
  expect(save).toBeDisabled();
  await userEvent.type(within(form).getByLabelText(/^음성 모델 키/), SENTINEL_KEY);
  await userEvent.click(save);
  await waitFor(() => expect(sent(fetchMock, `PUT ${VOICE}`)).toEqual([{ provider: 'openai', secret: SENTINEL_KEY }]));
  await waitFor(() => expect(within(b).queryByText(FREE)).toBeNull());
});

test('음성 진단 sends {} and draws all ten rows grouped under the three buttons, codes collapsed', async () => {
  const { fetchMock } = open({ [`POST ${VOICE}/diagnose`]: CONNECTED });
  const b = await findBlock();
  await userEvent.click(within(b).getByRole('button', { name: '음성 진단' }));
  await waitFor(() => expect(within(results()).getAllByRole('listitem')[0]).toHaveTextContent(/P5.*OK/));
  expect(posts(fetchMock)).toEqual([{}]);
  const rows = within(results()).getAllByRole('listitem');
  expect(rows.map((r) => r.querySelector('.st-nt-step-id')?.textContent)).toEqual(['P5', 'P9', 'P11', 'P6', 'P7', 'P8', 'P10', 'P12', 'P13', 'P14']);
  expect(rows[0]).toHaveTextContent(/P5.*OK.*음성 SDK · 플랫폼 연결.*음성 SDK 1\.4 · 플랫폼에 연결됐습니다\..*840ms/);
  expect(rows[1]).toHaveTextContent(/P9.*건너뜀.*플랫폼이 음성 목록을 주지 않아 확인하지 않았습니다\./);
  expect(rows[2]).toHaveTextContent(/P11.*FAIL.*AI 전화 번호가 거절됐습니다\./);
  expect(rows[3]).toHaveTextContent(/P6.*안 돌림.*이번에는 확인하지 않았습니다\./);
  expect(within(rows[3]).queryByText(/^메모/)).toBeNull();
  expect(within(rows[0]).getByText(/sdk_version/)).not.toBeVisible();
  expect(within(rows[2]).getByText(/bad_number/)).not.toBeVisible();
  for (const name of ['연결 확인', '시험 전화', '받는 통화']) expect(within(results()).getByRole('group', { name })).toBeVisible();
  expect(within(within(results()).getByRole('group', { name: '연결 확인' })).getByText(/돌린 시각/)).toBeVisible();
  expect(within(rows[2]).queryByRole('button')).toBeNull();
});

test('before any diagnosis the ten rows are drawn as not run yet', async () => {
  open();
  await findBlock();
  const rows = within(results()).getAllByRole('listitem');
  expect(rows).toHaveLength(10);
  for (const r of rows) expect(r).toHaveTextContent('안 돌림');
});

test('the last stored diagnosis is shown when the screen is opened again', async () => {
  open({ [`${VOICE}/diagnosis`]: CONNECTED });
  await findBlock();
  await waitFor(() => expect(within(results()).getAllByRole('listitem')[0]).toHaveTextContent(/P5.*OK/));
});

test('real calls are locked with a reason when there is no callable first allowed number', async () => {
  open({ [LIST]: [conn({ allow_numbers: [], test_sms_index: null })], [VOICE]: voice({ test_call_index: null }) });
  const b = await findBlock();
  expect(within(b).getByRole('switch', { name: /실제 통화 포함/ })).toBeDisabled();
  expect(within(b).getByRole('button', { name: '시험 전화' })).toBeDisabled();
  expect(within(b).getByRole('button', { name: '받는 통화 확인' })).toBeDisabled();
  expect(within(b).getByText(/허용 번호를 먼저 넣어 주세요/)).toBeVisible();
  expect(within(b).getByRole('button', { name: '음성 진단' })).toBeEnabled();
});

test('a test call goes only through the confirmation showing the masked number and the count, once, with the version', async () => {
  let release: () => void = () => {};
  const done = diag({ P6: { ok: true, skipped: false, code: 'ok', detail: '통화가 연결됐습니다 · 첫 응답 900ms' } }, { part: 'call', called_real: true });
  const { fetchMock } = open({
    [`POST ${VOICE}/diagnose`]: () => new Promise<Response>((r) => (release = () => r(json(200, done)))),
  });
  const b = await findBlock();
  expect(within(b).getByRole('button', { name: '시험 전화' })).toBeDisabled();
  await askReal(b, '시험 전화');
  let confirm = within(b).getByRole('group', { name: '실제 통화 확인' });
  expect(confirm).toHaveTextContent('010-****-0199');
  expect(confirm).toHaveTextContent('본인 번호로 전화가 최대 1통 걸려 옵니다');
  await userEvent.click(within(confirm).getByRole('button', { name: '취소' }));
  expect(posts(fetchMock)).toHaveLength(0);
  await userEvent.click(within(b).getByRole('checkbox', { name: /영어 첫마디/ }));
  await userEvent.click(within(b).getByRole('button', { name: '시험 전화' }));
  confirm = within(b).getByRole('group', { name: '실제 통화 확인' });
  expect(confirm).toHaveTextContent('본인 번호로 전화가 최대 2통 걸려 옵니다');
  await userEvent.dblClick(within(confirm).getByRole('button', { name: '전화 걸기' }));
  expect(posts(fetchMock)).toEqual([{ steps: ['P6', 'P7', 'P8', 'P10'], call: true, allow_numbers_version: 'v1' }]);
  release();
  await waitFor(() => expect(within(results()).getAllByRole('listitem')[3]).toHaveTextContent(/P6.*OK/));
});

test('while a voice diagnosis runs every diagnosis button of both blocks is disabled and the running step is shown', async () => {
  let release: () => void = () => {};
  open({ [`POST ${VOICE}/diagnose`]: () => new Promise<Response>((r) => (release = () => r(json(200, CONNECTED)))) });
  const b = await findBlock();
  await userEvent.click(within(b).getByRole('switch', { name: /실제 통화 포함/ }));
  await userEvent.click(within(b).getByRole('button', { name: '음성 진단' }));
  const status = within(b).getByRole('status', { name: '음성 진단 진행' });
  expect(status).toHaveTextContent(/P5 · P9 · P11/);
  expect(status).toHaveTextContent(/0:0\d/);
  for (const name of ['음성 진단', '시험 전화', '받는 통화 확인', '변경', '삭제']) expect(within(b).getByRole('button', { name })).toBeDisabled();
  expect(within(card()).getByRole('button', { name: '연결 진단' })).toBeDisabled();
  expect(within(card()).getByRole('switch', { name: /실제 문자 1건 보내기/ })).toBeDisabled();
  release();
  await waitFor(() => expect(within(b).getByRole('button', { name: '음성 진단' })).toBeEnabled());
  expect(within(card()).getByRole('button', { name: '연결 진단' })).toBeEnabled();
});

test('while the notify diagnosis runs the voice buttons are disabled', async () => {
  let release: () => void = () => {};
  const DIAG = { ran_at: RAN, state: 'done', by: null, sends: [], sent_real: false, sent_unknown: false, steps: [] };
  open({ [`POST ${ONE}/diagnose`]: () => new Promise<Response>((r) => (release = () => r(json(200, DIAG)))) });
  const b = await findBlock();
  await userEvent.click(within(card()).getByRole('button', { name: '연결 진단' }));
  expect(within(b).getByRole('button', { name: '음성 진단' })).toBeDisabled();
  expect(within(b).getByRole('switch', { name: /실제 통화 포함/ })).toBeDisabled();
  release();
  await waitFor(() => expect(within(b).getByRole('button', { name: '음성 진단' })).toBeEnabled());
});

test('409 diagnosis_running is shown as already running', async () => {
  open({ [`POST ${VOICE}/diagnose`]: () => json(409, { code: 'diagnosis_running', message: RUNNING, detail: null }) });
  const b = await findBlock();
  await userEvent.click(within(b).getByRole('button', { name: '음성 진단' }));
  expect(await within(b).findByText(RUNNING)).toBeVisible();
});

test('409 allow_list_changed reloads and re-opens the confirmation with the new number instead of retrying', async () => {
  const message = '허용 번호 목록이 그사이 바뀌었습니다. 새로 불러온 뒤 다시 해 주세요.';
  let rows = [conn()];
  const { fetchMock } = open({
    [LIST]: () => json(200, rows),
    [`POST ${VOICE}/diagnose`]: () => {
      rows = [conn({ allow_numbers: [{ index: 0, number_masked: '010-****-0288', kind: 'mobile', can_test_sms: true }], allow_numbers_version: 'v2' })];
      return json(409, { code: 'allow_list_changed', message, detail: null });
    },
  });
  const b = await findBlock();
  await askReal(b, '시험 전화');
  await userEvent.click(within(within(b).getByRole('group', { name: '실제 통화 확인' })).getByRole('button', { name: '전화 걸기' }));
  expect(await within(b).findByText(message)).toBeVisible();
  const again = await within(b).findByRole('group', { name: '실제 통화 확인' });
  await waitFor(() => expect(again).toHaveTextContent('010-****-0288'));
  expect(posts(fetchMock)).toHaveLength(1);
  await userEvent.click(within(again).getByRole('button', { name: '전화 걸기' }));
  await waitFor(() => expect(posts(fetchMock)[1]).toEqual({ call: true, allow_numbers_version: 'v2' }));
});

test('an unknown call outcome is 확인 필요, not a failure, and the test call cannot be pressed again at once', async () => {
  const unknown = diag(
    { P6: { ok: false, skipped: false, maybe_sent: true, code: 'cut_unconfirmed', detail: '전화가 걸렸을 수도 있습니다. 다시 누르면 또 걸릴 수 있습니다.' } },
    { part: 'call', call_unknown: true, calls: [{ at: RAN, by: '김하늘', outcome: 'unknown' }] },
  );
  open({ [`${VOICE}/diagnosis`]: unknown });
  const b = await findBlock();
  await waitFor(() => expect(within(results()).getAllByRole('listitem')[3]).toHaveTextContent(/P6.*확인 필요/));
  const p6 = within(results()).getAllByRole('listitem')[3];
  expect(p6).not.toHaveTextContent('FAIL');
  expect(within(p6).queryByRole('button')).toBeNull();
  expect(within(b).getByText(/휴대전화를 확인해 주세요\. 다시 누르면 또 걸릴 수 있습니다/)).toBeVisible();
  await userEvent.click(within(b).getByRole('switch', { name: /실제 통화 포함/ }));
  expect(within(b).getByRole('button', { name: '시험 전화' })).toBeDisabled();
  expect(within(results()).getByText('시험 전화 기록 1건')).toBeVisible();
});

test('call_unknown_pending needs its own recall confirmation before confirm_recall is sent', async () => {
  const message = '앞서 건 시험 전화가 걸렸는지·끊겼는지 아직 모릅니다. 휴대전화를 먼저 확인해 주세요(통화 중이면 끊어 주세요). 확인한 뒤에도 다시 걸려면 다시 걸기를 골라 주세요.';
  let calls = 0;
  const { fetchMock } = open({
    [`POST ${VOICE}/diagnose`]: () => (++calls === 1 ? json(409, { code: 'call_unknown_pending', message, detail: null }) : json(200, CONNECTED)),
  });
  const b = await findBlock();
  await askReal(b, '시험 전화');
  await userEvent.click(within(within(b).getByRole('group', { name: '실제 통화 확인' })).getByRole('button', { name: '전화 걸기' }));
  expect(await within(b).findByText(message)).toBeVisible();
  await userEvent.click(within(b).getByRole('button', { name: '그래도 다시 걸기' }));
  const confirm = within(b).getByRole('group', { name: '다시 걸기 확인' });
  expect(confirm).toHaveTextContent('010-****-0199');
  expect(posts(fetchMock)).toHaveLength(1);
  await userEvent.click(within(confirm).getByRole('button', { name: '다시 걸기' }));
  await waitFor(() =>
    expect(posts(fetchMock)).toEqual([
      { call: true, allow_numbers_version: 'v1' },
      { call: true, allow_numbers_version: 'v1', confirm_recall: true },
    ]),
  );
});

test('a call request that ends without a clear answer says to check the phone and re-reads the last diagnosis', async () => {
  const { fetchMock } = open({ [`POST ${VOICE}/diagnose`]: () => json(502, { code: 'http_error', message: '요청을 처리할 수 없습니다.', detail: null }) });
  const b = await findBlock();
  const reads = () => fetchMock.mock.calls.filter(([url, init]) => String(url) === `${VOICE}/diagnosis` && !(init as RequestInit | undefined)?.method).length;
  await waitFor(() => expect(reads()).toBe(1));
  await askReal(b, '시험 전화');
  await userEvent.click(within(within(b).getByRole('group', { name: '실제 통화 확인' })).getByRole('button', { name: '전화 걸기' }));
  expect(await within(b).findByText(/전화가 걸렸는지 확인 필요/)).toBeVisible();
  await waitFor(() => expect(reads()).toBe(2));
  expect(within(b).queryByText('요청을 처리할 수 없습니다.')).toBeNull();
});

test('받는 통화 확인 asks first, shows where to call with the time left, then asks for the reject call', async () => {
  let release: () => void = () => {};
  let n = 0;
  const first = diag(
    {
      P12: { ok: true, skipped: false, code: 'ok', detail: '걸려 온 통화를 받았습니다.' },
      P13: { ok: true, skipped: false, code: 'ok', detail: '건 번호를 읽었습니다.' },
    },
    { part: 'inbound' },
  );
  // 걸음 줄은 이어진다: 둘째 응답에도 앞 요청의 P12·P13 결과가 그대로 있다.
  const second: VoiceDiagnosis = {
    ...first,
    steps: first.steps.map((s) => (s.id === 'P14' ? { ...s, ok: false, skipped: false, code: 'no_inbound', detail: '90초 동안 걸려 온 전화가 없었습니다.', ran_at: RAN } : s)),
  };
  const { fetchMock } = open({
    [`POST ${VOICE}/diagnose`]: () => (++n === 1 ? new Promise<Response>((r) => (release = () => r(json(200, first)))) : json(200, second)),
  });
  const b = await findBlock();
  await askReal(b, '받는 통화 확인');
  const confirm = within(b).getByRole('group', { name: '받는 통화 확인 시작' });
  expect(confirm).toHaveTextContent('010-****-0199');
  expect(confirm).toHaveTextContent('070-****-0456');
  expect(posts(fetchMock)).toHaveLength(0);
  await userEvent.click(within(confirm).getByRole('button', { name: '시작' }));
  const status = within(b).getByRole('status', { name: '음성 진단 진행' });
  expect(status).toHaveTextContent('지금 휴대전화로 070-****-0456에 걸어 주세요');
  expect(status).toHaveTextContent(/남은 시간 1:[23]\d/);
  expect(posts(fetchMock)).toEqual([{ steps: ['P12', 'P13'], inbound: true, allow_numbers_version: 'v1' }]);
  release();
  await waitFor(() => expect(posts(fetchMock)).toHaveLength(2));
  expect(posts(fetchMock)[1]).toEqual({ steps: ['P14'], inbound: true, allow_numbers_version: 'v1' });
  await waitFor(() => expect(within(results()).getAllByRole('listitem')[9]).toHaveTextContent(/P14.*FAIL.*90초 동안 걸려 온 전화가 없었습니다\./));
  expect(within(results()).getAllByRole('listitem')[7]).toHaveTextContent(/P12.*OK/);
});

test('when nobody called in, the reject call is not asked for', async () => {
  const none = diag({ P12: { ok: false, skipped: false, code: 'no_inbound', detail: '90초 동안 걸려 온 전화가 없었습니다.' } }, { part: 'inbound' });
  const { fetchMock } = open({ [`POST ${VOICE}/diagnose`]: none });
  const b = await findBlock();
  await askReal(b, '받는 통화 확인');
  await userEvent.click(within(within(b).getByRole('group', { name: '받는 통화 확인 시작' })).getByRole('button', { name: '시작' }));
  await waitFor(() => expect(within(results()).getAllByRole('listitem')[7]).toHaveTextContent(/P12.*FAIL.*90초 동안/));
  expect(posts(fetchMock)).toHaveLength(1);
  // P14 는 돌리지 않았지만 「안 돌림」이 아니라 까닭을 말한다.
  const p14 = within(results()).getAllByRole('listitem')[9];
  expect(p14).toHaveTextContent(/P14.*건너뜀.*받는 통화가 확인되지 않아 돌리지 않았습니다/);
  expect(p14).not.toHaveTextContent('안 돌림');
});

test('without the voice SDK the band is shown, the call buttons are locked and the provider choice stays', async () => {
  open({ [VOICE]: voice({ sdk_installed: false }) });
  const b = await findBlock();
  expect(within(b).getByText(BAND)).toBeVisible();
  expect(within(b).getByRole('switch', { name: /실제 통화 포함/ })).toBeDisabled();
  expect(within(b).getByRole('button', { name: '시험 전화' })).toBeDisabled();
  expect(within(b).getByRole('button', { name: '받는 통화 확인' })).toBeDisabled();
  expect(within(b).getByRole('button', { name: '음성 진단' })).toBeEnabled();
  expect(within(await editForm(b)).getByRole('combobox', { name: '음성 모델 공급자' })).toBeEnabled();
  const band = within(b).getByText(BAND);
  expect(band.compareDocumentPosition(results()) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});

test('a missing provider extra (P5 sdk_extra_missing) shows the band too', async () => {
  const extra = diag({ P5: { ok: false, skipped: false, code: 'sdk_extra_missing', detail: '고른 음성 모델에 필요한 묶음이 설치돼 있지 않습니다.' } });
  open({ [VOICE]: voice({ provider: 'openai', key_notice: null }), [`${VOICE}/diagnosis`]: extra });
  const b = await findBlock();
  expect(await within(b).findByText(/고른 음성 모델에 필요한 묶음이 설치돼 있지 않습니다 — 설치는 PM 승인 뒤에 합니다/)).toBeVisible();
  expect(within(b).getByRole('button', { name: '시험 전화' })).toBeDisabled();
});

test('the dashboard agent has no voice diagnosis and no free-tier notice', async () => {
  open({ [VOICE]: voice({ provider: 'dashboard', has_secret: false, secret_last4: '', key_notice: null }) });
  const b = await findBlock();
  expect(within(b).getByRole('button', { name: '음성 진단' })).toBeDisabled();
  expect(within(b).getByText('대시보드 에이전트 방식은 음성 진단을 하지 않습니다.')).toBeVisible();
  expect(within(b).queryByText(FREE)).toBeNull();
});

// ── 고침 1차(리뷰 Important 1·2) ──

test('an open confirm dialog in the notify block locks the voice buttons, and the other way round', async () => {
  open();
  const b = await findBlock();
  const c = card();
  // 알림 연결 카드 자신의 단추(「AI 전화」 카드에도 [삭제]가 있다)
  const own = (name: string) => within(c).getAllByRole('button', { name }).find((el) => !b.contains(el)) as HTMLElement;
  await userEvent.click(within(c).getByRole('switch', { name: /실제 문자 1건 보내기/ }));
  await userEvent.click(within(c).getByRole('button', { name: '시험 문자' }));
  expect(within(c).getByRole('group', { name: '실제 문자 확인' })).toBeVisible();
  expect(within(b).getByRole('button', { name: '음성 진단' })).toBeDisabled();
  expect(within(b).getByRole('switch', { name: /실제 통화 포함/ })).toBeDisabled();
  await userEvent.click(within(within(c).getByRole('group', { name: '실제 문자 확인' })).getByRole('button', { name: '취소' }));
  expect(within(b).getByRole('button', { name: '음성 진단' })).toBeEnabled();
  await userEvent.click(own('삭제'));
  expect(within(c).getByRole('group', { name: '연결 삭제 확인' })).toBeVisible();
  expect(within(b).getByRole('button', { name: '음성 진단' })).toBeDisabled();
  await userEvent.click(within(within(c).getByRole('group', { name: '연결 삭제 확인' })).getByRole('button', { name: '취소' }));
  // 음성 쪽 확인 창이 열려 있으면 알림 쪽 진단 단추가 잠긴다.
  await askReal(b, '시험 전화');
  expect(within(b).getByRole('group', { name: '실제 통화 확인' })).toBeVisible();
  expect(within(c).getByRole('button', { name: '연결 진단' })).toBeDisabled();
  expect(own('삭제')).toBeDisabled();
});

test('a diagnosis read back as running shows 도는 중 in its group, never 안 돌림', async () => {
  const running: VoiceDiagnosis = { state: 'running', part: 'call', ran_at: RAN, by: '김하늘', steps: [], called_real: false, call_unknown: false, calls: [] };
  open({ [`${VOICE}/diagnosis`]: running });
  const b = await findBlock();
  const call = await within(results()).findByRole('group', { name: '시험 전화' });
  await waitFor(() => expect(within(call).getAllByRole('listitem')[0]).toHaveTextContent(/P6.*도는 중.*진단이 도는 중입니다/));
  expect(within(call).getByText(/도는 중 — 김하늘/)).toBeVisible();
  expect(within(results()).queryByText('안 돌림')).toBeNull();
  expect(within(results()).queryByText(/아직 돌리지 않/)).toBeNull();
  expect(within(b).getByRole('button', { name: '음성 진단' })).toBeDisabled();
});

// ── 11-24 손보기: 모델은 목록에서 · 번호는 연결에서 · 저장하면 카드 ──

const FRESH = voice({
  saved: false,
  has_secret: false,
  secret_last4: '',
  agent_number_masked: null,
  agent_number_kind: '',
  agent_number_effective_masked: '070-****-0123',
  agent_number_source: 'connection',
});

/** 저장 전: 넣기 폼이 그려질 때까지. */
async function findAddForm() {
  const b = await screen.findByRole('region', { name: 'AI 전화' });
  return { b, form: await within(b).findByRole('group', { name: 'AI 전화 설정 넣기' }) };
}

test('before anything is saved the add form shows the Live model list with gemini-3.8-live first and 직접 입력', async () => {
  const { fetchMock } = open({ [VOICE]: FRESH, [`PUT ${VOICE}`]: voice({ model: 'gemini-x-live', model_effective: 'gemini-x-live', agent_number_source: 'connection' }) });
  const { b, form } = await findAddForm();
  expect(within(b).queryByRole('button', { name: '변경' })).toBeNull();
  expect(within(b).queryByRole('region', { name: '음성 진단 결과' })).toBeNull();
  const select = await within(form).findByRole('combobox', { name: '모델' });
  await waitFor(() => expect(within(select).getAllByRole('option').map((o) => o.textContent)).toEqual(['gemini-3.8-live (기본)', 'gemini-x-live', '직접 입력']));
  expect(select).toHaveValue('gemini-3.8-live');
  expect(within(form).getByText('이 키로 쓸 수 있는 실시간 음성 모델 2개')).toBeVisible();
  await userEvent.selectOptions(select, '직접 입력');
  expect(within(form).getByLabelText('모델 이름')).toHaveFocus();
  await userEvent.selectOptions(select, 'gemini-x-live');
  const save = within(form).getByRole('button', { name: '저장' });
  expect(save).toBeDisabled(); // 키 없이는 저장하지 않는다
  await userEvent.type(within(form).getByLabelText(/^음성 모델 키/), SENTINEL_KEY);
  await userEvent.click(save);
  await waitFor(() => expect(sent(fetchMock, `PUT ${VOICE}`)).toEqual([{ secret: SENTINEL_KEY, model: 'gemini-x-live' }]));
  expect(await within(b).findByRole('button', { name: '변경' })).toBeVisible();
  expect(document.body.innerHTML).not.toContain(SENTINEL_KEY);
});

test('the default model is not sent when it was left as it is', async () => {
  const { fetchMock } = open({ [VOICE]: FRESH, [`PUT ${VOICE}`]: voice() });
  const { form } = await findAddForm();
  await within(form).findByRole('combobox', { name: '모델' });
  await userEvent.type(within(form).getByLabelText(/^음성 모델 키/), SENTINEL_KEY);
  await userEvent.click(within(form).getByRole('button', { name: '저장' }));
  await waitFor(() => expect(sent(fetchMock, `PUT ${VOICE}`)).toEqual([{ secret: SENTINEL_KEY }]));
});

test('when the list could not be read the select still offers the default and says why', async () => {
  const reason = '구글이 시간 안에 답하지 않아 기본 목록을 보여 줍니다.';
  open({ [VOICE]: FRESH, [`${VOICE}/models`]: { models: ['gemini-3.8-live'], default: 'gemini-3.8-live', fallback: true, refused: false, no_live: false, reason } });
  const { form } = await findAddForm();
  expect(await within(form).findByText(reason)).toBeVisible();
  expect(within(form).getByRole('combobox', { name: '모델' })).toHaveValue('gemini-3.8-live');
});

test('a stored model the key cannot use is kept visible and marked', async () => {
  open({ [VOICE]: voice({ model: 'gemini-3.1-flash-live-preview', model_effective: 'gemini-3.1-flash-live-preview' }) });
  const b = await findBlock();
  const select = await within(await editForm(b)).findByRole('combobox', { name: '모델' });
  await waitFor(() => expect(select).toHaveDisplayValue('gemini-3.1-flash-live-preview — 이 키로 쓸 수 없음'));
});

test('the AI call number defaults to the KoreaAITel number and [다른 번호 쓰기] reveals the field', async () => {
  const { fetchMock } = open({ [VOICE]: FRESH, [`PUT ${VOICE}`]: voice() });
  const { form } = await findAddForm();
  const line = within(form).getByRole('group', { name: 'AI 전화 번호' });
  expect(line).toHaveTextContent('한국AI통신 연결의 번호(070-****-0123)를 씁니다');
  expect(within(form).queryByRole('textbox', { name: 'AI 전화 번호' })).toBeNull();
  await userEvent.click(within(line).getByRole('button', { name: '다른 번호 쓰기' }));
  const field = within(form).getByLabelText('AI 전화 번호');
  expect(field).toHaveFocus();
  await userEvent.type(field, '070-0000-0456');
  await userEvent.type(within(form).getByLabelText(/^음성 모델 키/), SENTINEL_KEY);
  await userEvent.click(within(form).getByRole('button', { name: '저장' }));
  await waitFor(() => expect(sent(fetchMock, `PUT ${VOICE}`)).toEqual([{ secret: SENTINEL_KEY, agent_number: '070-0000-0456' }]));
});

test('the card names the number in use and where it comes from', async () => {
  open({ [VOICE]: voice({ agent_number_masked: null, agent_number_effective_masked: '070-****-0123', agent_number_source: 'connection' }) });
  const b = await findBlock();
  expect(within(b).getByText('070-****-0123 · 한국AI통신 연결의 번호')).toBeVisible();
});

test('a stored own number can be put back to the KoreaAITel number', async () => {
  const { fetchMock } = open({ [`PUT ${VOICE}`]: voice({ agent_number_masked: null, agent_number_source: 'connection' }) });
  const b = await findBlock();
  const form = await editForm(b);
  await userEvent.click(within(form).getByRole('button', { name: '연결의 번호(070-****-0123) 쓰기' }));
  expect(within(form).getByRole('group', { name: 'AI 전화 번호' })).toHaveTextContent('저장하면 바뀝니다');
  await userEvent.click(within(form).getByRole('button', { name: '저장' }));
  await waitFor(() => expect(sent(fetchMock, `PUT ${VOICE}`)).toEqual([{ agent_number: null }]));
});

test('[변경] then 취소 closes the form without sending anything', async () => {
  const { fetchMock } = open();
  const b = await findBlock();
  const form = await editForm(b);
  await userEvent.click(within(form).getByRole('button', { name: '취소' }));
  expect(within(b).queryByRole('group', { name: 'AI 전화 설정 고치기' })).toBeNull();
  expect(sent(fetchMock, `PUT ${VOICE}`)).toEqual([]);
  expect(within(b).getByRole('button', { name: '음성 진단' })).toBeEnabled();
});

test('[삭제] asks first, sends DELETE and shows the add form again', async () => {
  let gone = false;
  const { fetchMock } = open({
    [VOICE]: () => json(200, gone ? FRESH : voice()),
    [`DELETE ${VOICE}`]: () => ((gone = true), new Response(null, { status: 204 })),
  });
  const b = await findBlock();
  await userEvent.click(within(b).getByRole('button', { name: '삭제' }));
  const confirm = within(b).getByRole('group', { name: 'AI 전화 삭제 확인' });
  expect(confirm).toHaveTextContent('음성 모델 키·AI 전화 번호');
  expect(within(card()).getByRole('button', { name: '연결 진단' })).toBeDisabled(); // 확인 창이 열려 있으면 알림 쪽도 잠근다
  await userEvent.click(within(confirm).getByRole('button', { name: '취소' }));
  expect(sent(fetchMock, `DELETE ${VOICE}`)).toHaveLength(0);
  await userEvent.click(within(b).getByRole('button', { name: '삭제' }));
  await userEvent.click(within(within(b).getByRole('group', { name: 'AI 전화 삭제 확인' })).getByRole('button', { name: '삭제' }));
  expect(await screen.findByRole('group', { name: 'AI 전화 설정 넣기' })).toBeVisible();
  expect(sent(fetchMock, `DELETE ${VOICE}`)).toHaveLength(1);
});

test('a refused delete (diagnosis running) is shown and the card stays', async () => {
  open({ [`DELETE ${VOICE}`]: () => json(409, { code: 'diagnosis_running', message: RUNNING, detail: null }) });
  const b = await findBlock();
  await userEvent.click(within(b).getByRole('button', { name: '삭제' }));
  await userEvent.click(within(within(b).getByRole('group', { name: 'AI 전화 삭제 확인' })).getByRole('button', { name: '삭제' }));
  expect(await within(b).findByText(RUNNING)).toBeVisible();
  expect(within(b).getByRole('button', { name: '변경' })).toBeVisible();
});

test('the card status: 연결됨 · 실패 · 확인 필요(never 실패 for an unknown call) · 아직 진단 안 함', () => {
  const ran = diag({ P5: { ok: true, skipped: false, code: 'ok', detail: '연결됐습니다.' } });
  expect(voiceStatus(voice({ status: 'ok' }), ran)).toEqual({ tone: 'success', text: '연결됨' });
  expect(voiceStatus(voice({ status: 'failed' }), ran)).toEqual({ tone: 'danger', text: '실패' });
  expect(voiceStatus(voice({ status: 'unknown' }), null)).toEqual({ tone: 'neutral', text: '아직 진단 안 함' });
  expect(voiceStatus(voice({ status: 'unknown' }), diag())).toEqual({ tone: 'neutral', text: '아직 진단 안 함' });
  expect(voiceStatus(voice({ status: 'unknown' }), ran)).toEqual({ tone: 'warning', text: '확인 필요' });
  const unknownCall = diag({ P6: { ok: false, skipped: false, maybe_sent: true, code: 'cut_unconfirmed', detail: '모름' } }, { call_unknown: true });
  expect(voiceStatus(voice({ status: 'ok' }), unknownCall)).toEqual({ tone: 'warning', text: '확인 필요' });
  const pending = diag({ P5: { ok: false, skipped: false, pending: true, code: 'timeout', detail: '확인하지 못했습니다.' } });
  expect(voiceStatus(voice({ status: 'unknown' }), pending).text).toBe('확인 필요');
});

// ── 고침 1: 결과 모름은 실패가 아님(서버 꼴 그대로) · 연결의 번호를 화면 끝까지 ──

const UNKNOWN_P6: Partial<VoiceStep> = { ok: false, skipped: false, maybe_sent: true, pending: false, code: 'cut_unconfirmed', detail: '끊으려 했지만 통화가 끊겼는지 확인하지 못했습니다.' };

test('an unknown call outcome is 확인 필요 even when the server status is failed (a definite failure elsewhere)', () => {
  // 서버가 실제로 낼 수 있는 꼴: P11 분명한 실패 → status failed, 그 뒤 마지막 시험 전화가 모름 → call_unknown true
  const d = diag(
    { P5: { ok: true, skipped: false, code: 'ok', detail: '연결됐습니다.' }, P11: { ok: false, skipped: false, code: 'bad_number', detail: '거절됐습니다.' }, P6: UNKNOWN_P6 },
    { part: 'call', call_unknown: true, calls: [{ at: RAN, by: '김하늘', outcome: 'unknown' }] },
  );
  expect(voiceStatus(voice({ status: 'failed' }), d)).toEqual({ tone: 'warning', text: '확인 필요' });
  // 고침 뒤 서버: P5·P11 성공 + P6 모름 → status ok 그대로 — 카드는 「확인 필요」
  const ok = diag({ P5: { ok: true, skipped: false, code: 'ok', detail: '연결됐습니다.' }, P11: { ok: true, skipped: false, code: 'ok', detail: '묶였습니다.' }, P6: UNKNOWN_P6 }, { part: 'call', call_unknown: true });
  expect(voiceStatus(voice({ status: 'ok' }), ok).text).toBe('확인 필요');
});

const FROM_CONN = voice({ agent_number_masked: null, agent_number_kind: '', agent_number_effective_masked: '070-****-0123', agent_number_source: 'connection' });

test('with the KoreaAITel number in use, real calls are open and the inbound dialog and running line name that number', async () => {
  let release: () => void = () => {};
  open({
    [VOICE]: FROM_CONN,
    [`POST ${VOICE}/diagnose`]: () => new Promise<Response>((r) => (release = () => r(json(200, diag({}, { part: 'inbound' }))))),
  });
  const b = await findBlock();
  expect(within(b).getByRole('switch', { name: /실제 통화 포함/ })).toBeEnabled();
  expect(within(b).queryByText(/AI 전화 번호를 먼저 넣어 주세요/)).toBeNull();
  await askReal(b, '받는 통화 확인');
  const confirm = within(b).getByRole('group', { name: '받는 통화 확인 시작' });
  expect(confirm).toHaveTextContent('AI 전화 번호 070-****-0123에 두 번 걸어 주세요');
  await userEvent.click(within(confirm).getByRole('button', { name: '시작' }));
  expect(within(b).getByRole('status', { name: '음성 진단 진행' })).toHaveTextContent('지금 휴대전화로 070-****-0123에 걸어 주세요');
  release();
});

test('only with no number anywhere does it ask for the AI call number', async () => {
  open({ [VOICE]: voice({ agent_number_masked: null, agent_number_effective_masked: null, agent_number_source: null, test_call_index: null }) });
  const b = await findBlock();
  expect(within(b).getByText('AI 전화 번호를 먼저 넣어 주세요.')).toBeVisible();
});

// ── 고침 2: 구글이 거절한 키 — 카드에 크게, 가짜 목록 없음, 시험 전화 잠금 ──

const REFUSED_TEXT = '구글이 이 키로 Gemini API 를 쓰지 못하게 합니다(권한 없음). Google AI Studio 에서 만든 Gemini API 키를 넣거나, 이 키의 프로젝트에서 Generative Language API 를 켜 주세요.';
const REFUSED: VoiceModels = { models: [], default: 'gemini-3.8-live', fallback: true, refused: true, no_live: false, reason: REFUSED_TEXT };

test('a key Google refused makes the card 실패 with the reason, locks real calls and shows no fake model list', async () => {
  open({ [`${VOICE}/models`]: REFUSED, [VOICE]: voice({ status: 'ok' }) });
  const b = await findBlock();
  await waitFor(() => expect(within(b).getByText('실패', { selector: '.ui-badge' })).toBeVisible());
  expect(within(b).getByRole('alert')).toHaveTextContent(REFUSED_TEXT);
  expect(within(b).getByRole('switch', { name: /실제 통화 포함/ })).toBeDisabled();
  expect(within(b).getByRole('button', { name: '시험 전화' })).toBeDisabled();
  expect(within(b).getByRole('button', { name: '받는 통화 확인' })).toBeDisabled();
  expect(within(b).getByText(/구글이 키를 거절해 전화를 걸 수 없습니다/)).toBeVisible();
  const select = within(await editForm(b)).getByRole('combobox', { name: '모델' });
  expect(within(select).getAllByRole('option').map((o) => o.textContent)).toEqual(['gemini-3.8-live', '직접 입력']);
  expect(within(b).getByText('키가 거절돼 목록을 읽지 못했습니다')).toBeVisible();
});

test('saving a new key reads the model list again', async () => {
  let refused = true;
  const { fetchMock } = open({
    [`${VOICE}/models`]: () => json(200, refused ? REFUSED : MODELS),
    [`PUT ${VOICE}`]: () => ((refused = false), json(200, voice({ secret_last4: '7777' }))),
  });
  const reads = () => fetchMock.mock.calls.filter(([url]) => String(url) === `${VOICE}/models`).length;
  const b = await findBlock();
  await waitFor(() => expect(within(b).getByRole('alert')).toHaveTextContent(REFUSED_TEXT));
  const before = reads();
  const form = await editForm(b);
  await userEvent.type(within(form).getByLabelText(/^음성 모델 키/), SENTINEL_KEY);
  await userEvent.click(within(form).getByRole('button', { name: '저장' }));
  await waitFor(() => expect(reads()).toBeGreaterThan(before));
  await waitFor(() => expect(within(b).queryByRole('alert')).toBeNull());
  expect(within(b).getByRole('switch', { name: /실제 통화 포함/ })).toBeEnabled();
});

// ── 고침 3: Live 모델이 하나도 없는 키 ──

const NO_LIVE_TEXT = '이 키의 프로젝트에서는 실시간 음성(Live) 모델을 쓸 수 없습니다. 구글이 이 프로젝트에 Live 모델을 열어 주지 않았습니다 — 결제(유료 등급)를 켠 뒤 다시 확인하거나, 공급자를 OpenAI 로 바꿔 주세요.';
const NO_LIVE: VoiceModels = { models: [], default: 'gemini-3.8-live', fallback: false, refused: false, no_live: true, reason: NO_LIVE_TEXT };

test('a key whose project has no Live model makes the card 실패 with the reason and locks real calls', async () => {
  open({ [`${VOICE}/models`]: NO_LIVE, [VOICE]: voice({ status: 'ok' }) });
  const b = await findBlock();
  await waitFor(() => expect(within(b).getByText('실패', { selector: '.ui-badge' })).toBeVisible());
  expect(within(b).getByRole('alert')).toHaveTextContent(NO_LIVE_TEXT);
  expect(within(b).getByRole('switch', { name: /실제 통화 포함/ })).toBeDisabled();
  expect(within(b).getByRole('button', { name: '시험 전화' })).toBeDisabled();
  expect(within(b).getByText(/실시간 음성 모델이 없어 전화를 걸 수 없습니다/)).toBeVisible();
  const select = within(await editForm(b)).getByRole('combobox', { name: '모델' });
  expect(within(select).getAllByRole('option').map((o) => o.textContent)).toEqual(['gemini-3.8-live', '직접 입력']);
  expect(within(b).getByText('이 키로 쓸 수 있는 실시간 음성 모델이 없습니다')).toBeVisible();
});

// ── 요청 시간 제한 = 서버 덩어리 상한(voice.py `_ceiling`) + 덩어리마다 닫기 28초 + 여유 30초 ──

test('the client time limit covers the server ceilings of every chunk plus the shielded close and a margin', () => {
  expect(limitMs('connection', {}, 90)).toBe((189 + 28 + 30) * 1000); // P9 가 음성을 하나씩 연다(Task 99)
  expect(limitMs('call', { call: true }, 90)).toBe((146 + 28 + 30) * 1000);
  expect(limitMs('call', { steps: ['P6', 'P7', 'P8', 'P10'], call: true }, 90)).toBe((2 * (146 + 28) + 30) * 1000); // 두 덩어리
  expect(limitMs('inbound', { steps: ['P12', 'P13'], inbound: true }, 90)).toBe((121 + 90 + 28 + 30) * 1000);
  expect(limitMs('inbound', { steps: ['P14'], inbound: true }, 90)).toBe((89 + 90 + 28 + 30) * 1000);
  expect(limitMs('inbound', { steps: ['P12', 'P13'], inbound: true }, 10)).toBe((121 + 10 + 28 + 30) * 1000);
  expect(limitMs('inbound', { inbound: true }, 90)).toBe((121 + 90 + 28 + 89 + 90 + 28 + 30) * 1000); // 셋을 한 번에
});
