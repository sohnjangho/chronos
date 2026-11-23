// 현장 허브(FieldHub) 카드 시험: 사진 판독 결과(F1), 회신 전 카드·저장 알림·의견 조회 작성 칸(F7).
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { resizeImage } from '../../shared/files/resizeImage';
import { useSession } from '../../os/session';
import { signInAsDemo, stubFetch } from '../../test-helpers';
import FieldHub from './FieldHub';
import type { FieldData, FieldItem } from './fieldApi';

// 리뷰 I-2: jsdom 에는 그림 그리기가 없어 줄이기는 가짜로 — 무엇을 줄여 달라 했는지와 줄인 결과를 보내는지를 본다.
vi.mock('../../shared/files/resizeImage', () => ({ resizeImage: vi.fn() }));

const SUMMARY = { checkin_total: 0, checkin_responded: 0, photo_total: 1, poll_total: 0, poll_feasible: 0, poll_conditional: 0, poll_infeasible: 0, handoff_total: 0, handoff_ready: 0 };

function item(over: Partial<FieldItem>): FieldItem {
  return {
    id: 1, schedule_id: 1, kind: 'photo', activity_id: 'A1210', activity_name: '지상 골조', trade: '골조팀', status: 'responded',
    title: '[AI 사진 판독] A1210 지상 골조', prompt_text: '', response_choice: 'verified', reported_progress: null, reported_rd: null,
    response_note: '', payload_json: {}, approval_id: null, created_at: '2026-11-23T00:00:00Z', updated_at: '2026-11-23T00:00:00Z',
    ...over,
  };
}

const data = (items: FieldItem[]): FieldData => ({
  schedule_id: 1, schedule_name: '5층 사무동 신축', activities: [{ id: 'A1210', name: '지상 골조', progress: 0, rd: 10 }], summary: SUMMARY, items,
});

beforeEach(() => signInAsDemo('admin'));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  useSession.getState().logout();
});

async function photoCard(it: FieldItem) {
  stubFetch({ '/api/schedules/1/field': data([it]) });
  render(<FieldHub scheduleId={1} />);
  await userEvent.click(await screen.findByRole('tab', { name: '사진 AI 판독' }));
  return screen.getByRole('article', { name: it.title });
}

test('a photo that was not read shows 판독하지 않음 with its reason, no number, and cannot be sent (F1)', async () => {
  const card = await photoCard(
    item({ response_choice: 'unread', payload_json: { photo_name: 'rebar.jpg', ai_progress: null, unread_reason: '사진이 없어 판독하지 않았습니다.' } }),
  );
  expect(within(card).getByText('판독하지 않음 — 사진이 없어 판독하지 않았습니다.')).toBeVisible();
  expect(within(card).queryByRole('progressbar')).toBeNull();
  expect(within(card).queryByText(/\d+%/)).toBeNull();
  expect(within(card).getByRole('button', { name: '승인함 상신 · 증빙 확정' })).toBeDisabled();
});

// 리뷰 I-3: 예전 방식(숫자를 지어낸) 사진 항목은 서버가 판독하지 않음으로 내보낸다 — 숫자 없이 다시 올리라고 말한다.
test('an old made-up photo reading shows as unread and asks for the photo again (I-3)', async () => {
  const card = await photoCard(
    item({ response_choice: 'unread', reported_progress: null, payload_json: { photo_name: 'old.jpg', ai_progress: null, ai_stage: '거푸집 조립 단계', unread_reason: '이전 방식으로 만든 항목입니다. 사진을 다시 올려 주세요' } }),
  );
  expect(within(card).getByText('판독하지 않음 — 이전 방식으로 만든 항목입니다. 사진을 다시 올려 주세요')).toBeVisible();
  expect(within(card).queryByText(/\d+%/)).toBeNull();
  expect(within(card).getByRole('button', { name: '승인함 상신 · 증빙 확정' })).toBeDisabled();
});

test('a photo read by the vision model shows its percentage and one-sentence reason (F1)', async () => {
  const card = await photoCard(
    item({ reported_progress: 40, payload_json: { photo_name: 'rebar.jpg', ai_progress: 40, ai_reason: '철근 배근은 끝났고 거푸집은 절반쯤 섰다.', ai_risks: [] } }),
  );
  expect(within(card).getByRole('progressbar')).toHaveAttribute('aria-valuenow', '40');
  expect(within(card).getByText('40%')).toBeVisible();
  expect(within(card).getByText('판독 근거: 철근 배근은 끝났고 거푸집은 절반쯤 섰다.')).toBeVisible();
  expect(within(card).getByRole('button', { name: '승인함 상신 · 증빙 확정' })).toBeEnabled();
});

const checkin = item({
  id: 5, kind: 'checkin', activity_id: 'A1020', activity_name: '현장 사무실 설치', trade: '시공팀 박과장', status: 'pending',
  title: '[체크인 요청] A1020 현장 사무실 설치', prompt_text: '착수/진행 여부를 회신해 주세요.', response_choice: null,
  reported_progress: 100, reported_rd: 3,
});

test('a check-in card waiting for a reply shows no pre-pressed choice or progress (F7)', async () => {
  stubFetch({ '/api/schedules/1/field': data([checkin]) });
  render(<FieldHub scheduleId={1} />);
  const card = await screen.findByRole('article', { name: checkin.title });
  expect(within(card).queryAllByRole('button', { pressed: true })).toHaveLength(0);
  expect(within(card).getByLabelText('진도율 (%)')).toHaveValue(null);
  const submit = within(card).getByRole('button', { name: '현장 보고 제출 (저장·승인 반영)' });
  expect(submit).toBeDisabled();
  expect(within(card).getByRole('button', { name: '임시 저장' })).toBeDisabled();
  await userEvent.click(within(card).getByRole('button', { name: '✓ 정상 진행' }));
  expect(submit).toBeEnabled();
});

test('임시 저장 says 저장했습니다 once the reply is saved (F7)', async () => {
  const saved = { ...checkin, status: 'responded' as const, response_choice: 'on_track' };
  const fetchFn = stubFetch({ '/api/schedules/1/field': data([checkin]), 'POST /api/schedules/1/field/5/respond': data([saved]) });
  render(<FieldHub scheduleId={1} />);
  const card = await screen.findByRole('article', { name: checkin.title });
  await userEvent.click(within(card).getByRole('button', { name: '✓ 정상 진행' }));
  await userEvent.click(within(card).getByRole('button', { name: '임시 저장' }));
  expect(await screen.findByText('저장했습니다.')).toBeVisible();
  const [, init] = fetchFn.mock.calls.find(([url, i]) => String(url).endsWith('/respond') && i?.method === 'POST')!;
  expect(JSON.parse(String(init?.body))).toEqual({ response_choice: 'on_track', response_note: '' });
});

test('점검 저장 on a hand-off card also says 저장했습니다 (F7)', async () => {
  const handoff = item({ id: 9, kind: 'handoff', title: '[D-3 핸드오프] A1000 → A1010', status: 'pending', response_choice: 'hold',
    payload_json: { pred_id: 'A1000', days_left: 3, pred_handover_ok: true, checklist: { material: true, equipment: false, workforce: true } } });
  stubFetch({ '/api/schedules/1/field': data([handoff]), 'POST /api/schedules/1/field/9/handoff': data([{ ...handoff, status: 'responded' }]) });
  render(<FieldHub scheduleId={1} />);
  await userEvent.click(await screen.findByRole('tab', { name: 'D-3 핸드오프 점검' }));
  await userEvent.click(screen.getByRole('button', { name: '점검 저장' }));
  expect(await screen.findByText('저장했습니다.')).toBeVisible();
});

test('the poll compose fields start empty with the example as a placeholder, so nothing goes out unfilled (F7)', async () => {
  stubFetch({ '/api/schedules/1/field': data([]) });
  render(<FieldHub scheduleId={1} />);
  await userEvent.click(await screen.findByRole('tab', { name: '만회안 의견 조회' }));
  await userEvent.click(screen.getByRole('button', { name: '+ 공종 담당자 의견 조회 발송' }));
  const title = screen.getByLabelText('검토 중인 만회안 제목');
  const ask = screen.getByLabelText('담당자에게 보낼 질문');
  expect(title).toHaveValue('');
  expect(title).toHaveAttribute('placeholder', '예: 공종 주말·병행 단축 2일안');
  expect(ask).toHaveValue('');
  expect(ask.getAttribute('placeholder')).toMatch(/^예: /);
  expect(screen.getByRole('button', { name: '공종 담당자에게 의견 조회 발송' })).toBeDisabled();
});

test('a poll card waiting for a reply has no pre-pressed choice either (F7)', async () => {
  const poll = item({ id: 7, kind: 'poll', status: 'pending', response_choice: null, title: '[만회안 의견] A1025 선행 공종 병행 착수(SS+2d)' });
  stubFetch({ '/api/schedules/1/field': data([poll]) });
  render(<FieldHub scheduleId={1} />);
  await userEvent.click(await screen.findByRole('tab', { name: '만회안 의견 조회' }));
  const card = screen.getByRole('article', { name: poll.title });
  expect(within(card).queryAllByRole('button', { pressed: true })).toHaveLength(0);
  const send = within(card).getByRole('button', { name: '의견 회신 완료' });
  expect(send).toBeDisabled();
  await userEvent.click(within(card).getByRole('button', { name: '조건부 가능' }));
  expect(send).toBeEnabled();
});


// 리뷰 I-2: 휴대폰 사진은 긴 변 1280px·JPEG 0.7 로 줄여 보내고, 줄여도 서버 한도를 넘으면 까닭을 말하고 보내지 않는다.
async function pickPhoto(original: File, shrunk: File) {
  vi.mocked(resizeImage).mockResolvedValue({ file: shrunk, resized: true });
  const fetchSpy = stubFetch({ '/api/schedules/1/field': data([]), 'POST /api/schedules/1/field/photos': data([]) });
  render(<FieldHub scheduleId={1} />);
  await userEvent.click(await screen.findByRole('tab', { name: '사진 AI 판독' }));
  await userEvent.upload(screen.getByLabelText('사진 촬영 / 파일 첨부'), original);
  return fetchSpy;
}
const photoPosts = (spy: ReturnType<typeof stubFetch>) =>
  spy.mock.calls.filter(([u, init]) => String(u) === '/api/schedules/1/field/photos' && init?.method === 'POST');

test('a picked photo is shrunk to a 1280px JPEG before it is sent (I-2)', async () => {
  const original = new File(['x'.repeat(4000)], 'rebar.jpg', { type: 'image/jpeg' });
  const spy = await pickPhoto(original, new File(['small'], 'rebar.jpg', { type: 'image/jpeg' }));
  expect(resizeImage).toHaveBeenCalledWith(original, 1280, { always: true, quality: 0.7 });
  await userEvent.click(screen.getByRole('button', { name: 'AI 사진 판독 실행' }));
  const sent = JSON.parse(String(photoPosts(spy)[0][1]?.body));
  expect(sent.photo_data_url).toBe(`data:image/jpeg;base64,${btoa('small')}`);
});

test('a photo still over the limit after shrinking says so and is not sent (I-2)', async () => {
  const huge = new File(['A'.repeat(1_200_000)], 'big.jpg', { type: 'image/jpeg' });
  const spy = await pickPhoto(huge, huge);
  expect(await screen.findByText('사진이 너무 큽니다 — 더 작은 사진으로 다시 올려 주세요')).toBeVisible();
  expect(screen.getByRole('button', { name: 'AI 사진 판독 실행' })).toBeDisabled();
  expect(photoPosts(spy)).toHaveLength(0);
});

// 리뷰: 현장 관리자가 올린 보고는 승인 수준과 상관없이 승인을 기다린다(서버) — 올린 뒤 그렇게 알린다.
const WAITS = '승인함에 올렸습니다 — 승인되기 전에는 일정이 바뀌지 않습니다.';

async function submitReport() {
  const sent = { ...checkin, status: 'responded' as const, response_choice: 'on_track' };
  stubFetch({
    '/api/schedules/1/field': data([checkin]),
    'POST /api/schedules/1/field/5/respond': data([sent]),
    'POST /api/schedules/1/field/5/apply': data([{ ...sent, status: 'applied', approval_id: 18 }]),
  });
  render(<FieldHub scheduleId={1} />);
  const card = await screen.findByRole('article', { name: checkin.title });
  await userEvent.click(within(card).getByRole('button', { name: '✓ 정상 진행' }));
  await userEvent.click(within(card).getByRole('button', { name: '현장 보고 제출 (저장·승인 반영)' }));
  await screen.findByText('승인함 #18 상신');
}

test('a field manager is told the report waits for approval', async () => {
  signInAsDemo('field', '박현장', 'site1', 3);
  await submitReport();
  expect(screen.getByText(WAITS)).toBeVisible();
});

test('other roles are not told it waits (their report may apply at once)', async () => {
  await submitReport();
  expect(screen.queryByText(WAITS)).toBeNull();
});
