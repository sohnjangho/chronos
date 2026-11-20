import { api } from '../../shared/api';
import type { LlmError } from './model';

// 서비스 키는 요청 본문(JSON)에만 싣는다. 주소·기록·저장소에는 넣지 않는다.
const send = (method: string, body?: unknown): RequestInit => ({
  method,
  ...(body === undefined ? {} : { body: JSON.stringify(body) }),
});

const BASE = '/api/info/connections';

export type InfoPreset = 'kma';

/** 서버의 정보 API 연결 한 줄. 키는 끝 4자리(secret_last4)만 온다. */
export interface InfoConnection {
  id: number;
  name: string;
  preset: InfoPreset;
  base_url: string;
  secret_last4: string;
  status: 'ok' | 'failed' | 'unknown';
  checked_at: string | null;
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
}

export interface NewInfoConnection {
  name: string;
  preset: InfoPreset;
  secret: string;
}

export type InfoPatch = Partial<{ name: string; base_url: string; secret: string }>;

export const INFO_PRESETS: { value: InfoPreset; label: string }[] = [{ value: 'kma', label: '기상청(공공데이터포털)' }];

export const presetLabel = (p: InfoPreset) => INFO_PRESETS.find((x) => x.value === p)?.label ?? p;

/** 정보 API 연결(관리자만). 주소를 빼고 보내면 서버가 프리셋의 기본 주소를 쓴다. */
export const infoApi = {
  list: () => api<InfoConnection[]>(BASE),
  create: (body: NewInfoConnection) => api<InfoConnection>(BASE, send('POST', body)),
  update: (id: number, body: InfoPatch) => api<InfoConnection>(`${BASE}/${id}`, send('PATCH', body)),
  remove: (id: number) => api<void>(`${BASE}/${id}`, send('DELETE')),
  test: (id: number) => api<InfoTest>(`${BASE}/${id}/test`, send('POST')),
};
