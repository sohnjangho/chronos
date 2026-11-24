// 사진 사람 판독(PM 11-24, 시안 B): 관리자는 묶은 목록 + 크게 보기에서 진도·근거를 넣어 승인함에 올리고, 다시 찍기를 요청한다.
// 올린 사람(현장 관리자)은 카드에서 「AI 가 판독하지 못해 관리자가 확인 중입니다」·다시 찍기 요청을 본다. 0% 를 보이지 않는다.
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test, vi } from 'vitest';
import { useSession } from '../../os/session';
import { signInAsDemo, stubFetch } from '../../test-helpers';
import FieldHub from './FieldHub';
import type { FieldData, FieldItem } from './fieldApi';
import progressCss from './progress.css?raw';

vi.mock('../../shared/outreach/BatchSendDialog', () => ({ default: () => null }));

const SUMMARY = { checkin_total: 0, checkin_responded: 0, photo_total: 3, poll_total: 0, poll_feasible: 0, poll_conditional: 0, poll_infeasible: 0, handoff_total: 0, handoff_ready: 0 };
const WHY = '사진이 어두워 작업 상태가 보이지 않습니다.';

function photo(over: Partial<FieldItem>): FieldItem {
  return {
    id: 1, schedule_id: 1, kind: 'photo', activity_id: 'A310', activity_name: '철골 보 설치', trade: '철골팀', status: 'human_wait',
    title: '[AI 사진 판독] A310 철골 보 설치', prompt_text: '', response_choice: 'unread', reported_progress: null, reported_rd: null,
    response_note: '', approval_id: null, created_at: '2026-11-24T00:00:00Z', updated_at: '2026-11-24T00:00:00Z',
    payload_json: { photo_name: 'night.jpg', ai_progress: null, unread_reason: WHY, captured_at: '2026-11-24 19:55', uploaded_by: { id: 9, name: '박현장' } },
    ...over,
  };
}

const WAIT = photo({});
const ASKED = photo({ id: 2, activity_id: 'A320', activity_name: '철골 접합부 볼트 체결', title: '[AI 사진 판독] A320 철골 접합부 볼트 체결', status: 'retake',
  payload_json: { ...WAIT.payload_json, retake: { by: '김하늘', reason: '한 층 접합부가 함께 보이게 다시 찍어 주세요' } } });
const DONE = photo({ id: 3, activity_id: 'A230', activity_name: '4층 기둥 철근', title: '[AI 사진 판독] A230 4층 기둥 철근', status: 'applied', response_choice: 'human',
  reported_progress: 45, approval_id: 212, payload_json: { ...WAIT.payload_json, human_read: { by: '김하늘', progress: 45, reason: '띠철근 절반' } } });

const data = (items: FieldItem[], can: boolean, waits = 1, retake = 1): FieldData => ({
  schedule_id: 1, schedule_name: '5층 사무동 신축', activities: [{ id: 'A310', name: '철골 보 설치', progress: 50, rd: 10 }],
  summary: { ...SUMMARY, photo_human_wait: waits, photo_retake: retake }, items, can_human_read: can,
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  useSession.getState().logout();
});

async function openHuman(items = [WAIT, ASKED, DONE], extra = {}) {
  signInAsDemo('admin');
  const spy = stubFetch({ '/api/schedules/1/field': data(items, true), ...extra });
  render(<FieldHub scheduleId={1} />);
  await userEvent.click(await screen.findByRole('tab', { name: /사진 AI 판독/ }));
  expect(screen.getByRole('tab', { name: /사진 AI 판독/ })).toHaveTextContent('사람 판독 대기 1');
  await userEvent.click(screen.getByRole('button', { name: /^사람 판독 대기 1/ }));
  return spy;
}

test('the admin sees waiting photos grouped and searchable, with the recorded progress only for comparison', async () => {
  await openHuman();
  const list = screen.getByRole('region', { name: '사진 사람 판독' });
  expect(within(list).getByRole('region', { name: '사람 판독 대기 1' })).toBeVisible();
  expect(within(list).getByRole('region', { name: '다시 찍기 요청 — 새 사진을 기다림 1' })).toBeVisible();
  expect(within(list).getByRole('region', { name: '사람 판독함 1' })).toBeVisible();
  const side = screen.getByRole('complementary', { name: '사람 판독 자세히' });
  expect(within(side).getByText(`판독하지 않음 — ${WHY}`)).toBeVisible();
  expect(within(side).getByText('50%')).toBeVisible(); // 기록된 진도(비교용)
  expect(within(side).queryByText('0%')).toBeNull();

  await userEvent.type(within(list).getByRole('searchbox', { name: '사람 판독 찾기' }), '볼트');
  expect(within(list).queryByRole('region', { name: '사람 판독 대기 1' })).toBeNull();
  expect(within(list).getByRole('region', { name: '다시 찍기 요청 — 새 사진을 기다림 1' })).toBeVisible();
});

test('a human reading is sent with its progress and one-line grounds (it then goes to the approvals inbox)', async () => {
  const spy = await openHuman(undefined, { 'POST /api/schedules/1/field/1/human-read': data([{ ...WAIT, status: 'applied', response_choice: 'human', approval_id: 300 }], true, 0, 0) });
  const side = screen.getByRole('complementary', { name: '사람 판독 자세히' });
  const send = within(side).getByRole('button', { name: '사람 판독으로 승인함에 올리기' });
  expect(send).toBeDisabled();
  await userEvent.type(within(side).getByLabelText('진도율 (%)'), '35');
  expect(send).toBeDisabled(); // 근거가 없으면 못 올린다
  await userEvent.type(within(side).getByLabelText('근거 한 줄'), '보 인양 장면뿐 — 반입 대장 대조로 35%');
  await userEvent.click(send);
  const call = spy.mock.calls.find(([u]) => String(u) === '/api/schedules/1/field/1/human-read');
  expect(JSON.parse(String(call?.[1]?.body))).toEqual({ progress: 35, reason: '보 인양 장면뿐 — 반입 대장 대조로 35%' });
  expect(await screen.findByText('사람 판독을 승인함에 올렸습니다 — 승인되기 전에는 일정이 바뀌지 않습니다.')).toBeVisible();
});

test('a retake request is recorded with its reason', async () => {
  const spy = await openHuman(undefined, { 'POST /api/schedules/1/field/1/retake': data([{ ...WAIT, status: 'retake' }], true, 0, 1) });
  const side = screen.getByRole('complementary', { name: '사람 판독 자세히' });
  await userEvent.click(within(side).getByRole('button', { name: '다시 찍어 달라고 요청' }));
  await userEvent.type(within(side).getByLabelText('다시 찍을 까닭 (올린 사람에게 보입니다)'), '낮에 다시 찍어 주세요');
  await userEvent.click(within(side).getByRole('button', { name: '요청 남기기' }));
  const call = spy.mock.calls.find(([u]) => String(u) === '/api/schedules/1/field/1/retake');
  expect(JSON.parse(String(call?.[1]?.body))).toEqual({ reason: '낮에 다시 찍어 주세요' });
});

test('the uploader (field manager) sees the admin is checking and the retake request, with no entry form or number', async () => {
  signInAsDemo('field', '박현장');
  stubFetch({ '/api/schedules/1/field': data([WAIT, ASKED], false) });
  render(<FieldHub scheduleId={1} />);
  await userEvent.click(await screen.findByRole('tab', { name: '사진 AI 판독' }));
  const waiting = screen.getByRole('article', { name: WAIT.title });
  expect(within(waiting).getByText('AI 가 판독하지 못해 관리자가 확인 중입니다.')).toBeVisible();
  expect(within(waiting).getByText('관리자 확인 중')).toBeVisible();
  expect(within(waiting).queryByText(/\d+%/)).toBeNull();
  const asked = screen.getByRole('article', { name: ASKED.title });
  expect(within(asked).getByText('관리자가 다시 찍어 달라고 했습니다 — 한 층 접합부가 함께 보이게 다시 찍어 주세요')).toBeVisible();
  expect(screen.queryByRole('button', { name: '사람 판독으로 승인함에 올리기' })).toBeNull();
  expect(screen.queryByRole('region', { name: '사진 사람 판독' })).toBeNull();
});

// 리뷰 11-24

const BACK = photo({ id: 4, title: '[AI 사진 판독] A330 기둥 세우기', activity_id: 'A330', activity_name: '기둥 세우기',
  payload_json: { ...WAIT.payload_json, human_history: [{ by: '김하늘', progress: 40, reason: '절반', outcome: 'rejected', approval_id: 5 }] } });
const SAME = photo({ id: 5, title: '[AI 사진 판독] A340 보 세우기', activity_id: 'A340', activity_name: '보 세우기', status: 'applied',
  response_choice: 'human', reported_progress: 40, approval_id: null,
  payload_json: { ...WAIT.payload_json, human_read: { by: '김하늘', progress: 40, reason: '그대로', no_change: true } } });

test('a human reading rejected in the inbox shows 반려됨 — 다시 판독 대기 to the uploader and in the list', async () => {
  signInAsDemo('field', '박현장');
  stubFetch({ '/api/schedules/1/field': data([BACK], false) });
  render(<FieldHub scheduleId={1} />);
  await userEvent.click(await screen.findByRole('tab', { name: '사진 AI 판독' }));
  const card = screen.getByRole('article', { name: BACK.title });
  expect(within(card).getByText('반려됨 — 다시 판독 대기')).toBeVisible();
  expect(within(card).queryByText(/\d+%/)).toBeNull(); // 거부된 값은 보이지 않는다
  cleanup();
  useSession.getState().logout();
  await openHuman([WAIT, BACK]);
  const list = screen.getByRole('region', { name: '사진 사람 판독' });
  expect(within(list).getByText(/^반려됨 — 다시 판독 대기 · /)).toBeVisible();
});

test('a human reading equal to the record says so and cannot be sent again', async () => {
  signInAsDemo('field', '박현장');
  stubFetch({ '/api/schedules/1/field': data([SAME], false, 0, 0) });
  render(<FieldHub scheduleId={1} />);
  await userEvent.click(await screen.findByRole('tab', { name: '사진 AI 판독' }));
  const card = screen.getByRole('article', { name: SAME.title });
  expect(within(card).getByRole('button', { name: '기록과 같아 일정 변경 없음' })).toBeDisabled();
});

test('an old row without the uploader name shows — instead of the trade', async () => {
  const old = photo({ payload_json: { ...WAIT.payload_json, uploaded_by: undefined } });
  await openHuman([old]);
  const side = screen.getByRole('complementary', { name: '사람 판독 자세히' });
  expect(within(side).getByText('— · 2026-11-24 19:55')).toBeVisible();
  expect(within(side).queryByText(/철골팀/)).toBeNull();
});

test('unreadable photos are not counted as evidence in the KPI', async () => {
  await openHuman();
  expect(screen.getByText('증빙 3건 · 사람 판독 대기 1')).toBeVisible();
});

test('the photo view switch wraps instead of overflowing on a narrow screen', () => {
  expect(progressCss).toMatch(/\.pg-field-subbar \.pg-hr-switch button \{[^}]*white-space: normal/);
  expect(progressCss).toMatch(/\.pg-field-subbar \.pg-seg button:has\(\.pg-hr-pill\) \{[^}]*white-space: normal/);
});
