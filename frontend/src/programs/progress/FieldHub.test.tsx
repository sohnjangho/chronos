// 현장 허브(FieldHub) 카드 시험: 사진 판독 결과(F1).
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { useSession } from '../../os/session';
import { signInAsDemo, stubFetch } from '../../test-helpers';
import FieldHub from './FieldHub';
import type { FieldData, FieldItem } from './fieldApi';

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

test('a photo read by the vision model shows its percentage and one-sentence reason (F1)', async () => {
  const card = await photoCard(
    item({ reported_progress: 40, payload_json: { photo_name: 'rebar.jpg', ai_progress: 40, ai_reason: '철근 배근은 끝났고 거푸집은 절반쯤 섰다.', ai_risks: [] } }),
  );
  expect(within(card).getByRole('progressbar')).toHaveAttribute('aria-valuenow', '40');
  expect(within(card).getByText('40%')).toBeVisible();
  expect(within(card).getByText('판독 근거: 철근 배근은 끝났고 거푸집은 절반쯤 섰다.')).toBeVisible();
  expect(within(card).getByRole('button', { name: '승인함 상신 · 증빙 확정' })).toBeEnabled();
});
