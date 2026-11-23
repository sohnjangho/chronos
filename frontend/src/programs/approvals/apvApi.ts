// 승인함 API(Task 11)와 화면 글. 모양은 서버 ApprovalOut·ApprovalDetail·DecideOut 그대로다.
import { api } from '../../shared/api';

export type Json = Record<string, unknown>;
export type Group = 'pending' | 'decided' | 'auto';
export type Mode = 'all' | 'important' | 'auto';
export type Status = 'pending' | 'approved' | 'rejected' | 'conflict' | 'auto';
export type Decision = 'approve' | 'reject' | 'reject_retry';

export interface ApprovalItem {
  id: number;
  /** rule = 분야 범위 내 규칙 저장(일정 없음, summary.rule). 일정 범위 규칙은 change(link_kind rule). */
  kind: 'first_save' | 'change' | 'rule';
  title: string;
  status: Status;
  reasons: string[];
  schedule_id: number | null;
  draft_id: number | null;
  base_version: number;
  version: number | null;
  restore_to: number | null;
  retry: boolean;
  request: string;
  chat_session_id: number | null;
  requested_by: string;
  decided_by: string | null;
  note: string;
  created_at: string;
  decided_at: string | null;
  /** summary_json(준공·크리티컬·조건 변화·점검·기한 여유). 칸이 빠져 있어도 그릴 수 있어야 한다. */
  summary: Json;
}

export interface DiffSide {
  start: string;
  finish: string;
}

export interface DiffRow {
  activity_id: string;
  name: string;
  before: DiffSide | null;
  after: DiffSide | null;
  finish_delta: number | null;
}

export interface ApprovalDetail extends ApprovalItem {
  mode: Mode;
  diff: DiffRow[];
  /** 반영할 수 없는 까닭(예전 방식 사진 판독에서 나온 건). 있으면 서버가 승인을 막는다(422) — 거부는 된다. */
  blocked?: string | null;
}

export interface DecideOut {
  status: 'approved' | 'rejected';
  version: number | null;
  schedule_id: number | null;
  chat_session_id: number | null;
  owner_is_decider: boolean;
}

export interface ScheduleItem {
  id: number;
  name: string;
  version: number;
}

const post = (body: unknown): RequestInit => ({ method: 'POST', body: JSON.stringify(body) });

export const apvApi = {
  list: (group: Group) => api<{ mode: Mode; items: ApprovalItem[] }>(`/api/approvals?status=${group}`),
  detail: (id: number) => api<ApprovalDetail>(`/api/approvals/${id}`),
  decide: (id: number, decision: Decision, note: string) => api<DecideOut>(`/api/approvals/${id}/decide`, post({ decision, note })),
  /** 일정 이름과 지금 버전(자동 적용 되돌리기 판단). */
  schedules: () => api<ScheduleItem[]>('/api/schedules'),
  /** n번 버전의 내용으로 새 버전(Task 4). 돌려받는 것은 새 버전의 일정 보기. */
  restore: (scheduleId: number, n: number, base: number) =>
    api<{ version: number }>(`/api/schedules/${scheduleId}/versions/${n}/restore`, post({ base_version: base })),
};

const REASONS: Record<string, string> = {
  finish_changed: '준공일',
  critical_path_changed: '크리티컬 패스',
  condition_changed: '조건 변경',
  first_save: '새 일정의 첫 저장',
  structure_changed: '구조 변경',
  milestone_changed: '주요 날짜',
  condition_violated: '조건 위반',
  plan_reset: 'Plan 다시 잡기',
  rule_save: '내 규칙 저장',
};
export const reasonLabel = (r: string) => REASONS[r] ?? r;

export const MODES: Record<Mode, string> = { all: '모두 승인', important: '중요한 것만', auto: '자동' };

export const STATUS: Record<Status, string> = { pending: '대기', approved: '승인됨', rejected: '거부됨', conflict: '충돌', auto: '자동 적용' };

export const groupOf = (s: Status): Group => (s === 'pending' ? 'pending' : s === 'auto' ? 'auto' : 'decided');
