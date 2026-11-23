import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { useCurrentSchedule } from '../../os/currentSchedule';
import { useWindows } from '../../os/windowStore';
import { forgetSchedules } from '../../shared/schedule/scheduleStore';
import { setup } from '../../shared/schedule/testKit';
import { json } from '../../test-helpers';
import manifest from './index';
import Reports from './Reports';

const SAMPLE_TPL_CURRENT = {
  id: 11,
  builtin_key: null,
  schedule_id: 1,
  project_name: '5층 사무동 신축',
  cadence: 'monthly',
  name: '발주처 월간 양식',
  is_default: true,
  is_builtin: false,
  source_file_id: 50,
  source_file_name: 'monthly.docx',
  sections: [
    { id: 's1', heading: '1. 요약', block_kind: 'prose', data_binding: 'summary_prose', table_columns: [], section_prompt: '' },
    { id: 's2', heading: '2. WBS 현황', block_kind: 'table', data_binding: 'wbs_table', table_columns: ['WBS', '계획', '실적'], section_prompt: '' },
  ],
  style: { tone: '~습니다', date_format: 'YYYY.MM.DD', number_precision: 1, header_note: '', learned_rules: ['첫 줄에 SPI 표기'] },
  created_by: '손장호',
  updated_at: '2026-11-22T09:00:00Z',
};

const SAMPLE_TPL_OTHER = {
  ...SAMPLE_TPL_CURRENT,
  id: 22,
  schedule_id: 2,
  project_name: '배터리 파일럿 라인',
  cadence: 'quarterly',
  name: '배터리 분기 보고 양식',
  is_default: true,
};

const SAMPLE_REPORT = {
  id: 101,
  schedule_id: 1,
  template_id: 11,
  template_name: '발주처 월간 양식',
  cadence: 'monthly',
  period_label: '2027년 6월',
  title: '월간 공정 보고서 — 5층 사무동 신축 (2027년 6월)',
  data_date: '2027.06.01',
  schedule_version: 1,
  status: 'draft',
  created_by: '손장호',
  updated_at: '2026-11-22T09:05:00Z',
  blocks: [
    {
      id: 's1',
      heading: '1. 요약',
      block_kind: 'prose',
      data_binding: 'summary_prose',
      text: '실적 공정률 28.1%, SPI 0.92입니다.',
      metrics: [],
      table: null,
      chart: null,
    },
    {
      id: 's2',
      heading: '2. WBS 현황',
      block_kind: 'table',
      data_binding: 'wbs_table',
      text: '',
      metrics: [],
      table: { columns: ['WBS', '계획', '실적'], rows: [['1 기초', '100.0', '100.0']] },
      chart: null,
    },
  ],
  style: SAMPLE_TPL_CURRENT.style,
};

function stubReportsFetch(report: typeof SAMPLE_REPORT = SAMPLE_REPORT) {
  let current = [SAMPLE_TPL_CURRENT];
  let reports = [{ ...report }];
  let detail = { ...report };
  const baseFetch = globalThis.fetch;

  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method ?? 'GET').toUpperCase();

    if (url.startsWith('/api/reports/templates?')) {
      return json(200, {
        current_project: current,
        other_projects: [SAMPLE_TPL_OTHER],
        builtins: [
          { ...SAMPLE_TPL_CURRENT, id: null, builtin_key: 'monthly', schedule_id: null, project_name: null, name: '기본 월간 공정 보고서', is_default: false, is_builtin: true },
          { ...SAMPLE_TPL_OTHER, id: null, builtin_key: 'quarterly', schedule_id: null, project_name: null, name: '기본 분기별 공정 보고서', is_default: false, is_builtin: true },
        ],
      });
    }
    if (url === '/api/files' && method === 'POST') {
      return json(200, { items: [{ file_id: 99, name: 'sample.md', kind: 'text', status: 'extracted', reason: null }] });
    }
    if (url === '/api/reports/templates/learn' && method === 'POST') {
      return json(200, {
        suggested_name: '신규 학습 월간 양식',
        suggested_cadence: 'monthly',
        source_file_id: 99,
        source_file_name: 'sample.md',
        analysis_summary: '항목 2개를 추출했습니다.',
        sections: SAMPLE_TPL_CURRENT.sections,
        style: SAMPLE_TPL_CURRENT.style,
        saved_template: null,
      });
    }
    if (url === '/api/reports/templates' && method === 'POST') {
      const body = JSON.parse(String(init?.body));
      const created = { ...SAMPLE_TPL_CURRENT, id: 77, name: body.name, cadence: body.cadence, sections: body.sections, style: body.style };
      current = [created, ...current];
      return json(200, created);
    }
    if (url === '/api/reports/templates/22/adopt' && method === 'POST') {
      const cloned = { ...SAMPLE_TPL_OTHER, id: 88, schedule_id: 1, project_name: '5층 사무동 신축' };
      current = [...current, cloned];
      return json(200, cloned);
    }
    if (url === '/api/schedules/1/reports' && method === 'GET') {
      return json(200, { items: reports });
    }
    if (url === '/api/schedules/1/reports' && method === 'POST') {
      const body = JSON.parse(String(init?.body));
      const created = {
        ...SAMPLE_REPORT,
        id: 202,
        cadence: body.cadence,
        period_label: body.period_label ?? (body.cadence === 'quarterly' ? '2027년 3분기' : '2027년 6월'),
        title: body.cadence === 'quarterly' ? '분기별 공정 보고서 — 5층 사무동 신축' : '신규 월간 보고서',
      };
      reports = [created, ...reports];
      detail = created;
      return json(200, created);
    }
    if (url === '/api/schedules/1/reports/101/regenerate' && method === 'POST') {
      detail = { ...report, blocks: report.blocks.map((blk) => ({ ...blk, auto_text: false, text: 'AI 가 다시 쓴 문단입니다.' })) };
      return json(200, detail);
    }
    if (url.startsWith('/api/schedules/1/reports/') && method === 'GET') {
      return json(200, detail);
    }
    return baseFetch(input, init);
  });

  vi.stubGlobal('fetch', fn);
  return fn;
}

beforeEach(() => {
  localStorage.clear();
  setup();
  useWindows.setState({ open: vi.fn() } as never);
});

afterEach(() => {
  forgetSchedules();
  useCurrentSchedule.setState({ current: null });
  localStorage.clear();
  vi.unstubAllGlobals();
});

test('manifest registers 보고서 in work group with emerald tone', () => {
  expect(manifest).toMatchObject({ id: 'reports', name: '보고서', tone: 'emerald', kind: 'work', defaultSize: { w: 1400, h: 860 } });
});

test('shows current project templates, other project templates, report sheet, and adopts cross-project template', async () => {
  const fetchMock = stubReportsFetch();
  render(<Reports windowId="w1" params={{ id: '1' }} />);

  const sidebar = await screen.findByRole('complementary', { name: '보고서와 양식 목록' });
  expect(await screen.findByText('실적 공정률 28.1%, SPI 0.92입니다.')).toBeVisible();
  expect(within(sidebar).getByText('발주처 월간 양식')).toBeVisible();
  expect(within(sidebar).getByText('배터리 분기 보고 양식')).toBeVisible();
  expect(within(sidebar).getByText('기본 월간 공정 보고서')).toBeVisible();
  expect(within(sidebar).getByText('기본 분기별 공정 보고서')).toBeVisible();

  // 다른 프로젝트 양식 클릭 -> 복사·기억 배너 및 버튼 표시
  await userEvent.click(within(sidebar).getByRole('button', { name: /배터리 분기 보고 양식/ }));
  expect(await screen.findByText(/다른 프로젝트\(배터리 파일럿 라인\)에서 학습된 양식/)).toBeVisible();
  await userEvent.click(screen.getByRole('button', { name: '이 프로젝트 양식으로 복사·기억' }));
  await waitFor(() =>
    expect(fetchMock.mock.calls.some(([u, init]) => String(u) === '/api/reports/templates/22/adopt' && init?.method === 'POST')).toBe(true),
  );
});

test('uploads template file, learns sections, saves for project, and generates quarterly report', async () => {
  const fetchMock = stubReportsFetch();
  render(<Reports windowId="w1" params={{ id: '1' }} />);
  const sidebar = await screen.findByRole('complementary', { name: '보고서와 양식 목록' });
  await within(sidebar).findByText('발주처 월간 양식');

  await userEvent.click(screen.getByRole('button', { name: '+ 양식 등록 (파일 올리기)' }));
  const file = new File(['# 1. 요약\n보고합니다.'], 'sample.md', { type: 'text/markdown' });
  await userEvent.upload(screen.getByLabelText('양식 파일 선택'), file);
  await userEvent.click(screen.getByRole('button', { name: '양식 분석 · 학습' }));

  expect(await screen.findByText(/항목 2개를 추출했습니다/)).toBeVisible();
  await userEvent.click(screen.getByRole('button', { name: '이 프로젝트에 양식 기억' }));
  await waitFor(() =>
    expect(fetchMock.mock.calls.some(([u, init]) => String(u) === '/api/reports/templates' && init?.method === 'POST')).toBe(true),
  );

  // 분기별 보고서 생성 (일간 버튼 없음)
  await userEvent.click(screen.getByRole('button', { name: '+ 보고서 만들기' }));
  const creator = screen.getByRole('region', { name: '새 보고서 설정' });
  expect(within(creator).queryByRole('button', { name: /일간/ })).toBeNull();
  await userEvent.click(within(creator).getByRole('button', { name: '분기별 보고서' }));
  await userEvent.click(within(creator).getByRole('button', { name: '작성 시작' }));

  expect(await screen.findByDisplayValue('분기별 공정 보고서 — 5층 사무동 신축')).toBeVisible();
});

test('auto-made prose shows a notice with 다시 만들기, plain AI prose does not (R4)', async () => {
  const auto = {
    ...SAMPLE_REPORT,
    blocks: SAMPLE_REPORT.blocks.map((blk) => (blk.block_kind === 'prose' ? { ...blk, auto_text: true } : blk)),
  };
  const fetchMock = stubReportsFetch(auto);
  render(<Reports windowId="w1" params={{ id: '1' }} />);

  const note = await screen.findByRole('note', { name: '1. 요약 자동 문안 안내' });
  expect(note).toHaveTextContent('AI 서술을 받지 못해 자동 문안으로 채웠습니다');
  await userEvent.click(within(note).getByRole('button', { name: '다시 만들기' }));
  await waitFor(() =>
    expect(
      fetchMock.mock.calls.some(([u, init]) => String(u) === '/api/schedules/1/reports/101/regenerate' && init?.method === 'POST'),
    ).toBe(true),
  );
  expect(await screen.findByText('AI 가 다시 쓴 문단입니다.')).toBeVisible();
  expect(screen.queryByRole('note', { name: '1. 요약 자동 문안 안내' })).toBeNull();
});

test('editing auto-made prose by hand drops the notice (R4)', async () => {
  const auto = {
    ...SAMPLE_REPORT,
    blocks: SAMPLE_REPORT.blocks.map((blk) => (blk.block_kind === 'prose' ? { ...blk, auto_text: true } : blk)),
  };
  stubReportsFetch(auto);
  render(<Reports windowId="w1" params={{ id: '1' }} />);
  await screen.findByRole('note', { name: '1. 요약 자동 문안 안내' });
  await userEvent.type(screen.getByLabelText('1. 요약 본문'), ' 보탬');
  expect(screen.queryByRole('note', { name: '1. 요약 자동 문안 안내' })).toBeNull();
});

test('AI-written prose has no auto-text notice (R4)', async () => {
  stubReportsFetch();
  render(<Reports windowId="w1" params={{ id: '1' }} />);
  await screen.findByText('실적 공정률 28.1%, SPI 0.92입니다.');
  expect(screen.queryByRole('note', { name: /자동 문안 안내/ })).toBeNull();
});
