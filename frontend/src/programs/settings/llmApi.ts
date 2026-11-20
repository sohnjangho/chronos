import { api } from '../../shared/api';
import type { Assignment, Connection, ConnectionSaved, Probe, Provider } from './model';

// API 키는 요청 본문(JSON)에만 싣는다. 주소·기록·저장소에는 넣지 않는다.
const send = (method: string, body?: unknown): RequestInit => ({
  method,
  ...(body === undefined ? {} : { body: JSON.stringify(body) }),
});

const BASE = '/api/llm';

export interface NewConnection {
  name: string;
  provider: Provider;
  base_url: string;
  secret: string;
}

export interface ConnectionPatch {
  base_url?: string;
  secret?: string;
  /** true 만 받는다(다른 연결의 기본은 서버가 끈다). */
  is_default?: true;
}

export const llmApi = {
  list: () => api<Connection[]>(`${BASE}/connections`),
  /** 저장하지 않고 시험만 한다. */
  testNew: (body: Omit<NewConnection, 'name'>) => api<Probe>(`${BASE}/connections/test`, send('POST', body)),
  create: (body: NewConnection) => api<ConnectionSaved>(`${BASE}/connections`, send('POST', body)),
  update: (id: number, body: ConnectionPatch) => api<ConnectionSaved>(`${BASE}/connections/${id}`, send('PATCH', body)),
  /** 저장된 키로 다시 시험하고 결과를 연결에 적는다. */
  retest: (id: number) => api<Probe>(`${BASE}/connections/${id}/test`, send('POST')),
  models: (id: number) => api<{ models: string[] }>(`${BASE}/connections/${id}/models`),
  remove: (id: number) => api<void>(`${BASE}/connections/${id}`, send('DELETE')),
  assignments: () => api<{ items: Assignment[] }>(`${BASE}/assignments`),
  /** 한 줄만 보낸다. 서버는 보낸 쓰임새만 덮어쓰고 네 줄 전부를 돌려준다. */
  saveAssignment: (item: Assignment) => api<{ items: Assignment[] }>(`${BASE}/assignments`, send('PUT', { items: [item] })),
};
