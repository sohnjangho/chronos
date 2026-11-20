import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { json } from '../../test-helpers';
import ApprovalDetailView from './ApprovalDetail';
import Approvals from './Approvals';
import manifest from './index';
import { AUTO, bodyOf, callsTo, detailOf, item, openSpy, setup, SUMMARY } from './testKit';

const DECIDE = '/api/approvals/3/decide';
const detail = (over: Parameters<typeof detailOf>[0]) => <ApprovalDetailView item={detailOf(over)} scheduleName="5층 사무동 신축" />;
const noteBox = () => screen.getByRole('textbox', { name: /의견/ });
const lastBody = () => bodyOf(DECIDE).at(-1);
const mockDecide = (status: number, body: object = {}) =>
  setup(undefined, {}, () => json(status, status === 200 ? { status: 'approved', version: 4, schedule_id: 1, chat_session_id: 7, owner_is_decider: true, ...body } : body));

async function renderApprovals(params?: Record<string, string>) {
  render(<Approvals windowId="w1" params={params} />);
  await screen.findByRole('heading', { name: '만회안 B 반영 — 크레인 2대' });
}

beforeEach(() => localStorage.clear());
afterEach(() => vi.unstubAllGlobals());

describe('지시서 시험', () => {
  test('reasons are shown in Korean', () => {
    render(detail({ reasons: ['finish_changed', 'condition_changed'] }));
    expect(screen.getByText('준공일')).toBeVisible();
    expect(screen.getByText('조건 변경')).toBeVisible();
  });

  test('approve posts decision and moves the item out of pending', async () => {
    setup();
    await renderApprovals();
    await userEvent.click(screen.getByRole('button', { name: '승인하고 반영' }));
    expect(lastBody()).toEqual({ decision: 'approve', note: '' });
    expect(await screen.findByText('대기 0')).toBeVisible();
  });

  test('conflict shows server message', async () => {
    mockDecide(409, { code: 'version_conflict', message: '그 사이 일정이 바뀌었습니다. 에이전트에게 다시 요청해 주세요.', detail: { current: 4 } });
    await renderApprovals();
    await userEvent.click(screen.getByRole('button', { name: '승인하고 반영' }));
    expect(await screen.findByText(/그 사이 일정이 바뀌었습니다/)).toBeVisible();
  });

  // R3: 다시 짜기는 결정 본문의 의견으로 보내고, 주인이면 대화 창이 approval_id 로 이어 간다(chat 의 resume_approval).
  test('reject-and-retry sends the note with the decision and resumes the chat with it', async () => {
    setup();
    await renderApprovals();
    await userEvent.type(noteBox(), '크레인 추가는 안 됨');
    await userEvent.click(screen.getByRole('button', { name: '거부하고 다시 짜게 하기' }));
    await waitFor(() => expect(lastBody()).toEqual({ decision: 'reject_retry', note: '크레인 추가는 안 됨' }));
    expect(openSpy).toHaveBeenCalledWith('chat', { session: '7', resume_approval: '3' });
  });

  test('auto-applied row can be reverted', async () => {
    setup();
    await renderApprovals();
    await userEvent.click(screen.getByRole('tab', { name: /자동 적용/ }));
    await userEvent.click(screen.getAllByRole('button', { name: '되돌리기' })[0]);
    await waitFor(() => expect(bodyOf('/api/schedules/1/versions/2/restore')).toEqual([{ base_version: 3 }]));
    expect(await screen.findByText(/버전 2의 내용으로 되돌렸습니다/)).toBeVisible();
  });
});

describe('R2 승인이 필요한 이유·숫자·차이 표', () => {
  test('reason lines carry before → after values', () => {
    render(detail({}));
    const why = screen.getByRole('region', { name: '승인이 필요한 이유' });
    expect(within(why).getByText('2027.11.28 → 2027.11.12 (16일 당겨짐)')).toBeVisible();
    expect(within(why).getByText('7개 → 6개 · 경로 바뀜')).toBeVisible();
    expect(within(why).getByText('타워크레인 1대 → 2대')).toBeVisible();
  });

  test('a later finish says 늦어짐 and every reason has a Korean label', () => {
    const all = ['finish_changed', 'critical_path_changed', 'condition_changed', 'first_save', 'structure_changed', 'milestone_changed', 'condition_violated', 'plan_reset', 'rule_save'];
    render(detail({ reasons: all, summary: { finish: { before: '2027-03-10', after: '2027-03-16', delta_days: 6 } } }));
    const why = screen.getByRole('region', { name: '승인이 필요한 이유' });
    for (const label of ['준공일', '크리티컬 패스', '조건 변경', '새 일정의 첫 저장', '구조 변경', '주요 날짜', '조건 위반', 'Plan 다시 잡기', '내 규칙 저장']) {
      expect(within(why).getByText(label)).toBeVisible();
    }
    expect(within(why).getByText('2027.03.10 → 2027.03.16 (6일 늦어짐)')).toBeVisible();
  });

  test('counts never count unchecked conditions as passed', () => {
    render(detail({}));
    expect(screen.getByText('통과 14 · 위반 0 · 점검 안 함 1')).toBeVisible();
    expect(screen.getByText('2일 → 18일')).toBeVisible();
    expect(screen.getByText('6개')).toBeVisible();
  });

  test('the diff table lists activities and changed conditions', () => {
    render(detail({}));
    const table = screen.getByRole('table', { name: '바뀌는 것' });
    const rows = within(table).getAllByRole('row').map((r) => r.textContent);
    expect(rows[1]).toContain('A3010외장 패널2027.07.19 ~ 2027.09.052027.07.07 ~ 2027.08.24−12일');
    expect(rows[3]).toContain('새로 생김');
    expect(rows[4]).toContain('타워크레인1대2대');
  });

  test('[간트에서 보기] opens the 간트차트 program and there is no compare button', async () => {
    setup();
    await renderApprovals();
    await userEvent.click(screen.getByRole('button', { name: '간트에서 보기' }));
    expect(openSpy).toHaveBeenCalledWith('gantt', { id: '1' });
    expect(screen.queryByRole('button', { name: /비교판/ })).toBeNull();
  });

  test('a pending first save has no schedule yet, so no gantt button', () => {
    render(<ApprovalDetailView item={detailOf({ kind: 'first_save', schedule_id: null, reasons: ['first_save'], base_version: 0 })} scheduleName={null} />);
    expect(screen.queryByRole('button', { name: '간트에서 보기' })).toBeNull();
    expect(screen.getByText('새 일정의 첫 저장')).toBeVisible();
  });
});

describe('R3 결정', () => {
  test('reject-and-retry needs a note and does not post without one', async () => {
    setup();
    await renderApprovals();
    await userEvent.click(screen.getByRole('button', { name: '거부하고 다시 짜게 하기' }));
    expect(screen.getByRole('alert')).toHaveTextContent('다시 짜게 하려면 이유를 적어 주세요.');
    expect(callsTo(DECIDE, 'POST')).toHaveLength(0);
  });

  test('when someone else owns the chat the request is left for the owner', async () => {
    setup(undefined, {}, () => json(200, { status: 'rejected', version: null, schedule_id: 1, chat_session_id: 7, owner_is_decider: false }));
    await renderApprovals();
    await userEvent.type(noteBox(), '준공은 그대로 두고 다시');
    await userEvent.click(screen.getByRole('button', { name: '거부하고 다시 짜게 하기' }));
    expect(await screen.findByText('대화 주인에게 다시 짜기 요청을 남겼습니다.')).toBeVisible();
    expect(openSpy).not.toHaveBeenCalled();
  });

  test('plain reject posts reject with the note', async () => {
    setup();
    await renderApprovals();
    await userEvent.type(noteBox(), '  이번에는 안 함 ');
    await userEvent.click(screen.getByRole('button', { name: '거부' }));
    await waitFor(() => expect(lastBody()).toEqual({ decision: 'reject', note: '이번에는 안 함' }));
    expect(await screen.findByText('대기 0')).toBeVisible();
  });

  test('a conflict refreshes the item and shows its status as 충돌', async () => {
    const state = setup(undefined, {}, () => {
      state.rows[0].status = 'conflict';
      return json(409, { code: 'version_conflict', message: '그 사이 일정이 바뀌었습니다. 에이전트에게 다시 요청해 주세요.', detail: { current: 4 } });
    });
    await renderApprovals();
    await userEvent.click(screen.getByRole('button', { name: '승인하고 반영' }));
    expect(await screen.findByText('충돌', { selector: '.apv-status' })).toBeVisible();
    expect(screen.queryByRole('button', { name: '승인하고 반영' })).toBeNull();
  });

  test('already decided shows the server message and refreshes', async () => {
    const state = setup(undefined, {}, () => {
      state.rows[0].status = 'approved';
      state.rows[0].decided_by = '이도윤';
      return json(409, { code: 'already_decided', message: '이미 결정된 건입니다.', detail: null });
    });
    await renderApprovals();
    await userEvent.click(screen.getByRole('button', { name: '승인하고 반영' }));
    expect(await screen.findByText('이미 결정된 건입니다.')).toBeVisible();
    expect(await screen.findByText('승인됨', { selector: '.apv-status' })).toBeVisible();
    expect(screen.getByText(/이도윤/)).toBeVisible();
  });
});

describe('R4·R5 목록', () => {
  test('a stale auto row cannot be reverted and says why', async () => {
    setup();
    await renderApprovals();
    await userEvent.click(screen.getByRole('tab', { name: /자동 적용/ }));
    const rows = within(screen.getByRole('list', { name: '승인 건 목록' })).getAllByRole('listitem');
    expect(within(rows[0]).getByRole('button', { name: '되돌리기' })).toBeEnabled();
    expect(within(rows[1]).getByRole('button', { name: '되돌리기' })).toBeDisabled();
    expect(within(rows[1]).getByText('그 뒤에 바뀐 버전이 있습니다 — 탐색기에서 버전을 고르세요')).toBeVisible();
  });

  test('tabs show pending and auto counts and the approval level from the API', async () => {
    setup();
    await renderApprovals();
    expect(screen.getByRole('tab', { name: '대기 1' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: '결정됨' })).toBeVisible();
    expect(screen.getByRole('tab', { name: '자동 적용 2' })).toBeVisible();
    expect(screen.getByText(/승인 수준:/)).toHaveTextContent('승인 수준: 중요한 것만 (관리자 설정)');
  });

  test('params.id opens that approval on its own tab', async () => {
    setup([item(), ...AUTO, item({ id: 9, status: 'rejected', title: '조립 라인 순서 바꾸기', decided_by: '이도윤', note: '라인 2는 그대로' })]);
    render(<Approvals windowId="w1" params={{ id: '9' }} />);
    expect(await screen.findByRole('heading', { name: '조립 라인 순서 바꾸기' })).toBeVisible();
    expect(screen.getByRole('tab', { name: '결정됨' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText('거부됨', { selector: '.apv-status' })).toBeVisible();
    expect(screen.queryByRole('textbox', { name: /의견/ })).toBeNull();
  });

  test('the manifest opens the screen at 1200×760', () => {
    expect(manifest.defaultSize).toEqual({ w: 1200, h: 760 });
    expect(manifest.badge).toBe('approvals');
  });
});

describe('Fix round 1', () => {
  const second = item({ id: 10, title: '조립동 기초 공사 하루 당김', reasons: ['milestone_changed'] });
  const list = () => screen.getByRole('list', { name: '승인 건 목록' });
  function deferred() {
    let resolve!: (r: Response) => void;
    const promise = new Promise<Response>((r) => (resolve = r));
    return { promise, resolve };
  }

  test('I1: a late detail for an earlier pick never replaces the picked item', async () => {
    const late = deferred();
    setup([item(), second, ...AUTO], { '/api/approvals/3': () => late.promise });
    render(<Approvals windowId="w1" />);
    await userEvent.click(within(await screen.findByRole('list', { name: '승인 건 목록' })).getByRole('button', { name: /조립동 기초 공사/ }));
    expect(await screen.findByRole('heading', { name: '조립동 기초 공사 하루 당김' })).toBeVisible();
    await act(async () => late.resolve(json(200, detailOf())));
    expect(screen.getByRole('heading', { name: '조립동 기초 공사 하루 당김' })).toBeVisible();
    expect(screen.queryByRole('heading', { name: '만회안 B 반영 — 크레인 2대' })).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: '승인하고 반영' }));
    await waitFor(() => expect(bodyOf('/api/approvals/10/decide')).toHaveLength(1));
    expect(bodyOf(DECIDE)).toHaveLength(0);
  });

  test('I1: after a decision the detail is read again only if that item is still picked', async () => {
    const answer = deferred();
    setup([item(), second, ...AUTO], { [`POST ${DECIDE}`]: () => answer.promise });
    await renderApprovals();
    await userEvent.click(screen.getByRole('button', { name: '승인하고 반영' }));
    await userEvent.click(within(list()).getByRole('button', { name: /조립동 기초 공사/ }));
    expect(await screen.findByRole('heading', { name: '조립동 기초 공사 하루 당김' })).toBeVisible();
    const reads = callsTo('/api/approvals/3').length;
    await act(async () => answer.resolve(json(200, { status: 'approved', version: 4, schedule_id: 1, chat_session_id: 7, owner_is_decider: true })));
    expect(await screen.findByText('승인해 버전 4로 저장했습니다.')).toBeVisible();
    expect(callsTo('/api/approvals/3')).toHaveLength(reads);
    expect(screen.getByRole('heading', { name: '조립동 기초 공사 하루 당김' })).toBeVisible();
  });

  test('I1: picking the picked item again reads it again', async () => {
    setup([item(), second, ...AUTO]);
    await renderApprovals();
    const reads = callsTo('/api/approvals/3').length;
    await userEvent.click(within(list()).getByRole('button', { name: /만회안 B 반영/ }));
    await waitFor(() => expect(callsTo('/api/approvals/3')).toHaveLength(reads + 1));
  });

  test('m1: the check line is green only when nothing is unchecked, invalid or violated', () => {
    const check = (c: object) => <ApprovalDetailView item={detailOf({ summary: { ...SUMMARY, check: { passed: 14, violations: [], uncheckable: 0, invalid: 0, ...c } } })} scheduleName={null} />;
    const { rerender } = render(check({}));
    expect(screen.getByText('통과 14 · 위반 0 · 점검 안 함 0')).toHaveClass('is-ok');
    rerender(check({ uncheckable: 1 }));
    expect(screen.getByText('통과 14 · 위반 0 · 점검 안 함 1')).toHaveClass('is-neutral');
    rerender(check({ invalid: 1 }));
    expect(screen.getByText('통과 14 · 위반 0 · 점검 안 함 0 · 형식 틀림 1')).toHaveClass('is-warn');
    rerender(check({ violations: [{ message: '준공이 기한보다 1일 늦습니다.' }] }));
    expect(screen.getByText('통과 14 · 위반 1 · 점검 안 함 0')).toHaveClass('is-bad');
  });

  test('m5: a changed-condition row shows its name on hover, not its id', () => {
    render(detail({}));
    expect(within(screen.getByRole('table', { name: '바뀌는 것' })).getByText('타워크레인')).toHaveAttribute('title', '타워크레인');
  });

  test('m6: when schedule versions cannot be read, revert is off and says so', async () => {
    setup(undefined, { '/api/schedules': () => json(500, { code: 'internal_error', message: '서버에서 문제가 생겼습니다.', detail: null }) });
    await renderApprovals();
    await userEvent.click(screen.getByRole('tab', { name: /자동 적용/ }));
    const rows = within(list()).getAllByRole('listitem');
    expect(within(rows[0]).getByRole('button', { name: '되돌리기' })).toBeDisabled();
    expect(within(rows[0]).getByText('일정 버전을 읽지 못했습니다')).toBeVisible();
  });
});
