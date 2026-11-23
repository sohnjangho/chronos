import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { useCurrentSchedule } from '../../os/currentSchedule';
import { useSession } from '../../os/session';
import { json, signInAsDemo } from '../../test-helpers';
import ApprovalDetailView from './ApprovalDetail';
import DecisionBox from './DecisionBox';
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
afterEach(() => {
  vi.unstubAllGlobals();
  useSession.getState().logout();
});

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

  // W1 후속: 자동 적용 되돌리기도 탐색기 되돌리기처럼 열린 일정 창(간트·공정률 등)에 다시 읽으라고 알린다.
  test('W1: a revert tells the open schedule windows to read again', async () => {
    setup();
    await renderApprovals();
    await userEvent.click(screen.getByRole('tab', { name: /자동 적용/ }));
    const before = useCurrentSchedule.getState().reloadToken;
    await userEvent.click(screen.getAllByRole('button', { name: '되돌리기' })[0]);
    expect(await screen.findByText(/버전 2의 내용으로 되돌렸습니다/)).toBeVisible();
    expect(useCurrentSchedule.getState().reloadToken).toBe(before + 1);
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
    const all = ['finish_changed', 'critical_path_changed', 'condition_changed', 'first_save', 'structure_changed', 'milestone_changed', 'condition_violated', 'plan_reset', 'rule_save', 'field_report'];
    render(detail({ reasons: all, summary: { finish: { before: '2027-03-10', after: '2027-03-16', delta_days: 6 } } }));
    const why = screen.getByRole('region', { name: '승인이 필요한 이유' });
    for (const label of ['준공일', '크리티컬 패스', '조건 변경', '새 일정의 첫 저장', '구조 변경', '주요 날짜', '조건 위반', 'Plan 다시 잡기', '내 규칙 저장', '현장 보고']) {
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

describe('내 규칙 저장 (Task 35)', () => {
  const RULE = { scope: 'domain', domain: 'construction', text: '층당 골조 10일 넘지 않기', kind: 'max_duration', params: { days: 10 } };
  const ruleItem = (over: Parameters<typeof detailOf>[0] = {}) =>
    detailOf({ id: 3, kind: 'rule', reasons: ['rule_save'], schedule_id: null, base_version: 0, title: '내 규칙 저장 — 층당 골조 10일 넘지 않기', summary: { rule: RULE }, ...over }, []);

  test('approval detail renders a rule save', () => {
    render(<ApprovalDetailView item={ruleItem()} scheduleName={null} />);
    expect(screen.getByText('내 규칙 저장')).toBeVisible();
    expect(screen.getByText('분야 전체 · 건설')).toBeVisible();
    expect(screen.queryByRole('button', { name: '간트에서 보기' })).toBeNull();
  });

  test('a rule save shows its text and value, and no change table', () => {
    render(<ApprovalDetailView item={ruleItem()} scheduleName={null} />);
    const block = screen.getByRole('region', { name: '내 규칙 저장' });
    expect(within(block).getByText('층당 골조 10일 넘지 않기')).toBeVisible();
    expect(within(block).getByText('기간 상한 · 10일')).toBeVisible();
    expect(screen.queryByRole('table', { name: '바뀌는 것' })).toBeNull();
    expect(screen.queryByText('기준 버전 0', { exact: false })).toBeNull();
  });

  test.each([
    [{ scope: 'schedule', kind: 'min_gap', params: { after_tag: '타설', days: 7 } }, '이 일정', "간격 · '타설' 뒤 근무일 7일"],
    [{ kind: 'blocked_period', params: { start_md: [12, 1], end_md: [2, 28], tag: '타설' } }, '분야 전체 · 건설', "금지 기간 · 12.1~2.28 '타설'"],
    [{ kind: 'text_only', params: {}, domain: 'space' }, '분야 전체 · space', '말로 된 규칙 (자동 점검 안 됨)'],
  ])('rule kinds are summarised %#', (over, scope, value) => {
    render(<ApprovalDetailView item={ruleItem({ summary: { rule: { ...RULE, ...over } } })} scheduleName={null} />);
    expect(screen.getByText(scope)).toBeVisible();
    expect(screen.getByText(value)).toBeVisible();
  });

  test('an auto-saved rule says why it has no revert', async () => {
    setup([item(), ruleItem({ id: 8, status: 'auto', version: null, restore_to: null, chat_session_id: null })]);
    await renderApprovals();
    await userEvent.click(screen.getByRole('tab', { name: /자동 적용/ }));
    const row = within(screen.getByRole('list', { name: '승인 건 목록' })).getAllByRole('listitem')[0];
    expect(within(row).getByRole('button', { name: '되돌리기' })).toBeDisabled();
    expect(within(row).getByText('규칙 저장은 되돌리기 대신 내 규칙에서 끄거나 지웁니다')).toBeVisible();
  });

  test('the decision box tells that approving saves a rule', async () => {
    setup([ruleItem()]);
    render(<Approvals windowId="w1" params={{ id: '3' }} />);
    expect(await screen.findByText('승인하면 내 규칙으로 저장됩니다. 일정은 바뀌지 않고, 조건·규칙 창에서 끄거나 지울 수 있습니다.')).toBeVisible();
    expect(screen.queryByText(/버전 1로 저장/)).toBeNull();
  });
});

// W6(11-23): Plan 이 바뀌는 승인 건이면 기준선(Plan)도 새로 잡힌다고 결정 상자에 미리 알린다.
describe('W6 결정 상자 안내', () => {
  const box = (summary: Record<string, unknown>) =>
    render(<DecisionBox item={detailOf({ base_version: 3, summary: { ...SUMMARY, ...summary } })} onDecide={async () => {}} />);

  test('a plan-changing approval says the baseline is set again', () => {
    box({ plan_change: true });
    expect(screen.getByText('승인하면 버전 4로 저장되고, 기준선(Plan)도 이 안으로 새로 잡힙니다. 탐색기에서 되돌릴 수 있습니다.')).toBeVisible();
  });

  // 서버는 모든 승인 건 summary 에 plan_change 를 넣는다(store.approvals.create) — 만회안 복사본은 true, 말로 된 일정 규칙은 false.
  test('a submitted recovery plan says the baseline is set again', () => {
    box({ plan_change: true, changed_count: 3 });
    expect(screen.getByText(/기준선\(Plan\)도 이 안으로 새로 잡힙니다/)).toBeVisible();
  });

  test('a text-only schedule rule says the baseline stays', () => {
    box({ plan_change: false, rule: { scope: 'schedule', domain: 'construction', text: '타설 전날 알림', kind: 'text_only', params: {} } });
    expect(screen.getByText('승인하면 내 규칙이 반영되어 버전 4로 저장됩니다. 기존 기준선(Plan)은 유지됩니다.')).toBeVisible();
    expect(screen.queryByText(/기준선\(Plan\)도/)).toBeNull();
  });

  test('without the plan change mark the hint stays as before', () => {
    box({});
    expect(screen.getByText('승인하면 버전 4로 저장되고, 탐색기에서 되돌릴 수 있습니다.')).toBeVisible();
    expect(screen.queryByText(/기준선\(Plan\)도/)).toBeNull();
  });
});

// F4 후속: 현장 관리자(field)는 승인·거부할 수 없다(서버 403) — 결정 단추 대신 한 줄 안내.
describe('F4 현장 관리자', () => {
  test('the field role sees no decision buttons, only a note', async () => {
    setup();
    signInAsDemo('field', '박현장', 'site1', 3);
    await renderApprovals();
    expect(screen.getByText('현장 관리자는 승인·거부할 수 없습니다')).toBeVisible();
    for (const name of ['승인하고 반영', '거부', '거부하고 다시 짜게 하기']) expect(screen.queryByRole('button', { name })).toBeNull();
    expect(screen.queryByRole('textbox', { name: /의견/ })).toBeNull();
  });

  test('a user still decides', async () => {
    setup();
    signInAsDemo('user', '김민지');
    await renderApprovals();
    expect(screen.getByRole('button', { name: '승인하고 반영' })).toBeVisible();
    expect(screen.queryByText('현장 관리자는 승인·거부할 수 없습니다')).toBeNull();
  });
});

// 재확인 #18: 현장 회신의 실제 시작이 선행이 허락하는 날보다 이르면 서버가 summary.notes 에 남긴다 — 상세에 보인다.
describe('승인 요약의 알릴 것', () => {
  test('notes in the summary are shown on the detail', () => {
    const note = 'B 작업 B: 실제 시작을 Data Date 2027-03-04로 넣었습니다 — 선행 작업·제약으로 계산한 가장 이른 시작 2027-03-09보다 이릅니다.';
    render(detail({ summary: { ...SUMMARY, notes: [note] } }));
    expect(within(screen.getByRole('region', { name: '알릴 것' })).getByText(note)).toBeVisible();
  });

  test('without notes there is no such section', () => {
    render(detail({}));
    expect(screen.queryByRole('region', { name: '알릴 것' })).toBeNull();
  });
});

// 재확인 #14: 예전 방식(판독 없이 지어낸 숫자)의 사진 항목에서 나온 건 — 서버가 blocked 로 알린다. 승인은 막고 거부는 된다.
describe('반영할 수 없는 건', () => {
  const OLD = '이전 방식으로 만든 판독이라 반영할 수 없습니다 — 사진을 다시 올려 주세요';

  test('a blocked approval shows why and cannot be approved, but can be rejected', async () => {
    setup([item({ title: '[현장 반영] A1210 1층 철근 배근 (95%)' })], {
      '/api/approvals/3': () => json(200, { ...detailOf({ title: '[현장 반영] A1210 1층 철근 배근 (95%)' }), blocked: OLD }),
    });
    render(<Approvals windowId="w1" />);
    expect(await screen.findByText(OLD)).toBeVisible();
    expect(screen.getByRole('button', { name: '승인하고 반영' })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: '거부' }));
    await waitFor(() => expect(lastBody()).toEqual({ decision: 'reject', note: '' }));
  });

  test('an approval without the mark decides as before', async () => {
    setup();
    await renderApprovals();
    expect(screen.queryByText(OLD)).toBeNull();
    expect(screen.getByRole('button', { name: '승인하고 반영' })).toBeEnabled();
  });
});

// 재확인 2: 현장 관리자가 올려 기다리는 건은 사유 「현장 보고」 — 승인이 필요한 이유와 목록 꼬리표에 보인다.
describe('현장 보고 사유', () => {
  test('the reason explains why it waits and the list shows its tag', async () => {
    setup([item({ id: 3, title: '[현장 반영] A1110 기초 콘크리트 타설 (10%)', reasons: ['field_report'] })]);
    render(<Approvals windowId="w1" />);
    await screen.findByRole('heading', { name: '[현장 반영] A1110 기초 콘크리트 타설 (10%)' });
    const why = screen.getByRole('region', { name: '승인이 필요한 이유' });
    expect(within(why).getByText('현장 보고')).toBeVisible();
    expect(within(why).getByText('현장 관리자가 올린 건이라 승인 수준과 상관없이 승인을 기다립니다 — 승인되기 전에는 일정이 바뀌지 않습니다.')).toBeVisible();
    expect(within(screen.getByRole('list', { name: '승인 건 목록' })).getByText('현장 보고')).toBeVisible();
  });
});

// 재확인 2(#14·#13): 반영할 수 없는 건에는 「승인하면 버전 N…」을 보이지 않고, 버전은 지금 일정의 다음 버전으로 센다.
describe('결정 상자 안내의 버전', () => {
  const OLD = '이전 방식으로 만든 판독이라 반영할 수 없습니다 — 사진을 다시 올려 주세요';

  test('a blocked approval has no 「승인하면 버전」 line', () => {
    render(<DecisionBox item={{ ...detailOf({ base_version: 4 }), blocked: OLD }} currentVersion={9} onDecide={async () => {}} />);
    expect(screen.queryByText(/승인하면/)).toBeNull();
    expect(screen.getByText(OLD)).toBeVisible();
  });

  test('the version is the next one of the schedule as it is now', () => {
    render(<DecisionBox item={detailOf({ base_version: 9 })} currentVersion={9} onDecide={async () => {}} />);
    expect(screen.getByText('승인하면 버전 10으로 저장되고, 탐색기에서 되돌릴 수 있습니다.')).toBeVisible();
  });

  test('an approval made on an older version says it will not apply as it is', () => {
    render(<DecisionBox item={detailOf({ base_version: 4 })} currentVersion={9} onDecide={async () => {}} />);
    expect(screen.queryByText(/버전 5/)).toBeNull();
    expect(screen.getByText('버전 4 기준으로 만든 건이라 지금 일정(버전 9)에는 그대로 반영되지 않습니다 — 승인하면 충돌로 남습니다.')).toBeVisible();
  });

  test('the approvals window passes the current schedule version', async () => {
    setup([item({ base_version: 2 })]);
    render(<Approvals windowId="w1" />);
    await screen.findByRole('heading', { name: '만회안 B 반영 — 크레인 2대' });
    expect(await screen.findByText('버전 2 기준으로 만든 건이라 지금 일정(버전 3)에는 그대로 반영되지 않습니다 — 승인하면 충돌로 남습니다.')).toBeVisible();
  });
});
