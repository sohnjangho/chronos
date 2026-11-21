import type { Role, User } from '../../os/session';
import { api } from '../../shared/api';
import type { Account, ApprovalMode, ReindexState } from './model';

const json = (method: string, body: unknown): RequestInit => ({ method, body: JSON.stringify(body) });

export interface NewAccount {
  login_id: string;
  name: string;
  role: Role;
  password: string;
}

export type AccountPatch = Partial<Omit<NewAccount, 'login_id'>>;
export type MePatch = { name?: string; password?: string };

/** 승인 수준(Task 11)·계정(Task 1)·내 정보 수정·임베딩 다시 넣기(Task 48) API. */
export const settingsApi = {
  approval: () => api<{ mode: ApprovalMode }>('/api/settings/approval'),
  saveApproval: (mode: ApprovalMode) => api<{ mode: ApprovalMode }>('/api/settings/approval', json('PUT', { mode })),
  updateMe: (body: MePatch) => api<User>('/api/auth/me', json('PATCH', body)),
  accounts: () => api<Account[]>('/api/auth/users'),
  createAccount: (body: NewAccount) => api<Account>('/api/auth/users', json('POST', body)),
  updateAccount: (id: number, body: AccountPatch) => api<Account>(`/api/auth/users/${id}`, json('PATCH', body)),
  reindex: () => api<ReindexState>('/api/files/reindex'),
  /** 배정한 임베딩 모델로 다시 넣기를 (다시) 시작한다. 409 이미 하는 중·할 것 없음, 503 뜻 검색 서버 꺼짐. */
  restartReindex: () => api<{ job_id: number; total: number }>('/api/files/reindex', { method: 'POST' }),
};
