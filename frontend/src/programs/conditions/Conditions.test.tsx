import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { useCurrentSchedule } from '../../os/currentSchedule';
import { useSession } from '../../os/session';
import { resetShellState } from '../../os/shellReset';
import { useSchedulePreview } from '../../os/schedulePreview';
import { useUiContext } from '../../os/uiContext';
import { useWindows } from '../../os/windowStore';
import { json } from '../../test-helpers';
import Conditions from './Conditions';
import type { Cond, Preview } from './condApi';
import manifest from './index';
import { bodies, cond, deferred, fetchMock, INPUTS, m, makeView, mockPreview, openSpy, respond, setup, URL } from './testKit';

const PREVIEW = `${URL}/preview`;
const qty = (name: string) => screen.getByRole('textbox', { name: `${name} 수량` });
const item = (text: string) => screen.getByRole('listitem', { name: new RegExp(text) });
const column = (name: string) => screen.getByRole('region', { name });
const preview = () => useSchedulePreview.getState().previews[1] ?? null;

async function renderC(params: Record<string, string> | undefined = { id: '1' }) {
  const view = render(<Conditions windowId="w1" params={params} />);
  await screen.findByRole('region', { name: '④ 입력 조건' });
  return view;
}

function mockPreviewRoute(p: Preview) {
  setup({ [`POST ${PREVIEW}`]: respond(p) });
}

async function setCrane(value: string) {
  await userEvent.clear(qty('타워크레인'));
  await userEvent.type(qty('타워크레인'), value);
}

beforeEach(() => {
  useSchedulePreview.getState().reset();
  useUiContext.getState().reset();
  useCurrentSchedule.setState({ current: null });
});
afterEach(() => vi.unstubAllGlobals());

describe('지시서 시험', () => {
  test('four columns with lock labels', async () => {
    setup();
    await renderC();
    expect(screen.getByText('못 바꿈')).toBeVisible();
    expect(screen.getByText('관리자만 수정')).toBeVisible();
    expect(['① 기본 규칙', '② 분야 규칙', '③ 내 규칙', '④ 입력 조건'].map((n) => column(n))).toHaveLength(4);
  });

  test('changing a quantity previews after debounce and shows the delta', async () => {
    mockPreviewRoute(mockPreview({ feasible: true, before: { finish: '2027-11-24' }, after: { finish: '2027-11-12' }, moved: [m('A3010')] }));
    await renderC();
    await setCrane('2');
    expect(bodies(PREVIEW)).toEqual([]); // 300ms 를 기다린다
    expect(await screen.findByText(/11\.24 → 11\.12/)).toBeVisible();
    expect(preview()).not.toBeNull();
    expect(preview()!.moved).toEqual([m('A3010')]);
    expect(bodies(PREVIEW)).toEqual([{ base_version: 3, changes: [{ id: 'in.crane', params: { capacity: 2 } }] }]);
  });

  test('revert clears the preview', async () => {
    mockPreviewRoute(mockPreview({ moved: [m('A3010')] }));
    await renderC();
    await setCrane('2');
    await screen.findByText(/11\.24 → 11\.12/);
    await userEvent.click(screen.getByRole('button', { name: '되돌리기' }));
    expect(preview()).toBeNull();
    expect(qty('타워크레인')).toHaveValue('1');
    expect(screen.queryByText(/미리 보기 중/)).toBeNull();
  });

  test('infeasible preview hides confirm and offers the agent', async () => {
    mockPreviewRoute(mockPreview({ feasible: false, violations: [{ condition_id: 'in.finish_by', message: '준공이 기한보다 20일 늦습니다.' }], edits: { 'in.finish_by': { date: '2027-06-30' } } }));
    await renderC();
    await userEvent.clear(screen.getByRole('textbox', { name: '준공 기한 날짜' }));
    await userEvent.type(screen.getByRole('textbox', { name: '준공 기한 날짜' }), '2027-06-30');
    expect(await screen.findByText('준공이 기한보다 20일 늦습니다.')).toBeVisible();
    expect(screen.queryByRole('button', { name: '확정' })).toBeNull();
    expect(screen.getByRole('button', { name: '에이전트에게 맞추게 하기' })).toBeVisible();
    expect(screen.getByRole('button', { name: '에이전트에게 맞추게 하기' })).toHaveClass('ui-btn-primary');
    // fix1 I6: 이름은 종류와 지금(미리 보기) 값으로 만든다
    expect(within(screen.getByRole('alert')).getByText('준공 기한 2027.06.30: 준공이 기한보다 20일 늦습니다.')).toBeVisible();
    expect(screen.getByRole('listitem', { name: '준공 기한 2027.06.30' })).toBeVisible();
    expect(bodies(PREVIEW)[0].changes).toEqual([{ id: 'in.finish_by', params: { date: '2027-06-30' } }]);
  });

  test('commit that needs approval says so', async () => {
    setup({ [`POST ${PREVIEW}`]: respond(mockPreview()), [`POST ${URL}/commit`]: respond({ applied: false, approval_id: 7, version: null }) });
    await renderC();
    await setCrane('2');
    await screen.findByText(/11\.24 → 11\.12/);
    await userEvent.click(screen.getByRole('button', { name: '확정' }));
    expect(await screen.findByText(/승인함으로 보냈습니다/)).toBeVisible();
    expect(bodies(`${URL}/commit`)).toEqual([{ base_version: 3, changes: [{ id: 'in.crane', params: { capacity: 2 } }] }]);
    expect(preview()).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: '승인함 열기' }));
    expect(openSpy).toHaveBeenCalledWith('approvals', { id: '7' });
  });

  test('uncheckable condition is labeled, never "통과"', async () => {
    setup();
    await renderC();
    expect(within(item('안전 우선')).getByText('자동 점검 안 됨')).toBeVisible();
    expect(within(item('안전 우선')).queryByText('통과')).toBeNull();
  });
});

describe('R3 · 미리 보기 차례·충돌', () => {
  test('typing quickly sends one preview with the last value', async () => {
    mockPreviewRoute(mockPreview());
    await renderC();
    await setCrane('23');
    await screen.findByText(/11\.24 → 11\.12/);
    expect(bodies(PREVIEW).map((b) => b.changes)).toEqual([[{ id: 'in.crane', params: { capacity: 23 } }]]);
  });

  test('only the latest preview response is applied', async () => {
    const answers: ((r: Response) => void)[] = [];
    setup({ [`POST ${PREVIEW}`]: () => new Promise<Response>((resolve) => answers.push(resolve)) });
    await renderC();
    await setCrane('2');
    await waitFor(() => expect(answers).toHaveLength(1));
    await userEvent.type(qty('타워크레인'), '3');
    await waitFor(() => expect(answers).toHaveLength(2));
    await act(async () => answers[1](json(200, mockPreview({ after: { finish: '2027-11-05' }, moved: [m('A3020')] }))));
    expect(await screen.findByText(/11\.24 → 11\.05/)).toBeVisible();
    await act(async () => answers[0](json(200, mockPreview({ after: { finish: '2027-11-12' }, moved: [m('A3010')] }))));
    expect(screen.queryByText(/11\.24 → 11\.12/)).toBeNull();
    expect(preview()!.moved).toEqual([m('A3020')]);
  });

  test('version_conflict reloads the conditions and says so', async () => {
    let reads = 0;
    const fresh = makeView(INPUTS.map((c) => (c.id === 'in.crane' ? { ...c, params: { ...c.params, capacity: 2 } } : c)));
    setup({
      [URL]: () => json(200, reads++ === 0 ? makeView() : { ...fresh, version: 4 }),
      [`POST ${PREVIEW}`]: respond({ code: 'version_conflict', message: '그 사이 일정이 바뀌었습니다. 다시 불러와 주세요.', detail: { current: 4 } }, 409),
    });
    await renderC();
    await setCrane('3');
    expect(await screen.findByText('그 사이 일정이 바뀌어 다시 불러왔습니다.')).toBeVisible();
    expect(reads).toBe(2);
    expect(qty('타워크레인')).toHaveValue('2');
    expect(preview()).toBeNull();
  });

  test('a refused change shows the server message and keeps nothing previewed', async () => {
    setup({ [`POST ${PREVIEW}`]: respond({ code: 'invalid_change', message: 'in.crane: 용량이 너무 큽니다.', detail: null }, 422) });
    await renderC();
    await setCrane('999');
    expect(await screen.findByText('in.crane: 용량이 너무 큽니다.')).toBeVisible();
    expect(preview()).toBeNull();
  });

  test('a value that is not a whole number is marked and not previewed', async () => {
    setup();
    await renderC();
    await setCrane('두 대');
    expect(qty('타워크레인')).toHaveAttribute('aria-invalid', 'true');
    await new Promise((r) => setTimeout(r, 400));
    expect(bodies(PREVIEW)).toEqual([]);
  });

  test('typing the saved value back drops the change and the preview', async () => {
    mockPreviewRoute(mockPreview());
    await renderC();
    await setCrane('2');
    await screen.findByText(/11\.24 → 11\.12/);
    await setCrane('1');
    await waitFor(() => expect(preview()).toBeNull());
    expect(screen.queryByRole('button', { name: '확정' })).toBeNull();
  });
});

describe('R4·R5 · 확정과 에이전트', () => {
  test('a commit applied at once reloads and clears the preview', async () => {
    let reads = 0;
    setup({
      [URL]: () => json(200, { ...makeView(), version: 3 + (reads++ === 0 ? 0 : 1) }),
      [`POST ${PREVIEW}`]: respond(mockPreview()),
      [`POST ${URL}/commit`]: respond({ applied: true, approval_id: 8, version: 4 }),
    });
    await renderC();
    await setCrane('2');
    await screen.findByText(/11\.24 → 11\.12/);
    await userEvent.click(screen.getByRole('button', { name: '확정' }));
    expect(await screen.findByText('확정했습니다 · 버전 4')).toBeVisible();
    expect(reads).toBe(2);
    expect(preview()).toBeNull();
  });

  test('asking the agent opens the chat with the request text in the composer', async () => {
    setup({
      [`POST ${PREVIEW}`]: respond(mockPreview()),
      [`POST ${URL}/ask-agent`]: respond({ chat_session_id: 12, text: '조건에 맞게 고쳐 주세요.' }),
    });
    await renderC();
    await setCrane('2');
    await screen.findByText(/11\.24 → 11\.12/);
    await userEvent.click(screen.getByRole('button', { name: '에이전트에게 맞추게 하기' }));
    await waitFor(() => expect(openSpy).toHaveBeenCalledWith('chat', { session: '12', compose: '조건에 맞게 고쳐 주세요.' }));
    expect(bodies(`${URL}/ask-agent`)).toEqual([{ base_version: 3, changes: [{ id: 'in.crane', params: { capacity: 2 } }] }]);
  });

  test('with violations already saved the agent is offered without a change', async () => {
    const late = INPUTS.map((c) => (c.id === 'in.finish_by' ? { ...c, state: 'violated' as const, message: '준공이 기한보다 4일 늦습니다.' } : c));
    setup({ [URL]: { ...makeView(late), summary: { passed: 7, violated: 1, uncheckable: 2 } }, [`POST ${URL}/ask-agent`]: respond({ chat_session_id: 3, text: '고쳐 주세요.' }) });
    await renderC();
    await userEvent.click(screen.getByRole('button', { name: '에이전트에게 맞추게 하기' }));
    await waitFor(() => expect(openSpy).toHaveBeenCalledWith('chat', { session: '3', compose: '고쳐 주세요.' }));
    expect(bodies(`${URL}/ask-agent`)).toEqual([{ base_version: 3, changes: [] }]);
  });
});

describe('R2 · 일정판에 넘기는 미리 보기', () => {
  test('closing the window clears the preview', async () => {
    mockPreviewRoute(mockPreview({ moved: [m('A3010')] }));
    const view = await renderC();
    await setCrane('2');
    await screen.findByText(/11\.24 → 11\.12/);
    expect(preview()?.source).toBe('conditions');
    view.unmount();
    expect(preview()).toBeNull();
  });
});

describe('R6 · 겹마다 바꿀 수 있는 것', () => {
  test('an admin switches a domain rule off; the change is previewed', async () => {
    mockPreviewRoute(mockPreview());
    await renderC();
    await userEvent.click(within(item('슬래브 거푸집')).getByRole('button', { name: '끄기' }));
    await waitFor(() => expect(bodies(PREVIEW)).toHaveLength(1));
    expect(bodies(PREVIEW)[0].changes).toEqual([{ id: 'construction.curing', enabled: false }]);
    expect(within(item('슬래브 거푸집')).getByRole('button', { name: '켜기' })).toBeVisible();
  });

  test('a user sees domain rules read-only; base and my rules have no controls', async () => {
    setup({}, 'user');
    await renderC();
    expect(within(column('② 분야 규칙')).queryAllByRole('button')).toEqual([]);
    expect(within(column('① 기본 규칙')).queryAllByRole('button')).toEqual([]);
    expect(within(column('③ 내 규칙')).queryAllByRole('textbox')).toEqual([]);
    expect(within(column('③ 내 규칙')).queryAllByRole('button')).toEqual([]);
    expect(within(item('안전 우선')).getByRole('button', { name: '끄기' })).toBeVisible();
  });

  test('used activities fold open under a resource', async () => {
    setup();
    await renderC();
    await userEvent.click(within(item('타워크레인')).getByText('쓰는 액티비티 2개'));
    expect(within(item('타워크레인')).getByText('A3010, A3020')).toBeVisible();
  });
});

describe('R7·R9 · 상태 수와 많은 조건', () => {
  test('the summary counts passed, violated and unchecked separately', async () => {
    setup();
    await renderC();
    expect(screen.getByText('통과 8')).toBeVisible();
    expect(screen.getByText('위반 0')).toBeVisible();
    expect(screen.getByText('자동 점검 안 됨 2')).toBeVisible();
  });

  test('search and state filter narrow every column', async () => {
    setup();
    await renderC();
    await userEvent.type(screen.getByRole('searchbox', { name: '조건 찾기' }), '크레인');
    expect(within(column('④ 입력 조건')).getAllByRole('listitem').map((li) => li.getAttribute('aria-label'))).toEqual(['타워크레인']);
    expect(within(column('① 기본 규칙')).getByText('맞는 조건 없음')).toBeVisible();
    await userEvent.clear(screen.getByRole('searchbox', { name: '조건 찾기' }));
    await userEvent.click(screen.getByRole('radio', { name: /자동 점검 안 됨/ }));
    const shown = screen.getAllByRole('listitem').map((li) => li.getAttribute('aria-label'));
    expect(shown).toEqual(['슬래브 거푸집 해체는 타설 뒤 7일 이상 습윤 양생을 거친 뒤에 한다', '"안전 우선으로 여유 있게"']);
  });

  test('thirty-odd input conditions are grouped by kind with counts', async () => {
    const many: Cond[] = [
      ...Array.from({ length: 12 }, (_, i) => cond({ id: `in.r${i}`, layer: 'input', kind: 'resource_cap', params: { resource_id: `r${i}`, capacity: 1 }, text: `자원 ${i}` })),
      ...Array.from({ length: 10 }, (_, i) => cond({ id: `in.m${i}`, layer: 'input', kind: 'milestone_by', params: { activity_id: `A${i}`, date: '2027-05-01' }, text: `마일스톤 ${i}` })),
      ...Array.from({ length: 10 }, (_, i) => cond({ id: `in.t${i}`, layer: 'input', kind: 'text_only', text: `말로 된 조건 ${i}`, state: 'uncheckable' })),
    ];
    setup({ [URL]: makeView(many) });
    await renderC();
    const input = column('④ 입력 조건');
    expect(within(input).getByRole('heading', { name: '자원 12' })).toBeVisible();
    expect(within(input).getByRole('heading', { name: '날짜 10' })).toBeVisible();
    expect(within(input).getByRole('heading', { name: '말로 된 조건 10' })).toBeVisible();
    expect(within(input).getByText('32개')).toBeVisible();
  });
});

describe('창', () => {
  test('the title names the schedule and the window tells the agent which schedule it shows', async () => {
    setup();
    await renderC();
    expect(useWindows.getState().wins[0].title).toBe('조건·규칙 — 5층 사무동 신축');
    expect(useUiContext.getState().byWindow.w1).toEqual({ program: 'conditions', schedule_id: 1 });
  });

  test('without params it uses the OS current schedule, and asks to pick one when there is none', async () => {
    setup();
    useCurrentSchedule.setState({ current: { id: 1, name: '5층 사무동 신축' } });
    const view = await renderC(undefined);
    expect(fetchMock).toHaveBeenCalledWith(URL, expect.anything());
    view.unmount();
    useCurrentSchedule.setState({ current: null });
    render(<Conditions windowId="w1" />);
    expect(screen.getByText('일정을 먼저 고르세요. 메뉴바에서 현장을 고르면 그 일정의 조건이 보입니다.')).toBeVisible();
  });

  test('the manifest is a 1400×860 work program with the real screen', () => {
    expect([manifest.id, manifest.kind, manifest.defaultSize]).toEqual(['conditions', 'work', { w: 1400, h: 860 }]);
  });
});

describe('Fix round 1', () => {
  const agentButton = () => screen.queryByRole('button', { name: '에이전트에게 맞추게 하기' });

  test('I3 · only a domain change hides the agent; adding an input change brings it back', async () => {
    mockPreviewRoute(mockPreview());
    await renderC();
    await userEvent.click(within(item('슬래브 거푸집')).getByRole('button', { name: '끄기' }));
    await screen.findByText(/미리 보기 중/);
    expect(agentButton()).toBeNull();
    expect(screen.getByRole('button', { name: '확정' })).toBeVisible();
    await setCrane('2');
    await waitFor(() => expect(bodies(PREVIEW)).toHaveLength(2));
    expect(await screen.findByRole('button', { name: '에이전트에게 맞추게 하기' })).toBeVisible();
  });

  test('I4 · after an applied commit the value fields show the reloaded stored values (slow GET)', async () => {
    const reload = deferred();
    let reads = 0;
    const fresh = { ...makeView(INPUTS.map((c) => (c.id === 'in.crane' ? { ...c, params: { ...c.params, capacity: 2 } } : c))), version: 4 };
    setup({
      [URL]: () => (reads++ === 0 ? json(200, makeView()) : reload.route()),
      [`POST ${PREVIEW}`]: respond(mockPreview()),
      [`POST ${URL}/commit`]: respond({ applied: true, approval_id: 8, version: 4 }),
    });
    await renderC();
    await setCrane('2');
    await screen.findByText(/11\.24 → 11\.12/);
    await userEvent.click(screen.getByRole('button', { name: '확정' }));
    await waitFor(() => expect(reload.count()).toBe(1));
    await act(async () => reload.resolve(0, fresh));
    expect(await screen.findByText('확정했습니다 · 버전 4')).toBeVisible();
    expect(qty('타워크레인')).toHaveValue('2');
  });

  test('I4 · a conflict reload also refills the fields with the new stored values (slow GET)', async () => {
    const reload = deferred();
    let reads = 0;
    const fresh = { ...makeView(INPUTS.map((c) => (c.id === 'in.crane' ? { ...c, params: { ...c.params, capacity: 3 } } : c))), version: 4 };
    setup({
      [URL]: () => (reads++ === 0 ? json(200, makeView()) : reload.route()),
      [`POST ${PREVIEW}`]: respond({ code: 'version_conflict', message: 'x', detail: { current: 4 } }, 409),
    });
    await renderC();
    await setCrane('2');
    await waitFor(() => expect(reload.count()).toBe(1));
    await act(async () => reload.resolve(0, fresh));
    expect(await screen.findByText('그 사이 일정이 바뀌어 다시 불러왔습니다.')).toBeVisible();
    expect(qty('타워크레인')).toHaveValue('3');
  });

  test('I5 · a preview answer that arrives after the window closed does not refill the OS store', async () => {
    const late = deferred();
    setup({ [`POST ${PREVIEW}`]: late.route });
    const view = await renderC();
    await setCrane('2');
    await waitFor(() => expect(late.count()).toBe(1));
    view.unmount();
    await act(async () => late.resolve(0, mockPreview({ moved: [m('A3010')] })));
    expect(preview()).toBeNull();
  });

  test('I5 · …nor after logout', async () => {
    const late = deferred();
    setup({ [`POST ${PREVIEW}`]: late.route });
    await renderC();
    await setCrane('2');
    await waitFor(() => expect(late.count()).toBe(1));
    act(() => {
      useSession.getState().logout();
      resetShellState();
    });
    await act(async () => late.resolve(0, mockPreview({ moved: [m('A3010')] })));
    expect(preview()).toBeNull();
  });

  test('I6 · date and number conditions are named from kind and value', async () => {
    setup();
    await renderC();
    expect(item('준공 기한 2027.11.30')).toBeVisible();
    expect(within(column('③ 내 규칙')).getByRole('listitem', { name: '액티비티 기간 10일 이하' })).toBeVisible();
    // 기본 규칙(달력 종류지만 값이 없음)은 글 그대로
    expect(within(column('① 기본 규칙')).getByRole('listitem', { name: '달력에 일할 수 있는 날이 있음' })).toBeVisible();
  });

  test('m4 · a wrong value blocks 확정 with the reason inline', async () => {
    mockPreviewRoute(mockPreview());
    await renderC();
    await setCrane('2');
    await screen.findByText(/11\.24 → 11\.12/);
    await userEvent.clear(qty('철근공'));
    await userEvent.type(qty('철근공'), '열 명');
    expect(within(item('철근공')).getByText('0 이상 정수로 적어 주세요.')).toBeVisible();
    expect(await screen.findByText('값이 틀린 칸이 있어 확정할 수 없습니다.')).toBeVisible();
    await waitFor(() => expect(bodies(PREVIEW)).toHaveLength(2)); // 크레인 바꿈만 다시 미리 본다
    await act(() => new Promise((r) => setTimeout(r, 50))); // 그 응답까지 받은 뒤에도
    expect(screen.getByRole('button', { name: '확정' })).toBeDisabled();
    await userEvent.clear(qty('철근공'));
    await userEvent.type(qty('철근공'), '12');
    await waitFor(() => expect(screen.getByRole('button', { name: '확정' })).toBeEnabled());
    expect(screen.queryByText('값이 틀린 칸이 있어 확정할 수 없습니다.')).toBeNull();
  });

  test('m6 · arrow keys move through the state filter', async () => {
    setup();
    await renderC();
    const all = screen.getByRole('radio', { name: '전체' });
    expect(all).toHaveAttribute('tabindex', '0');
    expect(screen.getByRole('radio', { name: /^통과/ })).toHaveAttribute('tabindex', '-1');
    all.focus();
    await userEvent.keyboard('{ArrowRight}');
    expect(screen.getByRole('radio', { name: /^통과/ })).toHaveFocus();
    expect(screen.getByRole('radio', { name: /^통과/ })).toHaveAttribute('aria-checked', 'true');
    await userEvent.keyboard('{ArrowLeft}{ArrowLeft}');
    expect(screen.getByRole('radio', { name: /^꺼짐/ })).toHaveAttribute('aria-checked', 'true');
  });

  test('m6 · unreadable conditions fold open with their reasons', async () => {
    setup({ [URL]: { ...makeView(), invalid: [{ condition_id: 'x1', message: "'kind' 칸이 없습니다." }] } });
    await renderC();
    await userEvent.click(screen.getByText('읽을 수 없는 조건 1개 (점검하지 않음)'));
    expect(screen.getByText("x1: 'kind' 칸이 없습니다.")).toBeVisible();
  });
});

describe('Fix round 2', () => {
  test('a stored version that cannot be computed previews without breaking the window', async () => {
    mockPreviewRoute(mockPreview({ before: { finish: null, critical_count: null, violated: 1 }, moved: [] }));
    await renderC();
    await setCrane('2');
    expect(await screen.findByText('준공 (지금 저장본은 계산할 수 없음) → 11.12 · 위반 0')).toBeVisible();
    expect(screen.getByRole('button', { name: '확정' })).toBeVisible();
    expect(preview()?.moved).toEqual([]);
  });

  test('if reloading after an applied commit fails, the window keeps the old values and says so', async () => {
    let reads = 0;
    setup({
      [URL]: () => (reads++ === 0 ? json(200, makeView()) : json(503, { code: 'unavailable', message: '서버를 잠시 쓸 수 없습니다.', detail: null })),
      [`POST ${PREVIEW}`]: respond(mockPreview()),
      [`POST ${URL}/commit`]: respond({ applied: true, approval_id: 8, version: 4 }),
    });
    await renderC();
    await setCrane('2');
    await screen.findByText(/11\.24 → 11\.12/);
    await userEvent.click(screen.getByRole('button', { name: '확정' }));
    expect(await screen.findByText('확정했습니다 · 버전 4 — 다시 불러오지 못했습니다: 서버를 잠시 쓸 수 없습니다.')).toBeVisible();
    expect(reads).toBe(2);
    expect(column('④ 입력 조건')).toBeVisible();
    expect(qty('타워크레인')).toHaveValue('1');
  });
});
