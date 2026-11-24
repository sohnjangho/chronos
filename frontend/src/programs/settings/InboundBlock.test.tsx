// 설정 → 알림 연결 → 「받는 범위 · 차단」(Task 85). 받는 범위를 바꿀 때는 확인 창(전화와 문자에 같이 적용), 사람 연결 번호는
// 한 칸(가린 지금 번호만 보임 — 전체 번호는 화면에 내려오지 않는다). 길은 기존 PATCH /api/notify/connections/{id}. 번호는 모두 가상.
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { json, stubFetch } from '../../test-helpers';
import InboundBlock from './InboundBlock';
import type { NotifyConnection } from './notifyApi';

const ONE = 'PATCH /api/notify/connections/3';

function conn(over: Partial<NotifyConnection> = {}): NotifyConnection {
  return {
    id: 3, name: '현장 알림', provider: 'koreaaitel', base_url: 'https://api.koreaaitel.com', secret_last4: '9999', account_id_masked: '…0001',
    sender_number_masked: '070-****-0123', sender_index: 0, senders: [], kakao_channel: null, test_mode: true, allow_numbers: [],
    allow_numbers_version: 'v1', test_sms_index: null, limits: {}, agent_sms: 'approve', agent_kakao: 'approve', agent_call: 'approve',
    inbound_mode: 'off', handoff_number_masked: null, is_default: true, status: 'ok', checked_at: null, latency_ms: null, used_today: null,
    ...over,
  };
}

let fetchMock: ReturnType<typeof stubFetch>;
let patchReply: () => Response;
beforeEach(() => {
  patchReply = () => json(200, conn());
  fetchMock = stubFetch({ '/api/notify/blocked': [], [ONE]: () => patchReply() });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const patches = () => fetchMock.mock.calls.filter((c) => c[1]?.method === 'PATCH').map((c) => JSON.parse(String(c[1]?.body)));
const block = () => screen.getByRole('region', { name: '받는 범위 · 차단' });

test('changing the inbound range asks first — it applies to calls and texts — and then patches', async () => {
  const onChanged = vi.fn();
  render(<InboundBlock conn={conn()} onChanged={onChanged} />);
  const range = within(block()).getByRole('radiogroup', { name: '받는 범위' });
  expect(within(range).getByRole('radio', { name: '받지 않음' })).toBeChecked();

  await userEvent.click(within(range).getByRole('radio', { name: '주소록에 있는 번호만' }));
  const ask = within(block()).getByRole('group', { name: '받는 범위 바꾸기 확인' });
  expect(ask.textContent).toContain('걸려 오는 전화와 들어오는 문자에 같이 적용됩니다');
  expect(patches()).toEqual([]);
  await userEvent.click(within(ask).getByRole('button', { name: '취소' }));
  expect(within(range).getByRole('radio', { name: '받지 않음' })).toBeChecked();
  expect(patches()).toEqual([]);

  await userEvent.click(within(range).getByRole('radio', { name: '모두 받기' }));
  const again = within(block()).getByRole('group', { name: '받는 범위 바꾸기 확인' });
  expect(again.textContent).toContain('모르는 번호에서 온 실제 전화·문자에도 AI 가 응대합니다(메모만 남기고');
  await userEvent.click(within(again).getByRole('button', { name: '바꾸기' }));
  await waitFor(() => expect(patches()).toEqual([{ inbound_mode: 'all' }]));
  expect(onChanged).toHaveBeenCalled();
});

test('the hand-off number is one field: save sends the typed number once and clears it, clear sends null', async () => {
  render(<InboundBlock conn={conn({ handoff_number_masked: '010-****-0000' })} onChanged={() => undefined} />);
  expect(within(block()).getByText('지금: 010-****-0000')).toBeVisible();
  const input = within(block()).getByRole('textbox', { name: '사람 연결 번호' });
  await userEvent.type(input, '010-0000-0001');
  await userEvent.click(within(block()).getByRole('button', { name: '저장' }));
  await waitFor(() => expect(patches()).toEqual([{ handoff_number: '010-0000-0001' }]));
  await waitFor(() => expect(input).toHaveValue(''));

  await userEvent.click(within(block()).getByRole('button', { name: '비우기' }));
  await waitFor(() => expect(patches().at(-1)).toEqual({ handoff_number: null }));
});

test('a refused hand-off number shows the server reason under the field without echoing it', async () => {
  patchReply = () => json(422, { code: 'invalid_number', message: '번호 형식이 올바르지 않거나 쓸 수 없는 번호입니다.', detail: { field: 'handoff_number' } });
  render(<InboundBlock conn={conn()} onChanged={() => undefined} />);
  await userEvent.type(within(block()).getByRole('textbox', { name: '사람 연결 번호' }), '060-0000-0000');
  await userEvent.click(within(block()).getByRole('button', { name: '저장' }));
  expect(await within(block()).findByText('번호 형식이 올바르지 않거나 쓸 수 없는 번호입니다.')).toBeVisible();
});

test('everything is locked while the card is busy', () => {
  render(<InboundBlock conn={conn()} locked onChanged={() => undefined} />);
  for (const radio of within(block()).getAllByRole('radio')) expect(radio).toBeDisabled();
  expect(within(block()).getByRole('textbox', { name: '사람 연결 번호' })).toBeDisabled();
});
