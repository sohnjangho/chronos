// 상한 칸(설정 「알림 연결」과 개발 콘솔이 함께 씀). 값은 모두 가상.
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test, vi } from 'vitest';
import { json, stubFetch } from '../../test-helpers';
import LimitsForm from './LimitsForm';
import type { LimitsOut } from './limitsApi';

const DEFAULTS: Record<string, number> = {
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
const COUNT: [number, number] = [0, 1000];
const RANGES: Record<string, [number, number]> = {
  daily_sms_total: COUNT,
  daily_calls_total: COUNT,
  per_contact_sms_daily: COUNT,
  per_contact_calls_daily: COUNT,
  max_call_seconds: [30, 7200],
  max_call_seconds_unknown: [1, 7200],
  auto_reply_hourly: COUNT,
  auto_reply_daily: COUNT,
  inbound_burst_count: [1, 10000],
  inbound_burst_minutes: [1, 1440],
  reply_grace_minutes: [0, 1440],
  unknown_notice_daily: COUNT,
};
const LIMITS = '/api/notify/connections/3/limits';

const out = (values: Record<string, number> = {}): LimitsOut => ({
  values: { ...DEFAULTS, ...values },
  defaults: { ...DEFAULTS },
  ranges: { ...RANGES },
});

function sentBodies(fetchMock: ReturnType<typeof stubFetch>, key: string) {
  return fetchMock.mock.calls
    .filter(([url, init]) => `${init?.method ?? 'GET'} ${String(url)}` === key)
    .map(([, init]) => (typeof init?.body === 'string' ? JSON.parse(init.body) : undefined));
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test('draws every field the server gives, with its default and range', async () => {
  stubFetch({ [LIMITS]: out({ daily_sms_total: 40 }) });
  render(<LimitsForm connectionId={3} />);
  const sms = await screen.findByRole('spinbutton', { name: /^하루 문자/ });
  expect(sms).toHaveValue(40);
  expect(screen.getAllByRole('spinbutton')).toHaveLength(12);
  const field = sms.closest('[data-limit]') as HTMLElement;
  expect(within(field).getByText('기본 50 · 받는 값 0~1000')).toBeVisible();
  expect(within(field).getByText('바꿈')).toBeVisible();
  expect(screen.getByRole('spinbutton', { name: /^최대 통화 시간/ })).toHaveValue(300);
  for (const group of ['문자', '전화', '자동 답', '들어오는 전화']) expect(screen.getByRole('group', { name: group })).toBeVisible();
});

test('a field the screen does not know is still drawn', async () => {
  const body = out();
  body.values.new_cap = 7;
  body.defaults.new_cap = 7;
  body.ranges.new_cap = [0, 9];
  stubFetch({ [LIMITS]: body });
  render(<LimitsForm connectionId={3} />);
  expect(await screen.findByRole('spinbutton', { name: /new_cap/ })).toHaveValue(7);
});

test('saving one field sends only that field', async () => {
  const onSaved = vi.fn();
  const fetchMock = stubFetch({ [LIMITS]: out(), [`PUT ${LIMITS}`]: out({ per_contact_sms_daily: 3 }) });
  render(<LimitsForm connectionId={3} onSaved={onSaved} />);
  const input = await screen.findByRole('spinbutton', { name: /^한 사람 하루 문자/ });
  const field = input.closest('[data-limit]') as HTMLElement;
  const save = within(field).getByRole('button', { name: '저장' });
  expect(save).toBeDisabled();
  await userEvent.clear(input);
  await userEvent.type(input, '3');
  await userEvent.click(save);
  await waitFor(() => expect(sentBodies(fetchMock, `PUT ${LIMITS}`)).toEqual([{ per_contact_sms_daily: 3 }]));
  expect(await within(field).findByText('저장했습니다.')).toBeVisible();
  expect(input).toHaveValue(3);
  expect(onSaved).toHaveBeenCalledWith(expect.objectContaining({ per_contact_sms_daily: 3 }));
});

test('a 422 shows the server reason under the field it names', async () => {
  const reason = '모르는 번호 통화 시간은 최대 통화 시간보다 길 수 없습니다.';
  stubFetch({
    [LIMITS]: out(),
    [`PUT ${LIMITS}`]: () =>
      json(422, { code: 'invalid_limits', message: '한도 값이 올바르지 않습니다.', detail: { max_call_seconds_unknown: reason } }),
  });
  render(<LimitsForm connectionId={3} />);
  const input = await screen.findByRole('spinbutton', { name: /^최대 통화 시간/ });
  await userEvent.clear(input);
  await userEvent.type(input, '60{Enter}');
  const other = screen.getByRole('spinbutton', { name: /^모르는 번호 통화 시간/ }).closest('[data-limit]') as HTMLElement;
  expect(await within(other).findByText(reason)).toBeVisible();
  expect(input).toHaveValue(60);
});

test('a 422 for the edited field itself sits under that field', async () => {
  stubFetch({
    [LIMITS]: out(),
    [`PUT ${LIMITS}`]: () =>
      json(422, { code: 'invalid_limits', message: '한도 값이 올바르지 않습니다.', detail: { daily_sms_total: '0~1000 사이로 넣어 주세요.' } }),
  });
  render(<LimitsForm connectionId={3} />);
  const input = await screen.findByRole('spinbutton', { name: /^하루 문자/ });
  await userEvent.clear(input);
  await userEvent.type(input, '5000{Enter}');
  const field = input.closest('[data-limit]') as HTMLElement;
  expect(await within(field).findByRole('alert')).toHaveTextContent('0~1000 사이로 넣어 주세요.');
});

test('기본값으로 resets every field through the reset path', async () => {
  const fetchMock = stubFetch({ [LIMITS]: out({ daily_sms_total: 40 }), [`POST ${LIMITS}/reset`]: out() });
  render(<LimitsForm connectionId={3} />);
  const sms = await screen.findByRole('spinbutton', { name: /^하루 문자/ });
  await userEvent.click(screen.getByRole('button', { name: '기본값으로' }));
  await waitFor(() => expect(sms).toHaveValue(50));
  expect(sentBodies(fetchMock, `POST ${LIMITS}/reset`)).toHaveLength(1);
  expect(sentBodies(fetchMock, `PUT ${LIMITS}`)).toHaveLength(0);
});

test('a failed read shows the server message', async () => {
  stubFetch({ [LIMITS]: () => json(404, { code: 'connection_not_found', message: '알림 연결을 찾을 수 없습니다.', detail: null }) });
  render(<LimitsForm connectionId={3} />);
  expect(await screen.findByText('알림 연결을 찾을 수 없습니다.')).toBeVisible();
});

test('the two new fields have their own labels and sit in their groups (fourteen in all)', async () => {
  const body = out();
  Object.assign(body.values, { unknown_calls_hourly: 3, unknown_notice_total_daily: 20 });
  Object.assign(body.defaults, { unknown_calls_hourly: 3, unknown_notice_total_daily: 20 });
  Object.assign(body.ranges, { unknown_calls_hourly: [0, 1000], unknown_notice_total_daily: [0, 1000] });
  stubFetch({ [LIMITS]: body });
  render(<LimitsForm connectionId={3} />);
  const calls = await screen.findByRole('spinbutton', { name: '모르는 번호 전화 한 시간 (통)' });
  expect(screen.getAllByRole('spinbutton')).toHaveLength(14);
  expect(within(screen.getByRole('group', { name: '전화' })).getByRole('spinbutton', { name: '모르는 번호 전화 한 시간 (통)' })).toBe(calls);
  const notices = within(screen.getByRole('group', { name: '자동 답' }))
    .getAllByRole('spinbutton')
    .map((i) => i.closest('[data-limit]')?.getAttribute('data-limit'));
  expect(notices.slice(-2)).toEqual(['unknown_notice_daily', 'unknown_notice_total_daily']);
  expect(screen.getByRole('spinbutton', { name: '모르는 번호 안내 하루 전체 (건)' })).toHaveValue(20);
  expect(screen.queryByRole('group', { name: '그 밖' })).toBeNull();
});

test('disabled locks every field and the reset button', async () => {
  stubFetch({ [LIMITS]: out({ daily_sms_total: 40 }) });
  render(<LimitsForm connectionId={3} disabled />);
  await screen.findByRole('spinbutton', { name: /^하루 문자/ });
  for (const input of screen.getAllByRole('spinbutton')) expect(input).toBeDisabled();
  expect(screen.getByRole('button', { name: '기본값으로' })).toBeDisabled();
});
