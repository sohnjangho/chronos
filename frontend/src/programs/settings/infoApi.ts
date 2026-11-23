import { api } from '../../shared/api';
import type { LlmError } from './model';

// 서비스 키는 요청 본문(JSON)에만 싣는다. 주소·기록·저장소에는 넣지 않는다.
const send = (method: string, body?: unknown): RequestInit => ({
  method,
  ...(body === undefined ? {} : { body: JSON.stringify(body) }),
});

const BASE = '/api/info/connections';

export type InfoPreset = 'kma' | 'generic';
export type KeyIn = 'query' | 'header';

/** 서버의 정보 API 연결 한 줄. 키는 끝 4자리(secret_last4)만 온다. */
export interface InfoConnection {
  id: number;
  name: string;
  preset: InfoPreset;
  base_url: string;
  secret_last4: string;
  status: 'ok' | 'failed' | 'unknown';
  checked_at: string | null;
  /** 이 API 가 무엇을 주는지(범용만, 기상청은 ""). 에이전트가 읽고 고른다. */
  description: string;
  /** 쓰는 법 메모 — 경로·필수 파라미터·예시. */
  usage: string;
  key_in: KeyIn;
  key_name: string;
  /** 연결 시험에 쓸 경로+질의. 비면 범용 연결 시험은 422 test_path_required. */
  test_path: string;
}

/** 서비스 하나의 시험 결과. */
export interface ServiceCheck {
  service: string;
  label: string;
  ok: boolean;
  latency_ms: number;
  error: LlmError | null;
}

/** 연결 시험 결과. summary 예 「단기예보 OK · ASOS 일자료 등록 안 됨」. */
export interface InfoTest {
  ok: boolean;
  summary: string;
  services: ServiceCheck[];
  /** 범용 연결 시험의 HTTP 상태. */
  http_status?: number | null;
  /** 응답 앞 300자(키 지움). */
  sample?: string | null;
}

/** 빠른 채움 한 줄(서버 templates.yaml). 키는 없다. */
export interface InfoTemplate {
  id: string;
  label: string;
  base_url: string;
  key_in: KeyIn;
  key_name: string;
  description: string;
  usage: string;
  test_path: string;
  docs_url: string;
}

/** 범용 연결에서 사람이 넣는 칸들. */
export interface GenericFields {
  base_url: string;
  description: string;
  usage: string;
  key_in: KeyIn;
  key_name: string;
  test_path: string;
}

export type NewInfoConnection = { name: string; preset: InfoPreset; secret: string } & Partial<GenericFields>;

export type InfoPatch = Partial<{ name: string; secret: string } & GenericFields>;

export const INFO_PRESETS: { value: InfoPreset; label: string }[] = [
  { value: 'kma', label: '기상청(공공데이터포털)' },
  { value: 'generic', label: '범용' },
];

export const presetLabel = (p: InfoPreset) => INFO_PRESETS.find((x) => x.value === p)?.label ?? p;

/** 정보 API 연결(관리자만). 주소를 빼고 보내면 서버가 프리셋의 기본 주소를 쓴다. */
export const infoApi = {
  list: () => api<InfoConnection[]>(BASE),
  create: (body: NewInfoConnection) => api<InfoConnection>(BASE, send('POST', body)),
  update: (id: number, body: InfoPatch) => api<InfoConnection>(`${BASE}/${id}`, send('PATCH', body)),
  remove: (id: number) => api<void>(`${BASE}/${id}`, send('DELETE')),
  test: (id: number) => api<InfoTest>(`${BASE}/${id}/test`, send('POST')),
  templates: () => api<InfoTemplate[]>('/api/info/templates'),
};
