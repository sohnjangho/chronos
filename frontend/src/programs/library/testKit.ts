// 자료함 시험 전용 도우미: 가상 자료(A현장·B현장 · 5층 사무동 신축 · 김하늘)와 가짜 파일 API.
// 화면 코드는 이 파일을 import 하지 않는다. 사람·현장·파일은 모두 가상이다.
import { vi } from 'vitest';
import type { Role } from '../../os/session';
import { json, signInAsDemo } from '../../test-helpers';
import type { AxesData, FileItem, FileList, MergeSuggestions, PreviewData, ReindexState } from './libraryApi';

/** FileOut 한 줄. axes 는 서버처럼 축 이름 가나다 차례(공종·시기·종류·출처·현장)로 둔다. */
export function file(over: Partial<FileItem> = {}): FileItem {
  return {
    file_id: 1, name: 'A현장_골조시방서.pdf', ext: 'pdf', kind: 'pdf', size: 2_200_000, status: 'classified', reason: null,
    uploaded_by: 1, uploaded_at: '2026-11-20T01:00:00Z', pages: 42, summary: '철근콘크리트 골조 시공 기준 — 거푸집 존치, 양생, 한중 콘크리트',
    deleted: false, axes: { 공종: ['골조'], 시기: ['2026-10'], 종류: ['시방서'], 출처: ['대화 첨부'], 현장: ['A현장'] },
    ...over,
  };
}

export const SPEC = file();
export const PHOTO = file({
  file_id: 2, name: '1103_타설현장.jpg', ext: 'jpg', kind: 'image', size: 840_000, pages: 1, uploaded_by: 2,
  summary: '3층 슬래브 타설 중, 펌프카 1대', axes: { 공종: ['골조'], 시기: ['2026-11'], 종류: ['현장 사진'], 출처: ['대화 첨부'], 현장: ['A현장'] },
});
export const SHEET = file({
  file_id: 3, name: '공정표_v3.xlsx', ext: 'xlsx', kind: 'sheet', size: 96_000, pages: 2, uploaded_by: 3,
  summary: '액티비티 120개, 기간 칸 없음', axes: { 공종: ['전체'], 시기: ['2027-03'], 종류: ['공정표'], 출처: ['협력사'], 현장: ['A현장'] },
});
/** 뜻 검색이 꺼져 아직 분류 전(글만 읽음). */
export const WAITING = file({
  file_id: 4, name: '1104_철근배근.jpg', ext: 'jpg', kind: 'image', status: 'extracted', reason: '뜻 검색 준비 안 됨', summary: '', axes: {},
});
/** 상태는 extracted 이지만 분류됨(요약·축 있음) — 스캔 문서. */
export const SCANNED = file({
  file_id: 5, name: '스캔_착공계.pdf', status: 'extracted', reason: '스캔 문서라 글을 읽을 수 없습니다(OCR 미지원)', summary: '착공계 스캔본',
  axes: { 종류: ['기준서'], 현장: ['C현장'] },
});
export const FILES = [SPEC, PHOTO, SHEET, WAITING, SCANNED];

const v = (value: string, count: number, is_new = false) => ({ value, count, is_new });
export const AXES: AxesData = {
  종류: [v('현장 사진', 61), v('시방서', 38), v('공정표', 9), v('기준서', 4, true)],
  공종: [v('골조', 68), v('전기', 28), v('골조공사', 3, true), v('전체', 45)],
  현장: [v('A현장', 96), v('B현장', 71), v('C현장', 31)],
  시기: [v('2026-11', 40), v('2026-10', 30), v('2027-03', 2)],
  출처: [v('대화 첨부', 120), v('협력사', 20)],
};

export const SUGGESTIONS: MergeSuggestions = {
  made_at: '2026-11-20T00:12:00Z',
  items: [
    { axis: '공종', from: ['골조공사'], to: '골조', why: '이름이 비슷합니다' },
    { axis: '종류', from: ['기준서'], to: '시방서', why: '같은 뜻으로 쓰입니다' },
  ],
};

export const NO_JOB: ReindexState = { active_model: 'openai/text-embedding-3-small', assigned_model: 'openai/text-embedding-3-small', job: null };
export const RUNNING: ReindexState = {
  active_model: 'openai/text-embedding-3-small', assigned_model: 'openai/text-embedding-3-large',
  job: { id: 4, model: 'openai/text-embedding-3-large', status: 'running', total: 5830, done: 3120, started_at: '2026-11-20T01:00:00Z', finished_at: null },
};

type Reply = { status: number; body?: unknown };
type ListFn = (params: URLSearchParams) => FileList;
interface Call {
  method: string;
  url: string;
  body: unknown;
  auth: string | null;
}

let listFn: ListFn;
let axesReply: Reply;
let reindexReply: Reply;
let suggestionsReply: Reply;
let writeQueue: Reply[];
let previewFn: (id: number, page: number) => PreviewData;
let deleted: Set<number>;
let calls: Call[];

const page = (items: FileItem[], total = items.length, p = 1): FileList => ({ items, total, page: p, page_size: 50 });

/** 목록 GET 의 응답(질의 칸을 받아 만든다). 지운 파일은 서버처럼 뺀다. */
export function mockList(fn: ListFn | FileItem[]) {
  listFn = Array.isArray(fn) ? () => page(fn) : fn;
}
export const mockAxes = (data: AxesData) => (axesReply = { status: 200, body: data });
export const mockReindex = (data: ReindexState) => (reindexReply = { status: 200, body: data });
export const mockSuggestions = (data: MergeSuggestions) => (suggestionsReply = { status: 200, body: data });
/** 다음 쓰기(PATCH·DELETE·POST merge) 하나의 응답. 없으면 PATCH 는 보낸 값으로 고친 파일, DELETE 는 204. */
export const mockWrite = (status: number, body?: unknown) => writeQueue.push({ status, body });
export function mockPreview(fn: (id: number, page: number) => Partial<PreviewData>) {
  previewFn = (id, p) => ({ file_id: id, kind: 'pdf', page: p, pages: 1, text: '', truncated: false, ...fn(id, p) });
}

function fileById(id: number): FileItem {
  return FILES.find((f) => f.file_id === id) ?? file({ file_id: id, name: `자료_${id}.pdf` });
}

function patched(id: number, body: Record<string, string[]>): FileItem {
  const f = fileById(id);
  const axes = { ...f.axes, ...body };
  return { ...f, axes: Object.fromEntries(Object.entries(axes).filter(([, vals]) => vals.length > 0)) };
}

function route(method: string, url: URL, body: unknown): Reply | Response {
  const path = url.pathname;
  const id = Number(/^\/api\/files\/(\d+)/.exec(path)?.[1]);
  if (path === '/api/files' && method === 'GET') {
    const out = listFn(url.searchParams);
    return { status: 200, body: { ...out, items: out.items.filter((f) => !deleted.has(f.file_id)) } };
  }
  if (path === '/api/files/axes') return axesReply;
  if (path === '/api/files/reindex') return reindexReply;
  if (path === '/api/files/merge-suggestions') return suggestionsReply;
  if (path === '/api/files/merge') return writeQueue.shift() ?? { status: 200, body: { ...(body as object), files: 3 } };
  if (path.endsWith('/raw')) return new Response(new Blob(['fake-bytes'], { type: 'image/jpeg' }), { status: 200 });
  if (path.endsWith('/preview')) return { status: 200, body: previewFn(id, Number(url.searchParams.get('page') ?? '1')) };
  if (method === 'PATCH') return writeQueue.shift() ?? { status: 200, body: patched(id, body as Record<string, string[]>) };
  if (method === 'DELETE') {
    const r = writeQueue.shift() ?? { status: 204 };
    if (r.status === 204) deleted.add(id);
    return r;
  }
  return { status: 404, body: { code: 'not_found', message: '찾을 수 없습니다.', detail: null } };
}

/** 로그인(기본 관리자 id 1) + 가짜 파일 API. */
export function stubLibrary({ role = 'admin', userId = 1 }: { role?: Role; userId?: number } = {}) {
  signInAsDemo(role, '김하늘', 'demo-admin', userId);
  mockList(FILES);
  axesReply = { status: 200, body: AXES };
  reindexReply = { status: 200, body: NO_JOB };
  suggestionsReply = { status: 200, body: SUGGESTIONS };
  writeQueue = [];
  mockPreview(() => ({}));
  deleted = new Set();
  calls = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://localhost');
      const method = init?.method ?? 'GET';
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ method, url: `${url.pathname}${url.search}`, body, auth: new Headers(init?.headers).get('Authorization') });
      const r = route(method, url, body);
      if (r instanceof Response) return r;
      return r.status === 204 ? new Response(null, { status: 204 }) : json(r.status, r.body);
    }),
  );
}

export const libraryCalls = () => calls;
/** 목록 GET 들의 질의 칸(보낸 차례). */
export const listQueries = () =>
  calls.filter((c) => c.method === 'GET' && c.url.startsWith('/api/files?')).map((c) => new URLSearchParams(c.url.split('?')[1]));
export const lastQuery = () => listQueries().at(-1)!;
export const writes = () => calls.filter((c) => c.method !== 'GET');
export const countGets = (path: string) => calls.filter((c) => c.method === 'GET' && c.url === path).length;

/** n 개의 가상 자료(이름 「자료_001.pdf」…). */
export function many(n: number): FileItem[] {
  return Array.from({ length: n }, (_, i) => file({ file_id: 100 + i, name: `자료_${String(i + 1).padStart(3, '0')}.pdf` }));
}

/** 쪽마다 50개씩 나누어 주는 목록. */
export function paged(items: FileItem[]): ListFn {
  return (params) => {
    const p = Number(params.get('page') ?? '1');
    return page(items.slice((p - 1) * 50, p * 50), items.length, p);
  };
}
