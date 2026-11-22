import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { useCurrentSchedule } from '../../os/currentSchedule';
import { useWindows } from '../../os/windowStore';
import { forgetSchedules, scheduleStore } from '../../shared/schedule/scheduleStore';
import { setup } from '../../shared/schedule/testKit';
import manifest from './index';
import Progress from './Progress';
import { lastUrl, mockProgress, P, progressUrls, stubProgressApi } from './testKit';

const downloadSvgImage = vi.hoisted(() => vi.fn(async () => 'png' as const));
vi.mock('../../shared/gantt/exportImage', () => ({ downloadSvgImage }));

let openSpy: ReturnType<typeof vi.fn>;

beforeEach(() => {
  localStorage.clear();
  setup();
  stubProgressApi();
  openSpy = vi.fn();
  useWindows.setState({ open: openSpy } as never);
});
afterEach(() => {
  forgetSchedules();
  useCurrentSchedule.setState({ current: null });
  localStorage.clear();
  vi.unstubAllGlobals();
  downloadSvgImage.mockClear();
});

const show = () => render(<Progress windowId="w1" params={{ id: '1' }} />);
const wbsTable = () => screen.getByRole('table', { name: 'WBS 묶음별' });

test('the manifest opens 공정률 at 1400×860 in the work group', () => {
  expect(manifest).toMatchObject({ id: 'progress', name: '공정률', kind: 'work', tone: 'rose', defaultSize: { w: 1400, h: 860 } });
});

test('kpis show plan, actual, gap and spi', async () => {
  mockProgress(P);
  show();
  expect(await screen.findByText('20.0%')).toBeVisible();
  expect(screen.getByText('10.0%')).toBeVisible();
  expect(screen.getByText('−10.0%p')).toBeVisible();
  expect(screen.getByText('0.50')).toBeVisible();
  expect(screen.getByText('1.00 이상이면 계획대로')).toBeVisible();
  expect(screen.getByText('진행 1 · 지연 2')).toBeVisible();
});

test('late status banner', async () => {
  show();
  expect(await screen.findByText(/계획보다 늦음/)).toBeVisible();
  expect(screen.getByText('준공 +1일')).toBeVisible();
  expect(screen.queryByText(/준공 여유/)).toBeNull(); // 기한이 없으면 여유도 없다
});

test('on or ahead of plan the banner says so with the deadline float', async () => {
  mockProgress({ ...P, spi: 1.05, finish: { ...P.finish, delta: 0, deadline: '2027-03-19', deadline_float: 4 } });
  show();
  expect(await screen.findByText('계획대로')).toBeVisible();
  expect(screen.queryByText(/계획보다 늦음/)).toBeNull();
  expect(screen.getByText('준공 Plan 대로')).toBeVisible();
  expect(screen.getByText('· 준공 여유 4일')).toBeVisible();
});

test('a late finish is late even when the spi is on plan', async () => {
  mockProgress({ ...P, spi: 1.05 }); // finish.delta 1
  show();
  expect(await screen.findByText('계획보다 늦음')).toBeVisible();
  expect(screen.queryByText('계획대로')).toBeNull();
  expect(screen.getByText('준공 +1일')).toBeVisible();
});

test('the toolbar shows the unit and weight mode but leaves the data date to the window header', async () => {
  mockProgress({ ...P, weight_mode: 'manual' });
  show();
  expect(await screen.findByText('가중치: 직접 입력')).toBeVisible();
  expect(screen.getByRole('button', { name: '주' })).toHaveAttribute('aria-pressed', 'true');
  const toolbar = screen.getByRole('group', { name: '공정률 도구' });
  expect(toolbar).not.toHaveTextContent('Data Date');
  expect(toolbar).not.toHaveTextContent('2027.03.03');
  expect(screen.getAllByText('Data Date')).toHaveLength(1); // 창 머리줄의 것 하나
});

test('the S-curve names the data date and both percents for screen readers', async () => {
  show();
  expect(await screen.findByRole('img', { name: /Data Date 2027\.03\.03, 계획 20\.0%, 실적 10\.0%/ })).toBeInTheDocument();
});

test('unit switch refetches by month', async () => {
  show();
  await screen.findByText('20.0%');
  await userEvent.click(screen.getByRole('button', { name: '월' }));
  expect(lastUrl()).toContain('unit=month');
  expect(screen.getByRole('button', { name: '월' })).toHaveAttribute('aria-pressed', 'true');
  expect(await screen.findByText('공정률 — 누적(선)과 월간(막대)')).toBeVisible();
});

test('a new schedule version or weight mode refetches', async () => {
  show();
  await screen.findByText('20.0%');
  const before = progressUrls().length;
  act(() => setView({ version: 2 }));
  await waitFor(() => expect(progressUrls().length).toBe(before + 1));
  act(() => setView({ weight_mode: 'manual' }));
  await waitFor(() => expect(progressUrls().length).toBe(before + 2));
});

test('milestone and wbs tables', async () => {
  show();
  expect(await screen.findByText('지연 +1일')).toBeVisible();
  expect(within(wbsTable()).getByText('−20.0')).toBeVisible();
  expect(within(wbsTable()).getByText('1 기초')).toBeVisible();
  expect(within(screen.getByRole('table', { name: '마일스톤 추적' })).getByText('03.12')).toBeVisible();
});

test('lookahead marks blocked starts', async () => {
  show();
  expect(await screen.findByText('선행 미완료: A')).toBeVisible();
  expect(screen.getByText('03.03 ~ 03.23')).toBeVisible();
});

test('buttons open the delay window and the chat', async () => {
  show();
  await userEvent.click(await screen.findByRole('button', { name: '만회 계획 요청' }));
  expect(openSpy).toHaveBeenCalledWith('chat', { ask: '지연을 만회할 계획을 만들어 줘' });
  await userEvent.click(screen.getByRole('button', { name: '지연 기록 열기' }));
  expect(openSpy).toHaveBeenCalledWith('delays', { id: '1' });
});

test('assumed data date is labeled', async () => {
  mockProgress({ ...P, data_date_assumed: true });
  show();
  expect(await screen.findByText('오늘로 가정 2027.03.03')).toBeVisible();
  expect(screen.getByText('일정에 Data Date 가 없어 오늘 날짜로 계산했습니다')).toBeVisible();
});

test('activities without a plan are noted only when there are some', async () => {
  show();
  await screen.findByText('20.0%');
  expect(screen.queryByText(/Plan 이 없는 액티비티/)).toBeNull();
  mockProgress({ ...P, added_after_plan: { count: 3, actual_pct: 12.5 } });
  await userEvent.click(screen.getByRole('button', { name: '월' }));
  expect(await screen.findByText(/Plan 이 없는 액티비티 3개/)).toBeVisible();
});

test('a server refusal is shown in Korean', async () => {
  mockProgress({ status: 422, body: { code: 'schedule_invalid', message: '선후 관계가 고리를 이룹니다.', detail: null } });
  show();
  expect(await screen.findByRole('alert')).toHaveTextContent('선후 관계가 고리를 이룹니다.');
});

test('image export draws the S-curve sheet and downloads it', async () => {
  show();
  await screen.findByText('20.0%');
  await userEvent.click(screen.getByRole('button', { name: '그림 내보내기' }));
  await waitFor(() => expect(downloadSvgImage).toHaveBeenCalledTimes(1));
  const [svg, name] = downloadSvgImage.mock.calls[0] as unknown as [SVGSVGElement, string];
  expect(name).toBe('5층 사무동 신축 v1 공정률');
  expect(svg.textContent).toContain('Data Date 03.03 · 계획 20.0% · 실적 10.0%');
});

/** 일정 저장소의 보기 몇 칸을 바꾼다(다른 창이 고치거나 가중치 방식을 바꾼 것처럼). */
function setView(over: Record<string, unknown>) {
  const store = scheduleStore(1);
  store.setState({ view: { ...store.getState().view!, ...over } });
}

test('the report visual button asks for the s_curve picture of the shown version and unit', async () => {
  show();
  await screen.findByText('20.0%');
  await userEvent.click(screen.getByRole('button', { name: '월' }));
  await waitFor(() => expect(lastUrl()).toContain('unit=month'));
  await userEvent.click(screen.getByRole('button', { name: '보고서용 그림' }));
  expect(screen.getByRole('dialog', { name: '보고서용 그림' })).toBeVisible();
  const call = vi.mocked(fetch).mock.calls.find(([u]) => String(u) === '/api/schedules/1/visuals');
  expect(JSON.parse(String(call?.[1]?.body))).toEqual({ kind: 's_curve', version: 1, unit: 'month' });
});

test('an old version on screen disables the report visual button', async () => {
  mockProgress({ ...P, version: 0 });
  show();
  await screen.findByText('20.0%');
  expect(screen.getByRole('button', { name: '보고서용 그림' })).toBeDisabled();
  expect(screen.getByText('지금 버전으로만 만들 수 있습니다')).toBeVisible();
});

test('toggles into 현장 모바일 점검 and switches among the 4 field collaboration tabs', async () => {
  const sampleField = {
    schedule_id: 1,
    schedule_name: '5층 사무동 신축',
    activities: [{ id: 'A1010', name: '1층 철근', progress: 45, rd: 3 }],
    summary: { checkin_total: 2, checkin_responded: 1, photo_total: 1, poll_total: 1, poll_feasible: 0, poll_conditional: 1, poll_infeasible: 0, handoff_total: 1, handoff_ready: 0 },
    items: [
      { id: 1, schedule_id: 1, kind: 'checkin', activity_id: 'A1010', activity_name: '1층 철근', trade: '골조팀 박반장', status: 'pending', title: '[오늘 체크인] A1010', prompt_text: '진행 회신', response_choice: null, reported_progress: 45, reported_rd: 3, response_note: '', payload_json: {}, approval_id: null, created_at: '2026-11-21T00:00:00Z', updated_at: '2026-11-21T00:00:00Z' },
    ],
  };
  const baseFetch = globalThis.fetch;
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).startsWith('/api/schedules/1/field')) {
        return Promise.resolve(
          new Response(JSON.stringify(sampleField), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          }),
        );
      }
      return baseFetch(input, init);
    }),
  );
  show();
  await screen.findByText('20.0%');
  await userEvent.click(screen.getByRole('button', { name: '현장 모바일 점검' }));
  expect(await screen.findByRole('region', { name: '현장 모바일 협업 허브' })).toBeVisible();
  expect(screen.getByText('골조팀 박반장')).toBeVisible();
  expect(screen.getByRole('tab', { name: '사진 AI 판독' })).toBeVisible();
  expect(screen.getByRole('tab', { name: '만회안 의견 조회' })).toBeVisible();
  expect(screen.getByRole('tab', { name: 'D-3 핸드오프 점검' })).toBeVisible();
  expect(screen.getByRole('button', { name: '현장 보고 제출 (저장·승인 반영)' })).toBeVisible();
  expect(screen.queryByLabelText('예상 잔여일 (RD)')).toBeNull();
  await userEvent.click(screen.getByRole('button', { name: '⚠ 지연 우려' }));
  expect(screen.getByLabelText('예상 잔여일 (RD)')).toBeVisible();
});

const widgetLayout = (container: HTMLElement) =>
  Array.from(container.querySelectorAll<HTMLElement>('[data-widget-id]')).map((el) => [
    el.dataset.widgetId,
    el.dataset.span,
  ]);

test('default widget order and spans match the dashboard layout', async () => {
  const { container } = show();
  await screen.findByText('20.0%');
  expect(widgetLayout(container)).toEqual([
    ['kpi', '12'],
    ['scurve', '8'],
    ['milestone', '4'],
    ['wbs', '3'],
    ['spi', '3'],
    ['delay', '3'],
    ['lookahead', '3'],
  ]);
});

test('edit mode reorders widgets by buttons and drag-and-drop', async () => {
  const { container } = show();
  await screen.findByText('20.0%');

  await userEvent.click(screen.getByRole('button', { name: '배치 편집' }));
  expect(screen.getByRole('region', { name: '위젯 배치 도구' })).toBeVisible();

  // S-커브를 한 칸 앞으로 이동 (kpi 와 자리 바꿈)
  await userEvent.click(screen.getByRole('button', { name: 'S-커브 앞으로 이동' }));
  expect(widgetLayout(container).slice(0, 3)).toEqual([
    ['scurve', '8'],
    ['kpi', '12'],
    ['milestone', '4'],
  ]);

  // WBS 카드를 S-커브 위치로 드래그해 맨 앞으로 이동
  const wbs = container.querySelector<HTMLElement>('[data-widget-id="wbs"]')!;
  const scurve = container.querySelector<HTMLElement>('[data-widget-id="scurve"]')!;
  fireEvent.dragStart(wbs);
  fireEvent.dragOver(scurve);
  fireEvent.drop(scurve);
  expect(widgetLayout(container)[0]).toEqual(['wbs', '3']);
});

test('widget width, visibility toggle and order persist across remount', async () => {
  const first = show();
  await screen.findByText('20.0%');

  await userEvent.click(screen.getByRole('button', { name: '배치 편집' }));
  await userEvent.click(within(screen.getByRole('group', { name: '마일스톤 너비' })).getByRole('button', { name: '1/2' }));
  expect(first.container.querySelector('[data-widget-id="milestone"]')).toHaveAttribute('data-span', '6');

  await userEvent.click(screen.getByRole('button', { name: '마일스톤 숨기기' }));
  expect(first.container.querySelector('[data-widget-id="milestone"]')).toBeNull();

  await userEvent.click(screen.getByRole('button', { name: 'S-커브 앞으로 이동' }));
  await userEvent.click(screen.getByRole('button', { name: '편집 완료' }));
  expect(screen.getByRole('button', { name: '배치 편집 (숨김 1)' })).toBeVisible();
  first.unmount();

  // 다시 열어도 숨김 · 너비 · 순서가 유지된다.
  const second = show();
  await screen.findByText('20.0%');
  expect(second.container.querySelector('[data-widget-id="milestone"]')).toBeNull();
  expect(screen.getByRole('button', { name: '배치 편집 (숨김 1)' })).toBeVisible();
  expect(widgetLayout(second.container)[0]).toEqual(['scurve', '8']);

  // 숨긴 위젯을 배치 도구에서 다시 켠다(바뀐 너비 1/2=6 유지).
  await userEvent.click(screen.getByRole('button', { name: '배치 편집 (숨김 1)' }));
  await userEvent.click(screen.getByRole('button', { name: /\+ 마일스톤/ }));
  expect(second.container.querySelector('[data-widget-id="milestone"]')).toHaveAttribute('data-span', '6');
});

test('reset restores default order, spans and visibility even when all widgets were hidden', async () => {
  const { container } = show();
  await screen.findByText('20.0%');

  await userEvent.click(screen.getByRole('button', { name: '배치 편집' }));
  for (const label of ['요약 KPI', 'S-커브', '마일스톤', 'WBS', 'SPI 추이', '지연 상위', '앞으로 3주']) {
    await userEvent.click(screen.getByRole('button', { name: `${label} 숨기기` }));
  }
  expect(screen.getByText('표시된 위젯이 없습니다.')).toBeVisible();

  await userEvent.click(screen.getAllByRole('button', { name: '기본 배치 복원' })[0]);
  expect(widgetLayout(container)).toEqual([
    ['kpi', '12'],
    ['scurve', '8'],
    ['milestone', '4'],
    ['wbs', '3'],
    ['spi', '3'],
    ['delay', '3'],
    ['lookahead', '3'],
  ]);
});
