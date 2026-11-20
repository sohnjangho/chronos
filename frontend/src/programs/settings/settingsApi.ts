import type { Role } from '../../os/session';
import { api } from '../../shared/api';
import type { Account, ApprovalMode } from './model';

const json = (method: string, body: unknown): RequestInit => ({ method, body: JSON.stringify(body) });

export interface NewAccount {
  login_id: string;
  name: string;
  role: Role;
  password: string;
}

export type AccountPatch = Partial<Omit<NewAccount, 'login_id'>>;

/** 승인 수준(Task 11)과 계정(Task 1) API. */
export const settingsApi = {
  approval: () => api<{ mode: ApprovalMode }>('/api/settings/approval'),
  saveApproval: (mode: ApprovalMode) => api<{ mode: ApprovalMode }>('/api/settings/approval', json('PUT', { mode })),
  accounts: () => api<Account[]>('/api/auth/users'),
  createAccount: (body: NewAccount) => api<Account>('/api/auth/users', json('POST', body)),
  updateAccount: (id: number, body: AccountPatch) => api<Account>(`/api/auth/users/${id}`, json('PATCH', body)),
};
