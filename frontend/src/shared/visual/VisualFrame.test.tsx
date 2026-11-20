// 보고서용 그림(Task 44): Liner HTML 은 sandbox iframe(allow-same-origin 없음), 실패·CDN 실패는 우리 그림(SVG) + 까닭.
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { json, signInAsDemo, stubFetch } from '../../test-helpers';
import VisualFrame, { VisualButton, VisualPanel } from './VisualFrame';
import type { VisualData } from './visualApi';

const HTML = '<!DOCTYPE html><html><head><title>t</title></head><body><canvas></canvas></body></html>';
const V: VisualData = {
  id: 7, schedule_id: 1, kind: 'summary', title: '일정 요약 — 크리티컬 패스 작업', version: 3, data_date: '2027-03-01',
  columns: ['작업', '시작', '끝'], rows: [['터파기', '2027-03-01', '2027-03-05'], ['기초 타설', '2027-03-08', '2027-03-19']],
  chart: 'timeline', html: HTML, theme: 'summary', description: '요약', resource_id: 'viz_1', verified: true, passed: 6,
  total: 6, fallback: false, note: '', table_note: '', external: ['https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js'],
  latency_ms: 11000, created_at: '2026-11-20T10:00:00',
};
const FALLBACK: VisualData = { ...V, html: null, verified: false, passed: 5, fallback: true, note: 'Liner 그림 검증 실패 → 기본 그림' };

beforeEach(() => signInAsDemo());
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

const frame = () => document.querySelector('iframe') as HTMLIFrameElement;
const tell = (data: unknown, source: MessageEventSource | null) =>
  act(() => {
    window.dispatchEvent(new MessageEvent('message', { data, source }));
  });

describe('frame', () => {
  test('verified html goes into a sandboxed iframe with the caption', () => {
    render(<VisualFrame data={V} />);
    const f = frame();
    expect(f).toHaveAttribute('sandbox', 'allow-scripts');
    expect(f.getAttribute('srcdoc')).toContain('<canvas></canvas>');
    expect(f.getAttribute('srcdoc')).toContain('chronosVisual');
    const doc = f.getAttribute('srcdoc') ?? '';
    expect(doc).toMatch(/<meta http-equiv="Content-Security-Policy" content="[^"]*connect-src 'none'[^"]*">/);
    expect(doc).toContain('img-src data:');
    // 서버가 대조한 외부 주소(external)의 패키지 폴더만 허용한다(호스트 전체가 아니라).
    expect(doc).toContain("script-src 'unsafe-inline' https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/;");
    expect(doc).not.toContain('https://cdn.jsdelivr.net');
    expect(doc.indexOf('Content-Security-Policy')).toBeLessThan(doc.indexOf('chronosVisual'));
    expect(doc).toContain('afterRender'); // 차트가 실제로 그려진 뒤에 ready
    // 요소의 load 는 window 까지 오지 않는다(DOM 명세) — Chart.js 를 부른 때는 document 에서 잡는다(실제 Chrome 에서 확인).
    expect(doc).toContain('document.addEventListener("load"');
    expect(f).toHaveAttribute('title', '일정 요약 — 크리티컬 패스 작업');
    expect(screen.getByText('데이터: 크로노스 계산(버전 v3, 기준일 2027-03-01) · 그림: Liner Visualization · 숫자 대조 통과 6/6')).toBeVisible();
  });

  test('csp sources are the allowed package folders of the checked external urls', () => {
    const external = [
      'https://cdn.jsdelivr.net/npm/@liner-fe/design-token@^3.0.0/lib/index.css',
      'https://cdn.jsdelivr.net/npm/pretendard@1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.css',
      'https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js',
      'https://evil.example/x.js',
    ];
    render(<VisualFrame data={{ ...V, external }} />);
    const doc = frame().getAttribute('srcdoc') ?? '';
    const sources = 'https://cdn.jsdelivr.net/npm/@liner-fe/design-token@^3.0.0/ https://cdn.jsdelivr.net/npm/pretendard@1.3.9/ https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/';
    expect(doc).toContain(`style-src 'unsafe-inline' ${sources};`);
    expect(doc).toContain(`font-src ${sources};`);
    expect(doc).not.toContain('evil.example');
  });

  test('without a head the csp goes first, not inside a <header>', () => {
    render(<VisualFrame data={{ ...V, html: '<html><body><header>머리</header><canvas></canvas></body></html>' }} />);
    const doc = frame().getAttribute('srcdoc') ?? '';
    expect(doc.startsWith('<meta http-equiv="Content-Security-Policy"')).toBe(true);
    expect(doc.indexOf('Content-Security-Policy')).toBeLessThan(doc.indexOf('<header>'));
  });

  test('the caption carries the table note', () => {
    render(<VisualFrame data={{ ...V, table_note: '점이 많아 월 단위로 그렸습니다' }} />);
    expect(screen.getByText(/숫자 대조 통과 6\/6 · 점이 많아 월 단위로 그렸습니다/)).toBeVisible();
  });

  test('fallback draws our svg with the reason and no iframe', () => {
    render(<VisualFrame data={FALLBACK} />);
    expect(frame()).toBeNull();
    expect(screen.getByRole('img', { name: '일정 요약 — 크리티컬 패스 작업 (기본 그림)' })).toBeVisible();
    expect(screen.getByText('Liner 그림 검증 실패 → 기본 그림')).toBeVisible();
    expect(screen.getByText('데이터: 크로노스 계산(버전 v3, 기준일 2027-03-01) · 그림: 크로노스 기본 그림')).toBeVisible();
  });

  test('a cdn failure inside the frame switches to our svg', () => {
    render(<VisualFrame data={V} />);
    tell({ chronosVisual: 'cdn' }, null); // 다른 곳에서 온 알림은 무시
    expect(frame()).not.toBeNull();
    tell({ chronosVisual: 'cdn' }, frame().contentWindow);
    expect(frame()).toBeNull();
    expect(screen.getByText('그림 파일(CDN)을 불러오지 못해 기본 그림으로 보입니다.')).toBeVisible();
    expect(screen.getByRole('img', { name: /기본 그림/ })).toBeVisible();
  });

  test('a script error inside the frame switches to our svg', () => {
    render(<VisualFrame data={V} />);
    tell({ chronosVisual: 'error' }, frame().contentWindow);
    expect(frame()).toBeNull();
    expect(screen.getByText('그림을 그리다 오류가 나 기본 그림으로 보입니다.')).toBeVisible();
  });

  test('the table is behind a fold', async () => {
    render(<VisualFrame data={V} />);
    await userEvent.click(screen.getByText('표 보기'));
    const table = screen.getByRole('table', { name: '그림의 표' });
    expect(within(table).getByText('기초 타설')).toBeVisible();
    expect(within(table).getByText('2027-03-19')).toBeVisible();
  });

  test.each([
    ['bars', ['작업', '지연(근무일)', '흡수(근무일)'], [['터파기', 3, 1], ['기초 타설', -2, 0]], 4],
    ['line', ['날짜', '계획 누적(%)', '실적 누적(%)'], [['2027-03-01', 10, 5], ['2027-03-08', 20, null]], 2],
    ['timeline', ['작업', '시작', '끝'], [['터파기', '2027-03-01', '2027-03-05']], 1],
  ] as const)('%s fallback draws one mark per value', (chart, columns, rows, marks) => {
    render(<VisualFrame data={{ ...FALLBACK, chart, columns: [...columns], rows: rows.map((r) => [...r]) }} />);
    expect(document.querySelectorAll('.vf-mark')).toHaveLength(marks);
  });
});

describe('panel and button', () => {
  test('the button makes the visual and shows it in a dialog', async () => {
    const fetchSpy = stubFetch({ 'POST /api/schedules/1/visuals': V });
    render(<VisualButton scheduleId={1} kind="delay_impact" />);
    await userEvent.click(screen.getByRole('button', { name: '보고서용 그림' }));
    const dialog = screen.getByRole('dialog', { name: '보고서용 그림' });
    await waitFor(() => expect(frame()).not.toBeNull());
    expect(JSON.parse(String(fetchSpy.mock.calls[0][1]?.body))).toEqual({ kind: 'delay_impact' });
    expect(within(dialog).getByText('그림 만드는 중…')).toBeVisible(); // iframe 이 다 그렸다고 알릴 때까지
    tell({ chronosVisual: 'ready' }, frame().contentWindow);
    expect(within(dialog).queryByText('그림 만드는 중…')).toBeNull();
    await userEvent.click(within(dialog).getByRole('button', { name: '닫기' }));
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  test('the button sends version and unit, and can be disabled with a reason', async () => {
    const fetchSpy = stubFetch({ 'POST /api/schedules/1/visuals': V });
    const { rerender } = render(<VisualButton scheduleId={1} kind="s_curve" version={3} unit="month" />);
    await userEvent.click(screen.getByRole('button', { name: '보고서용 그림' }));
    expect(JSON.parse(String(fetchSpy.mock.calls[0][1]?.body))).toEqual({ kind: 's_curve', version: 3, unit: 'month' });
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
    rerender(<VisualButton scheduleId={1} kind="s_curve" disabledReason="지금 버전으로만 만들 수 있습니다" />);
    expect(screen.getByRole('button', { name: '보고서용 그림' })).toBeDisabled();
    expect(screen.getByText('지금 버전으로만 만들 수 있습니다')).toBeVisible();
  });

  test('escape closes the dialog', async () => {
    stubFetch({ 'POST /api/schedules/1/visuals': V });
    render(<VisualButton scheduleId={1} kind="summary" />);
    await userEvent.click(screen.getByRole('button', { name: '보고서용 그림' }));
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  test('server errors are shown', async () => {
    stubFetch({ 'POST /api/schedules/1/visuals': () => json(422, { code: 'no_data', message: '기록한 지연이 없습니다.', detail: null }) });
    render(<VisualPanel load={() => import('./visualApi').then((m) => m.makeVisual(1, 'delay_impact'))} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('기록한 지연이 없습니다.');
  });

  test('a response that is not a visual is an error, not a crash', async () => {
    render(<VisualPanel load={() => Promise.resolve({ id: 1, name: '일정' } as never)} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('그림 응답을 읽을 수 없습니다.');
  });

  test('after 30 seconds the placeholder offers a retry', async () => {
    vi.useFakeTimers();
    let resolve: (v: VisualData) => void = () => {};
    const load = vi.fn(() => new Promise<VisualData>((r) => (resolve = r)));
    render(<VisualPanel load={load} />);
    expect(screen.getByText('그림 만드는 중…')).toBeVisible();
    act(() => vi.advanceTimersByTime(30_000));
    expect(screen.getByRole('alert')).toHaveTextContent('30초 안에 그림이 오지 않았습니다.');
    fireEvent.click(screen.getByRole('button', { name: '다시 불러오기' }));
    expect(load).toHaveBeenCalledTimes(2);
    await act(async () => resolve(V));
    expect(frame()).not.toBeNull();
  });

  test('a frame that never says ready falls back after 30 seconds', async () => {
    vi.useFakeTimers();
    render(<VisualPanel load={() => Promise.resolve(V)} />);
    await act(async () => {});
    expect(frame()).not.toBeNull();
    act(() => vi.advanceTimersByTime(30_000));
    expect(frame()).toBeNull();
    expect(screen.getByText('그림이 30초 안에 그려지지 않아 기본 그림으로 보입니다.')).toBeVisible();
  });
});
