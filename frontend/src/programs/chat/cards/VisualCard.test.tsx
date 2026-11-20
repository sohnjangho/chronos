// 대화 카드 visual(Task 44): 도구 visual.make 의 card 사건 모양 그대로. 그림은 id 로 서버에서 읽는다.
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { signInAsDemo, stubFetch } from '../../../test-helpers';
import { CardView, type CardCtx } from './index';

const CARD = { kind: 'visual', visual_id: 7, schedule_id: 1, visual_kind: 'delay_impact', title: '지연 영향', version: 3, data_date: '2027-03-01', verified: true, passed: 10, total: 10, fallback: false, note: '' };
const VISUAL = {
  id: 7, schedule_id: 1, kind: 'delay_impact', title: '지연 영향', version: 3, data_date: '2027-03-01', columns: ['작업', '지연(근무일)'],
  rows: [['터파기', 3]], chart: 'bars', html: '<!DOCTYPE html><html><head></head><body>그림</body></html>', theme: 'comparison', description: '',
  resource_id: 'viz_1', verified: true, passed: 2, total: 2, fallback: false, note: '', external: [], latency_ms: 11000, created_at: '2026-11-20T10:00:00',
};
const ctx: CardCtx = { sessionId: 1, sendText: async () => true, failedQuestionnaire: null, retryResume: () => {} };

beforeEach(() => signInAsDemo());
afterEach(() => vi.unstubAllGlobals());

test('visual card reads the stored visual and shows it', async () => {
  const fetchSpy = stubFetch({ '/api/schedules/1/visuals/7': VISUAL });
  render(<CardView event="card" data={CARD} ctx={ctx} />);
  expect(screen.getByRole('region', { name: '보고서용 그림 — 지연 영향' })).toBeVisible();
  await waitFor(() => expect(document.querySelector('iframe')).not.toBeNull());
  expect(String(fetchSpy.mock.calls[0][0])).toBe('/api/schedules/1/visuals/7');
  expect(screen.getByText(/숫자 대조 통과 2\/2/)).toBeVisible();
  expect((document.querySelector('.vf-stage') as HTMLElement).style.height).toBe('460px');
});

test('크게 보기 opens the same visual in a dialog', async () => {
  stubFetch({ '/api/schedules/1/visuals/7': VISUAL });
  render(<CardView event="card" data={CARD} ctx={ctx} />);
  await userEvent.click(screen.getByRole('button', { name: '크게 보기' }));
  const dialog = screen.getByRole('dialog', { name: '보고서용 그림' });
  await waitFor(() => expect(within(dialog).getByTitle('지연 영향')).toBeVisible());
  await userEvent.click(within(dialog).getByRole('button', { name: '닫기' }));
  expect(screen.queryByRole('dialog')).toBeNull();
});

test('a fallback visual card says why', async () => {
  stubFetch({ '/api/schedules/1/visuals/7': { ...VISUAL, html: null, fallback: true, verified: false, note: 'Liner 그림 검증 실패 → 기본 그림' } });
  render(<CardView event="card" data={{ ...CARD, fallback: true, verified: false, note: 'Liner 그림 검증 실패 → 기본 그림' }} ctx={ctx} />);
  expect(await screen.findByText('Liner 그림 검증 실패 → 기본 그림')).toBeVisible();
  expect(screen.getByRole('img', { name: '지연 영향 (기본 그림)' })).toBeVisible();
});

test('a card without an id is a plain line', () => {
  render(<CardView event="card" data={{ kind: 'visual', title: '지연 영향' }} ctx={ctx} />);
  expect(screen.getByText('그림을 찾을 수 없습니다.')).toBeVisible();
});
