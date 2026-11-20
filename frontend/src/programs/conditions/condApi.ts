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
const post = <T>(path: string, version: number, changes: Change[]) =>
  api<T>(path, { method: 'POST', body: JSON.stringify({ base_version: version, changes }) });

export const getConditions = (scheduleId: number) => api<CondView>(base(scheduleId));

export const previewConditions = (scheduleId: number, version: number, changes: Change[]) =>
  post<Preview>(`${base(scheduleId)}/preview`, version, changes);

export const commitConditions = (scheduleId: number, version: number, changes: Change[]) =>
  post<CommitResult>(`${base(scheduleId)}/commit`, version, changes);

export const askAgent = (scheduleId: number, version: number, changes: Change[]) =>
  post<{ chat_session_id: number; text: string }>(`${base(scheduleId)}/ask-agent`, version, changes);
