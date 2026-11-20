// 승인함 시험 전용 도우미. 화면 코드는 이 파일을 import하지 않는다. 사람·현장은 모두 가상이다.
import { vi } from 'vitest';
import { useWindows } from '../../os/windowStore';
import { json, signInAsDemo, stubFetch } from '../../test-helpers';
import type { ApprovalDetail, ApprovalItem } from './apvApi';

export const SUMMARY = {
  finish: { before: '2027-11-28', after: '2027-11-12', delta_days: -16 },
  critical: { before_count: 7, after_count: 6, path_changed: true },
  conditions_changed: [{ id: 'in.resource_cap.crane', name: '타워크레인', before: '1대', after: '2대' }],
  changed_count: 6,
  check: { passed: 14, violations: [], uncheckable: 1, invalid: 0 },
  finish_float: { before: 2, after: 18 },
};

export const DIFF = [
  { activity_id: 'A3010', name: '외장 패널', before: { start: '2027-07-19', finish: '2027-09-05' }, after: { start: '2027-07-07', finish: '2027-08-24' }, finish_delta: -12 },
  { activity_id: 'A4030', name: '준공', before: { start: '2027-11-28', finish: '2027-11-28' }, after: { start: '2027-11-12', finish: '2027-11-12' }, finish_delta: -16 },
  { activity_id: 'A5010', name: '크레인 추가 반입', before: null, after: { start: '2027-06-01', finish: '2027-06-02' }, finish_delta: null },
];

export function item(over: Partial<ApprovalItem> = {}): ApprovalItem {
  return {
    id: 3,
    kind: 'change',
    title: '만회안 B 반영 — 크레인 2대',
    status: 'pending',
    reasons: ['finish_changed', 'critical_path_changed', 'condition_changed'],
    schedule_id: 1,
    draft_id: null,
    base_version: 3,
    version: null,
    restore_to: null,
    retry: false,
    request: '골조가 4일 밀렸어. 만회 계획 세워 줘',
    chat_session_id: 7,
    requested_by: '김하늘',
    decided_by: null,
    note: '',
    created_at: new Date(Date.now() - 120_000).toISOString(),
    decided_at: null,
    summary: SUMMARY,
    ...over,
  };
}

export const detailOf = (over: Partial<ApprovalItem> = {}, diff = DIFF): ApprovalDetail => ({ ...item(over), mode: 'important', diff });

/** 자동 적용 둘: 5 는 지금 버전(3)이라 되돌릴 수 있고, 4 는 그 뒤에 버전이 더 있다. */
export const AUTO = [
  item({ id: 5, status: 'auto', title: '실적 반영 (05.31)', reasons: [], version: 3, restore_to: 2, chat_session_id: null }),
  item({ id: 4, status: 'auto', title: '크레인 설치 2일 당김', reasons: [], version: 2, restore_to: 1, chat_session_id: null }),
];

const SCHEDULES = [{ id: 1, name: '5층 사무동 신축', domain: 'construction', level: 'L3', version: 3, finish: '2027-11-28', updated_at: '2026-11-20T01:00:00Z' }];

type Routes = Parameters<typeof stubFetch>[0];
export let fetchMock: ReturnType<typeof stubFetch>;
export let openSpy: ReturnType<typeof vi.fn>;

export interface FakeApprovals {
  rows: ApprovalItem[];
  mode: 'all' | 'important' | 'auto';
}

const GROUPS: Record<string, string[]> = { pending: ['pending'], decided: ['approved', 'rejected', 'conflict'], auto: ['auto'] };

/**
 * 가짜 승인함 서버 + 로그인(가상 사람) + 창 store 의 open 엿보기. decide 는 결정 경로의 응답을 바꾼다
 * (주지 않으면 승인·거부를 받아 상태를 바꾼다).
 */
export function setup(rows: ApprovalItem[] = [item(), ...AUTO], extra: Routes = {}, decide?: (init?: RequestInit) => Response) {
  signInAsDemo('admin');
  const state: FakeApprovals = { rows: rows.map((r) => ({ ...r })), mode: 'important' };
  const routes: Routes = { '/api/schedules': SCHEDULES };
  for (const [group, statuses] of Object.entries(GROUPS)) {
    routes[`/api/approvals?status=${group}`] = () => json(200, { mode: state.mode, items: state.rows.filter((r) => statuses.includes(r.status)) });
  }
  for (const r of state.rows) {
    routes[`/api/approvals/${r.id}`] = () => json(200, { ...state.rows.find((x) => x.id === r.id)!, mode: state.mode, diff: DIFF });
    routes[`POST /api/approvals/${r.id}/decide`] = (init?: RequestInit) => {
      if (decide) return decide(init);
      const body = JSON.parse(String(init?.body));
      const row = state.rows.find((x) => x.id === r.id)!;
      Object.assign(row, body.decision === 'approve' ? { status: 'approved', version: 4 } : { status: 'rejected', retry: body.decision === 'reject_retry' });
      row.note = body.note;
      return json(200, { status: row.status, version: row.version, schedule_id: row.schedule_id, chat_session_id: row.chat_session_id, owner_is_decider: true });
    };
  }
  routes['POST /api/schedules/1/versions/2/restore'] = () => json(200, { id: 1, version: 4 });
  fetchMock = stubFetch({ ...routes, ...extra });
  openSpy = vi.fn(() => 'w9');
  useWindows.setState({ open: openSpy, wins: [] } as never);
  return state;
}

export const callsTo = (url: string, method = 'GET') =>
  fetchMock.mock.calls.filter(([u, init]) => String(u) === url && (init?.method ?? 'GET') === method);

export const bodyOf = (url: string, method = 'POST') => callsTo(url, method).map(([, init]) => JSON.parse(String(init!.body)));
