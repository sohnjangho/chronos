// 「AI 전화」 카드의 음성 고르기(Task 99). 음성 SDK 가 음성 목록·샘플을 주지 않아(진단 P9 not_supported) 목록·▶ 없이
// 음성 이름(id)을 손으로 넣는 칸만 있다. 응답은 Task 90 계약대로의 가짜 — 실제 제공사를 부르지 않는다.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test } from 'vitest';
import { json } from '../../test-helpers';
import type { NotifyConnection } from './notifyApi';
import type { VoiceSettings } from './voiceApi';
import { renderAs, resetAll, sent } from './testKit';

const LIST = '/api/notify/connections';
const ONE = `${LIST}/3`;
const VOICE = `${ONE}/voice`;
const LIMITS = { max_call_seconds: 300, daily_sms_total: 50, daily_calls_total: 10 };
const HINT = '상대와 반대 성별의 음성을 고르세요';
const BAD = '음성 이름은 영문으로 시작하고 영문·숫자·점(.)·줄표(-)·밑줄(_)만 쓸 수 있습니다.';
const RISK = '공급자에 없는 이름이면 이 칸을 쓰는 전화는 상대가 받은 뒤 끊깁니다. 저장한 뒤 [음성 진단]으로 확인하세요.';

function conn(): NotifyConnection {
  return {
    id: 3, name: '현장 알림', provider: 'koreaaitel', base_url: 'https://api.koreaaitel.com', secret_last4: '9999',
    account_id_masked: '…0001', sender_number_masked: '070-****-0123', sender_index: 0,
    senders: [{ index: 0, number_masked: '070-****-0123', kind: 'internet', label: '발신번호 1' }], kakao_channel: null,
    test_mode: true, allow_numbers: [{ index: 0, number_masked: '010-****-0199', kind: 'mobile', can_test_sms: true }],
    allow_numbers_version: 'v1', test_sms_index: 0, limits: LIMITS, agent_sms: 'approve', agent_kakao: 'approve',
    agent_call: 'approve', inbound_mode: 'off', handoff_number_masked: null, is_default: true, status: 'ok', checked_at: null,
    latency_ms: 312, used_today: { sms: 0, call: 0 },
  };
}

function voice(over: Partial<VoiceSettings> = {}): VoiceSettings {
  return {
    connection_id: 3, provider: 'google', has_secret: true, secret_last4: '1234', model: '',
    agent_number_masked: '070-****-0456', agent_number_kind: 'internet', voice_male_contact: null, voice_female_contact: null,
    voice_unknown: null, voices_by_language: {}, status: 'unknown', checked_at: null, sdk_installed: true, test_call_index: 0,
    key_notice: null,
    call_limits: { calls_per_request: 2, ring_seconds: 20, call_seconds: 60, inbound_wait_default: 90, inbound_wait_min: 10, inbound_wait_max: 180 },
    saved: true, model_effective: 'gemini-3.8-live', agent_number_effective_masked: '070-****-0456', agent_number_source: 'voice',
    ...over,
  };
}

function open(v: VoiceSettings = voice(), over: Record<string, unknown> = {}) {
  return renderAs('admin', { section: 'notify' }, {
    [LIST]: [conn()],
    [`${ONE}/diagnosis`]: () => json(200, null),
    [`${ONE}/limits`]: { values: LIMITS, defaults: LIMITS, ranges: {} },
    [VOICE]: v,
    [`${VOICE}/diagnosis`]: () => json(200, null),
    [`${VOICE}/models`]: { models: ['gemini-3.8-live'], default: 'gemini-3.8-live', fallback: false, refused: false, no_live: false, reason: null },
    ...over,
  });
}

/** 카드가 그려지면 [음성 고르기]로 연다. */
async function picker() {
  const b = await screen.findByRole('region', { name: 'AI 전화' });
  await userEvent.click(await within(b).findByRole('button', { name: '음성 고르기' }));
  return within(b).getByRole('group', { name: '음성 고르기' });
}

const voiceFact = () => within(screen.getByRole('region', { name: 'AI 전화' })).getByText('음성', { selector: 'dt' }).nextElementSibling?.textContent;

afterEach(resetAll);

test('three manual fields — no voice list, no sample button — with the opposite-gender hint and the SDK default', async () => {
  open();
  const p = await picker();
  for (const name of ['남성 연락처에게 걸 때', '여성 연락처에게 걸 때', '성별 모름']) {
    const field = within(p).getByLabelText(name);
    expect(field.tagName).toBe('INPUT');
    expect(field).toHaveAttribute('placeholder', '비우면 기본 음성(Gemini: Kore)');
  }
  expect(within(p).getByText(HINT)).toBeVisible();
  expect(within(p).getByText(RISK)).toBeVisible(); // 없는 이름의 위험(고침 1)
  expect(within(p).getByText(/음성 SDK 가 음성 목록과 샘플을 주지 않아/)).toBeVisible();
  expect(within(p).queryByRole('listbox')).toBeNull();
  expect(within(p).queryByRole('button', { name: /샘플|▶/ })).toBeNull();
  expect(within(p).getByRole('button', { name: '음성 저장' })).toBeDisabled(); // 바꾼 것이 없다
});

test('saving sends only the changed fields with PUT and the card shows the chosen voices', async () => {
  const saved = voice({ voice_male_contact: 'Aoede', voice_female_contact: 'Charon' });
  const { fetchMock } = open(voice(), { [`PUT ${VOICE}`]: saved });
  expect(await screen.findByText(/남성 연락처 기본 음성 · 여성 연락처 기본 음성 · 성별 모름 기본 음성/)).toBeVisible();
  const p = await picker();
  await userEvent.type(within(p).getByLabelText('남성 연락처에게 걸 때'), 'Aoede');
  await userEvent.type(within(p).getByLabelText('여성 연락처에게 걸 때'), ' Charon ');
  await userEvent.click(within(p).getByRole('button', { name: '음성 저장' }));
  await waitFor(() => expect(sent(fetchMock, `PUT ${VOICE}`)).toEqual([{ voice_male_contact: 'Aoede', voice_female_contact: 'Charon' }]));
  expect(await screen.findByText('저장했습니다.')).toBeVisible();
  expect(screen.queryByRole('group', { name: '음성 고르기' })).toBeNull();
  expect(voiceFact()).toBe('남성 연락처 Aoede · 여성 연락처 Charon · 성별 모름 기본 음성');
});

test('emptying a saved field sends null; a wrong shape is caught before sending', async () => {
  const { fetchMock } = open(voice({ voice_unknown: 'Puck' }), { [`PUT ${VOICE}`]: voice() });
  const p = await picker();
  const unknown = within(p).getByLabelText('성별 모름');
  expect(unknown).toHaveValue('Puck');
  await userEvent.type(within(p).getByLabelText('남성 연락처에게 걸 때'), '010-0000-0000');
  expect(within(p).getByText(BAD)).toBeVisible();
  expect(within(p).getByRole('button', { name: '음성 저장' })).toBeDisabled();
  await userEvent.clear(within(p).getByLabelText('남성 연락처에게 걸 때'));
  await userEvent.type(within(p).getByLabelText('남성 연락처에게 걸 때'), '목소리');
  expect(within(p).getByRole('button', { name: '음성 저장' })).toBeDisabled();
  await userEvent.clear(within(p).getByLabelText('남성 연락처에게 걸 때'));
  await userEvent.clear(unknown);
  await userEvent.click(within(p).getByRole('button', { name: '음성 저장' }));
  await waitFor(() => expect(sent(fetchMock, `PUT ${VOICE}`)).toEqual([{ voice_unknown: null }]));
});

test('the server refusal lands under its field without echoing the value', async () => {
  open(voice(), { [`PUT ${VOICE}`]: () => json(422, { code: 'invalid_voice', message: BAD, detail: { field: 'voice_unknown' } }) });
  const p = await picker();
  await userEvent.type(within(p).getByLabelText('성별 모름'), 'Kore.x');
  await userEvent.click(within(p).getByRole('button', { name: '음성 저장' }));
  const field = within(p).getByLabelText('성별 모름').closest('.ui-field') as HTMLElement;
  expect(await within(field).findByText(BAD)).toBeVisible();
});

test('per-language voices are optional: add a language, fill one field, remove another language', async () => {
  const start = voice({ voices_by_language: { vi: { voice_unknown: 'Kore' } } });
  const { fetchMock } = open(start, { [`PUT ${VOICE}`]: voice({ voices_by_language: { en: { voice_male_contact: 'Leda' } } }) });
  const p = await picker();
  const vi = within(p).getByRole('group', { name: '베트남어 음성' });
  expect(within(vi).getByLabelText('성별 모름')).toHaveValue('Kore');
  expect(within(vi).getByLabelText('남성 연락처에게 걸 때')).toHaveAttribute('placeholder', '비우면 위의 칸');
  await userEvent.selectOptions(within(p).getByRole('combobox', { name: '언어별 음성 더하기' }), 'en');
  const en = within(p).getByRole('group', { name: '영어 음성' });
  await userEvent.type(within(en).getByLabelText('남성 연락처에게 걸 때'), 'Leda');
  await userEvent.click(within(vi).getByRole('button', { name: '베트남어 빼기' }));
  expect(within(p).queryByRole('group', { name: '베트남어 음성' })).toBeNull();
  await userEvent.click(within(p).getByRole('button', { name: '음성 저장' }));
  await waitFor(() => expect(sent(fetchMock, `PUT ${VOICE}`)).toEqual([{ voices_by_language: { en: { voice_male_contact: 'Leda' } } }]));
  expect(voiceFact()).toContain('언어별: 영어');
});

test('openai shows its own SDK default and cancel closes without sending', async () => {
  const { fetchMock } = open(voice({ provider: 'openai', model: 'gpt-realtime-test', model_effective: 'gpt-realtime-test' }));
  const p = await picker();
  expect(within(p).getByLabelText('성별 모름')).toHaveAttribute('placeholder', '비우면 기본 음성(OpenAI: marin)');
  await userEvent.type(within(p).getByLabelText('성별 모름'), 'cedar');
  await userEvent.click(within(p).getByRole('button', { name: '취소' }));
  expect(screen.queryByRole('group', { name: '음성 고르기' })).toBeNull();
  expect(sent(fetchMock, `PUT ${VOICE}`)).toEqual([]);
});
