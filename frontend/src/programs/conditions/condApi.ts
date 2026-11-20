// 조건·규칙 API(Task 18). 미리 보기는 저장하지 않는다. 확정은 서버의 승인 판단을 거친다.
import type { MovedActivity, PreviewView } from '../../os/schedulePreview';
import { api } from '../../shared/api';

export type Layer = 'base' | 'domain' | 'mine' | 'input';
export type State = 'passed' | 'violated' | 'uncheckable' | 'off';

export interface Cond {
  id: string;
  layer: Layer;
  kind: string;
  params: Record<string, unknown>;
  text: string;
  source: string;
  enabled: boolean;
  /** false: 못 바꿈 · 'toggle': 켜고 끄기만(분야 규칙, 관리자) · true: 값과 켜짐(입력 조건). */
  editable: boolean | 'toggle';
  state: State;
  message: string | null;
  overridden_by: string | null;
  /** 이 조건이 걸리는 액티비티(자원·꼬리표·마일스톤 조건만). */
  used_by: string[] | null;
  /** 근거 검색으로 붙인 출처(없으면 []). 서버가 http(s) 주소만 보낸다. */
  evidence: EvidenceRef[];
}

/** 조건을 받친 근거 하나(출처 링크). */
export interface EvidenceRef {
  id: number;
  title: string;
  url: string;
}

export interface Summary {
  passed: number;
  violated: number;
  uncheckable: number;
}

export interface CondView {
  schedule_id: number;
  name: string;
  version: number;
  layers: Record<Layer, Cond[]>;
  summary: Summary;
  /** 읽을 수 없는 저장 조건(점검하지 않음). */
  invalid: { condition_id: string; message: string }[];
  resources: { id: string; name: string; unit: string; capacity: number }[];
}

/** 있는 조건 하나 바꾸기(params 는 서버가 지금 params 에 덮어 합친다). 이 화면은 이 꼴만 보낸다. */
export interface Change {
  id: string;
  params?: Record<string, unknown>;
  enabled?: boolean;
}

/** 조건 하나 더하기(Condition dict). 이 화면은 내 규칙 목록의 [이 일정에 넣기]로만 보낸다(layer mine, source 「내 규칙」). */
export interface AddChange {
  add: Record<string, unknown> & { id: string };
}

/** 서버로 보내는 변경: 있는 조건 바꾸기 또는 더하기. 조건 칸(ConditionItem)은 바꾸기(Change)만 다룬다. */
export type AnyChange = Change | AddChange;

export const isAdd = (c: AnyChange | undefined): c is AddChange => c !== undefined && 'add' in c;

export interface Violation {
  condition_id: string;
  message: string;
  activity_ids: string[];
  amount: number | null;
}

export type Moved = MovedActivity;

/** 미리 보기의 한쪽. 저장본을 계산할 수 없으면(서버 m2) before 의 finish·critical_count 가 null 이다. */
export interface Side {
  finish: string | null;
  critical_count: number | null;
  violated: number;
}

export interface Preview {
  feasible: boolean;
  view: PreviewView;
  before: Side;
  after: Side;
  moved: Moved[];
  violations: Violation[];
  /** 미리 보기 상태의 겹(GET 과 같은 모양). */
  conditions: CondView;
}

export interface CommitResult {
  applied: boolean;
  version: number | null;
  approval_id: number;
}

const base = (scheduleId: number) => `/api/schedules/${scheduleId}/conditions`;
const post = <T>(path: string, version: number, changes: AnyChange[]) =>
  api<T>(path, { method: 'POST', body: JSON.stringify({ base_version: version, changes }) });

export const getConditions = (scheduleId: number) => api<CondView>(base(scheduleId));

export const previewConditions = (scheduleId: number, version: number, changes: AnyChange[]) =>
  post<Preview>(`${base(scheduleId)}/preview`, version, changes);

export const commitConditions = (scheduleId: number, version: number, changes: AnyChange[]) =>
  post<CommitResult>(`${base(scheduleId)}/commit`, version, changes);

export const askAgent = (scheduleId: number, version: number, changes: AnyChange[]) =>
  post<{ chat_session_id: number; text: string }>(`${base(scheduleId)}/ask-agent`, version, changes);

/** 내 규칙의 조건(Condition.to_dict 모양, layer mine, source 「내 규칙」). type 이라 Record 로 펼쳐 보낼 수 있다. */
export type RuleCondition = {
  id: string;
  layer: string;
  kind: string;
  params: Record<string, unknown>;
  text: string;
  source: string;
  enabled: boolean;
};

/** 내 규칙(Task 35) 하나. in_schedule = 이 일정 지금 조건에 같은 id 가 있는가(schedule_id 로 물었을 때만). */
export interface MyRule {
  id: number;
  scope: 'domain' | 'schedule';
  domain: string;
  schedule_id: number | null;
  condition: RuleCondition;
  enabled: boolean;
  created_by: string;
  created_at: string;
  in_schedule: boolean | null;
}

export const rulesApi = {
  list: (scheduleId: number) => api<MyRule[]>(`/api/rules?schedule_id=${scheduleId}`),
  setEnabled: (id: number, enabled: boolean) => api<MyRule>(`/api/rules/${id}`, { method: 'PATCH', body: JSON.stringify({ enabled }) }),
  remove: (id: number) => api<{ deleted: number }>(`/api/rules/${id}`, { method: 'DELETE' }),
};
