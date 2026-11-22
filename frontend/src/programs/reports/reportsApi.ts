import { api, failure, requestHeaders } from '../../shared/api';

export type Cadence = 'monthly' | 'quarterly';
export type BlockKind = 'prose' | 'kpi' | 'table' | 'chart' | 'manual';
export type DataBinding =
  | 'summary_prose'
  | 'kpi_summary'
  | 'wbs_table'
  | 'milestone_table'
  | 's_curve_month'
  | 'spi_trend'
  | 'delay_table'
  | 'lookahead_3w'
  | 'scenario_compare'
  | 'manual_input';

export const BINDING_OPTIONS: readonly { value: DataBinding; kind: BlockKind; label: string }[] = [
  { value: 'summary_prose', kind: 'prose', label: '에이전트 공정 요약 (문장 작성)' },
  { value: 'kpi_summary', kind: 'kpi', label: '핵심 공정 지표 (KPI)' },
  { value: 'wbs_table', kind: 'table', label: 'WBS 공종별 공정률 표' },
  { value: 's_curve_month', kind: 'chart', label: '월간 공정률 S-커브 차트' },
  { value: 'spi_trend', kind: 'chart', label: '일정 수행 지수(SPI) 추이 차트' },
  { value: 'milestone_table', kind: 'table', label: '마일스톤 달성·예측 표' },
  { value: 'delay_table', kind: 'table', label: '지연 현황 및 만회 대책 표' },
  { value: 'lookahead_3w', kind: 'table', label: '예정 일정 (Lookahead) 표' },
  { value: 'scenario_compare', kind: 'table', label: '만약에 시나리오 비교 표' },
  { value: 'manual_input', kind: 'manual', label: '직접 입력' },
];

export interface TemplateSection {
  id: string;
  heading: string;
  block_kind: BlockKind;
  data_binding: DataBinding;
  table_columns: string[];
  section_prompt: string;
}

export interface StyleMemory {
  tone: string;
  date_format: string;
  number_precision: number;
  header_note: string;
  learned_rules: string[];
}

export interface ReportTemplateItem {
  id: number | null;
  builtin_key: string | null;
  schedule_id: number | NoneToUndefined;
  project_name: string | null;
  cadence: Cadence;
  name: string;
  is_default: boolean;
  is_builtin: boolean;
  source_file_id: number | null;
  source_file_name: string | null;
  sections: TemplateSection[];
  style: StyleMemory;
  created_by: string;
  updated_at: string | null;
}

type NoneToUndefined = number | null;

export interface TemplateListOut {
  current_project: ReportTemplateItem[];
  other_projects: ReportTemplateItem[];
  builtins: ReportTemplateItem[];
}

export interface TemplateLearnOut {
  suggested_name: string;
  suggested_cadence: Cadence;
  source_file_id: number;
  source_file_name: string;
  analysis_summary: string;
  sections: TemplateSection[];
  style: StyleMemory;
  saved_template: ReportTemplateItem | null;
}

export interface ReportBlock {
  id: string;
  heading: string;
  block_kind: BlockKind;
  data_binding: DataBinding;
  text: string;
  metrics: { label: string; value: string; sub?: string }[];
  table: { columns: string[]; rows: (string | number | null)[][] } | null;
  chart: {
    kind: 's_curve' | 'spi_trend';
    unit?: string;
    points: Record<string, string | number | null>[];
  } | null;
}

export interface ReportSummary {
  id: number;
  schedule_id: number;
  template_id: number | null;
  template_name: string;
  cadence: Cadence;
  period_label: string;
  title: string;
  data_date: string;
  schedule_version: number;
  status: string;
  created_by: string;
  updated_at: string;
}

export interface ReportDetail extends ReportSummary {
  blocks: ReportBlock[];
  style: StyleMemory;
}

export const listTemplates = (scheduleId: number, cadence?: Cadence) => {
  const qs = cadence ? `schedule_id=${scheduleId}&cadence=${cadence}` : `schedule_id=${scheduleId}`;
  return api<TemplateListOut>(`/api/reports/templates?${qs}`);
};

export async function uploadTemplateFile(file: File): Promise<{ file_id: number; name: string }> {
  const fd = new FormData();
  fd.append('files', file);
  const { headers, token } = requestHeaders({ method: 'POST', body: fd }, true);
  const res = await fetch('/api/files', { method: 'POST', body: fd, headers });
  if (!res.ok) throw await failure(res, token);
  const data = (await res.json()) as { items: { file_id: number; name: string; status: string; reason: string | null }[] };
  const item = data.items[0];
  if (!item) throw new Error('파일 업로드 응답이 비어 있습니다.');
  return { file_id: item.file_id, name: item.name };
}

export const learnTemplate = (body: { file_id: number; schedule_id: number; cadence?: Cadence; name?: string }) =>
  api<TemplateLearnOut>('/api/reports/templates/learn', { method: 'POST', body: JSON.stringify(body) });

export const createTemplate = (body: {
  schedule_id: number;
  cadence: Cadence;
  name: string;
  is_default: boolean;
  source_file_id: number | null;
  source_file_name: string | null;
  sections: TemplateSection[];
  style: StyleMemory;
}) => api<ReportTemplateItem>('/api/reports/templates', { method: 'POST', body: JSON.stringify(body) });

export const updateTemplate = (
  templateId: number,
  body: Partial<{ name: string; cadence: Cadence; is_default: boolean; sections: TemplateSection[]; style: StyleMemory }>,
) => api<ReportTemplateItem>(`/api/reports/templates/${templateId}`, { method: 'PATCH', body: JSON.stringify(body) });

export const adoptTemplate = (templateId: number, body: { schedule_id: number; is_default: boolean; name?: string }) =>
  api<ReportTemplateItem>(`/api/reports/templates/${templateId}/adopt`, { method: 'POST', body: JSON.stringify(body) });

export const deleteTemplate = (templateId: number) =>
  api<void>(`/api/reports/templates/${templateId}`, { method: 'DELETE' });

export const listReports = (scheduleId: number, cadence?: Cadence) =>
  api<{ items: ReportSummary[] }>(`/api/schedules/${scheduleId}/reports${cadence ? `?cadence=${cadence}` : ''}`);

export const getReport = (scheduleId: number, reportId: number) =>
  api<ReportDetail>(`/api/schedules/${scheduleId}/reports/${reportId}`);

export const generateReport = (
  scheduleId: number,
  body: { cadence: Cadence; template_id?: number | null; use_builtin?: boolean; period_label?: string; title?: string; extra_note?: string },
) => api<ReportDetail>(`/api/schedules/${scheduleId}/reports`, { method: 'POST', body: JSON.stringify(body) });

export const updateReport = (
  scheduleId: number,
  reportId: number,
  body: Partial<{ title: string; period_label: string; status: 'draft' | 'final'; blocks: ReportBlock[] }>,
) => api<ReportDetail>(`/api/schedules/${scheduleId}/reports/${reportId}`, { method: 'PATCH', body: JSON.stringify(body) });

export const regenerateReport = (
  scheduleId: number,
  reportId: number,
  body: { template_id?: number | null; use_builtin?: boolean; extra_note?: string },
) => api<ReportDetail>(`/api/schedules/${scheduleId}/reports/${reportId}/regenerate`, { method: 'POST', body: JSON.stringify(body) });

export const reviseReportBlock = (
  scheduleId: number,
  reportId: number,
  body: { block_id: string; instruction: string; remember_rule: boolean },
) => api<ReportDetail>(`/api/schedules/${scheduleId}/reports/${reportId}/revise`, { method: 'POST', body: JSON.stringify(body) });

export const deleteReport = (scheduleId: number, reportId: number) =>
  api<void>(`/api/schedules/${scheduleId}/reports/${reportId}`, { method: 'DELETE' });

export async function exportReportFile(scheduleId: number, reportId: number, format: 'html' | 'docx', filenameBase: string): Promise<void> {
  const { headers, token } = requestHeaders({ method: 'GET' }, true);
  const res = await fetch(`/api/schedules/${scheduleId}/reports/${reportId}/export?format=${format}`, { headers });
  if (!res.ok) throw await failure(res, token);

  if (format === 'html') {
    const html = await res.text();
    const win = window.open('', '_blank');
    if (win) {
      win.document.open();
      win.document.write(html);
      win.document.close();
      win.focus();
      win.print();
      return;
    }
    const blob = new Blob([html], { type: 'text/html;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${filenameBase}.html`;
    a.click();
    URL.revokeObjectURL(url);
    return;
  }

  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${filenameBase}.docx`;
  a.click();
  URL.revokeObjectURL(url);
}
