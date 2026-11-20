// 자료함 API 클라이언트와 타입.
import { api, failure, networkError, requestHeaders } from '../../shared/api';

/** 자료 분류 5개 고정 축(화면 표시 차례). */
export const AXES = ['종류', '공종', '현장', '시기', '출처'] as const;
export type AxisName = (typeof AXES)[number];

export interface FileItem {
  file_id: number;
  name: string;
  ext: string;
  kind: 'image' | 'table' | 'sheet' | 'pdf' | 'doc' | 'text' | string;
  size: number;
  status: 'received' | 'extracted' | 'indexed' | 'classified' | 'failed' | string;
  reason: string | null;
  uploaded_by: number;
  uploaded_at: string;
  pages: number | null;
  summary: string;
  deleted: boolean;
  axes: Record<string, string[]>;
}

export interface FileList {
  items: FileItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface AxisValue {
  value: string;
  count: number;
  is_new: boolean;
}

export type AxesData = Record<string, AxisValue[]>;

export interface PreviewData {
  file_id: number;
  kind: string;
  page: number;
  pages: number;
  text: string;
  truncated: boolean;
}

export interface MergeSuggestion {
  axis: string;
  from: string[];
  to: string;
  why: string;
}

export interface MergeSuggestions {
  made_at: string | null;
  items: MergeSuggestion[];
}

export interface MergeOut {
  axis: string;
  to: string;
  files: number;
}

export interface ReindexJob {
  id: number;
  model: string;
  status: 'running' | 'done' | 'failed' | string;
  total: number;
  done: number;
  started_at: string;
  finished_at: string | null;
}

export interface ReindexState {
  active_model: string;
  assigned_model: string;
  job: ReindexJob | null;
}

export type AxisFilters = Partial<Record<AxisName, string[]>>;

function buildListQuery(q: string, filters: AxisFilters, page: number): string {
  const params = new URLSearchParams();
  if (q.trim()) params.set('q', q.trim());
  for (const axis of AXES) {
    for (const val of filters[axis] ?? []) params.append(axis, val);
  }
  params.set('page', String(page));
  return `/api/files?${params.toString()}`;
}

/** 원본 바이너리(/raw)를 인증 머리글로 받아 Blob 으로 돌려준다. */
async function fetchBlob(path: string, signal?: AbortSignal): Promise<Blob> {
  const { headers, token } = requestHeaders({}, true);
  let res: Response;
  try {
    res = await fetch(path, { headers, signal });
  } catch (e) {
    if (signal?.aborted) throw e;
    throw networkError();
  }
  if (!res.ok) throw await failure(res, token);
  return res.blob();
}

export const libraryApi = {
  list: (q: string, filters: AxisFilters, page: number, signal?: AbortSignal) =>
    api<FileList>(buildListQuery(q, filters, page), { signal }),
  axes: (signal?: AbortSignal) => api<AxesData>('/api/files/axes', { signal }),
  reindex: (signal?: AbortSignal) => api<ReindexState>('/api/files/reindex', { signal }),
  mergeSuggestions: (signal?: AbortSignal) => api<MergeSuggestions>('/api/files/merge-suggestions', { signal }),
  merge: (axis: string, from: string[], to: string) =>
    api<MergeOut>('/api/files/merge', { method: 'POST', body: JSON.stringify({ axis, from, to }) }),
  preview: (fileId: number, page: number, signal?: AbortSignal) =>
    api<PreviewData>(`/api/files/${fileId}/preview?page=${page}`, { signal }),
  rawBlob: (fileId: number, signal?: AbortSignal) => fetchBlob(`/api/files/${fileId}/raw`, signal),
  patchAxes: (fileId: number, body: Record<string, string[]>) =>
    api<FileItem>(`/api/files/${fileId}/axes`, { method: 'PATCH', body: JSON.stringify(body) }),
  remove: (fileId: number, purge = false) =>
    api<void>(`/api/files/${fileId}${purge ? '?purge=true' : ''}`, { method: 'DELETE' }),
};

/** 파일이 분류됨 상태인지(summary 또는 axes 가 하나라도 있으면 분류됨). */
export function isClassified(f: FileItem): boolean {
  if (f.summary.trim().length > 0) return true;
  return Object.values(f.axes).some((vals) => vals.length > 0);
}

/** 파일 크기 표시(예: 2.1 MB, 96 KB). */
export function formatBytes(n: number): string {
  if (n >= 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  if (n >= 1024) return `${Math.round(n / 1024)} KB`;
  return `${n} B`;
}

/** 올린 날짜 표시(YYYY-MM-DD). */
export function formatDate(iso: string): string {
  return iso.slice(0, 10);
}
