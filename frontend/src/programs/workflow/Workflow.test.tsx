import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { json } from '../../test-helpers';
import manifest from './index';
import StepGraph from './StepGraph';
import Workflow from './Workflow';
import { callsTo, DONE, run, setup, step } from './testKit';

const s = (status: string) => step(1, { status });
const graph = () => screen.getByRole('list', { name: '단계 그림' });
const node = (i: number) => within(graph()).getAllByRole('button')[i];
const detailPane = () => screen.getByRole('region', { name: '단계 상세' });

async function renderWorkflow(params: Record<string, string> = { run: '12' }) {
  const view = render(<Workflow windowId="w1" params={params} />);
  await screen.findByRole('heading', { name: '골조 지연 만회 계획' });
  return view;
}

beforeEach(() => localStorage.clear());
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('지시서 시험', () => {
  test('step states map to styles', () => {
    render(<StepGraph steps={[{ ...s('done'), n: 1 }, { ...s('running'), n: 2 }, { ...s('pending'), n: 3 }]} />);
    expect(node(0)).toHaveClass('done');
    expect(node(1)).toHaveClass('running');
    expect(node(2)).toHaveClass('pending');
  });
});

describe('R6 실행 목록·단계 그림·단계 상세', () => {
  test('the run list shows status, step count and opens the run from params', async () => {
    setup();
    await renderWorkflow();
    const list = screen.getByRole('list', { name: '실행 기록' });
    const rows = within(list).getAllByRole('button');
    expect(rows.map((r) => r.textContent)).toEqual([expect.stringContaining('골조 지연 만회 계획'), expect.stringContaining('5층 사무동 공정표 생성')]);
    expect(rows[0]).toHaveTextContent('실행 중');
    expect(rows[0]).toHaveTextContent('4단계');
    expect(rows[1]).toHaveTextContent('완료');
    expect(rows[1]).toHaveTextContent('41초');
    expect(rows[0]).toHaveAttribute('aria-current', 'true');
    expect(screen.getByText('요청: "골조가 4일 밀렸어. 만회 계획 세워 줘"')).toBeVisible();
    expect(screen.queryByRole('tab', { name: /저장|스킬/ })).toBeNull();
  });

  test('without params the newest run opens and the running step is selected', async () => {
    setup();
    await renderWorkflow({});
    expect(node(3)).toHaveClass('running');
    expect(node(3)).toHaveAttribute('aria-pressed', 'true');
    expect(within(detailPane()).getByRole('heading', { name: /④ 저장 요청/ })).toBeVisible();
    expect(within(detailPane()).getByText('아직 없습니다 (진행 중)')).toBeVisible();
  });

  test('parallel steps from one answer stack in the same column', async () => {
    setup();
    await renderWorkflow();
    const left = (i: number) => node(i).closest('li')!.style.left;
    expect(left(1)).toBe(left(2));
    expect(node(2)).toHaveTextContent('동시에');
  });

  test('step detail shows tool, why, model, time and readable inputs and outputs', async () => {
    setup();
    await renderWorkflow();
    await userEvent.click(node(1));
    const pane = detailPane();
    expect(within(pane).getByRole('heading', { name: '② 조건 점검' })).toBeVisible();
    expect(within(pane).getByText('harness.check')).toBeVisible();
    expect(within(pane).getByText('두 안을 같이 점검합니다.')).toBeVisible();
    expect(within(pane).getByText('liner-fast')).toBeVisible();
    expect(within(pane).getByText('1.1초')).toBeVisible();
    const input = within(pane).getByRole('group', { name: '받은 것' });
    expect(within(input).getByText('schedule_id')).toBeVisible();
    expect(within(input).getByText('1')).toBeVisible();
    const output = within(pane).getByRole('group', { name: '돌려준 것' });
    expect(within(output).getByText('activity_count')).toBeVisible();
    expect(within(output).getByText('목록 2개')).toBeVisible();
    expect(within(output).getByText('"5층 사무동 신축"')).toBeVisible();
  });

  test('a long list in the output shows the first fifty and the rest on request', async () => {
    const big = JSON.stringify({ rows: Array.from({ length: 120 }, (_, i) => ({ id: `A${1000 + i}` })) });
    setup({ 12: run({ steps: [step(1, { output_json: big })] }) });
    await renderWorkflow();
    const output = within(detailPane()).getByRole('group', { name: '돌려준 것' });
    expect(within(output).queryAllByText(/^항목 \d+$/)).toHaveLength(0); // 접힌 묶음은 아이들을 그리지 않는다(m3)
    await userEvent.click(within(output).getByText('목록 120개'));
    expect(within(output).getAllByText(/^항목 \d+$/)).toHaveLength(50);
    await userEvent.click(within(output).getByRole('button', { name: '나머지 70개 더 보기' }));
    expect(within(output).getAllByText(/^항목 \d+$/)).toHaveLength(120);
  });

  test('a cut-off input for a non-admin says so instead of failing', async () => {
    setup({ 12: run({ steps: [step(1, { input_json: `{"text": "${'가'.repeat(1990)}` })] }) }, {}, 'user');
    await renderWorkflow();
    const input = within(detailPane()).getByRole('group', { name: '받은 것' });
    expect(within(input).getByText('앞 2,000자만 받았습니다(관리자는 전체를 봅니다).')).toBeVisible();
  });

  test('usage shows tokens and steps and — for an unknown cost', async () => {
    setup();
    await renderWorkflow();
    expect(screen.getByText('토큰 21.4K · 단계 4개 · 비용 —')).toBeVisible();
    await userEvent.click(within(screen.getByRole('list', { name: '실행 기록' })).getByRole('button', { name: /5층 사무동 공정표 생성/ }));
    expect(await screen.findByText('토큰 21.4K · 단계 2개 · 비용 $0.12')).toBeVisible();
    expect(DONE.cost).toBe(0.12);
  });

  test('the manifest opens the screen at 1400×860', () => {
    expect(manifest.defaultSize).toEqual({ w: 1400, h: 860 });
  });
});

describe('R6 실시간', () => {
  test('a running run is read again every 2 seconds and stops when it is done', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'], shouldAdvanceTime: true });
    let reads = 0;
    const done = run({ status: 'done', ended_at: new Date().toISOString(), steps: run().steps.map((x) => ({ ...x, status: 'done', ms: 300 })) });
    setup(undefined, { '/api/workflows/runs/12': () => json(200, ++reads >= 3 ? done : run()) });
    await renderWorkflow();
    expect(callsTo('/api/workflows/runs/12')).toHaveLength(1);
    await act(() => vi.advanceTimersByTimeAsync(2000));
    await waitFor(() => expect(callsTo('/api/workflows/runs/12')).toHaveLength(2));
    await act(() => vi.advanceTimersByTimeAsync(2000));
    await waitFor(() => expect(node(3)).toHaveClass('done'));
    await act(() => vi.advanceTimersByTimeAsync(6000));
    expect(callsTo('/api/workflows/runs/12')).toHaveLength(3);
  });

  test('closing the window stops the refresh', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'], shouldAdvanceTime: true });
    setup();
    const view = await renderWorkflow();
    view.unmount();
    await act(() => vi.advanceTimersByTimeAsync(6000));
    expect(callsTo('/api/workflows/runs/12')).toHaveLength(1);
  });
});

describe('Fix round 1', () => {
  test('m4: node title and tool name show in full on hover', async () => {
    setup();
    await renderWorkflow();
    expect(within(node(0)).getByText('일정 읽기')).toHaveAttribute('title', '일정 읽기');
    expect(within(node(0)).getByText('schedule.read')).toHaveAttribute('title', 'schedule.read');
  });

  test('m7: a folded group does not stay folded on the next step', async () => {
    setup();
    await renderWorkflow();
    await userEvent.click(node(0));
    const output = () => within(detailPane()).getByRole('group', { name: '돌려준 것' });
    expect(within(output()).getByText('"A1010"')).toBeVisible();
    await userEvent.click(within(output()).getByText('목록 2개'));
    expect(within(output()).queryByText('"A1010"')).toBeNull();
    await userEvent.click(node(1));
    expect(within(output()).getByText('"A1010"')).toBeVisible();
  });

  test('m9: the next read waits for the previous one to finish', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'], shouldAdvanceTime: true });
    let release!: () => void;
    let reads = 0;
    setup(undefined, {
      '/api/workflows/runs/12': () => {
        reads += 1;
        if (reads !== 2) return json(200, run());
        return new Promise<Response>((r) => (release = () => r(json(200, run()))));
      },
    });
    await renderWorkflow();
    await act(() => vi.advanceTimersByTimeAsync(2000));
    expect(reads).toBe(2);
    await act(() => vi.advanceTimersByTimeAsync(6000));
    expect(reads).toBe(2);
    await act(async () => release());
    await act(() => vi.advanceTimersByTimeAsync(2000));
    expect(reads).toBe(3);
  });

  test('waiting run shows 대기 중 badge and allows saving as skill', async () => {
    setup({ 12: run({ status: 'waiting', ended_at: null }) });
    await renderWorkflow();
    expect(screen.getAllByText('대기 중').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByRole('button', { name: '스킬로 저장' })).toBeVisible();
  });
});
