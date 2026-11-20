// 일정 API(Task 4). 쓰기는 모두 base_version 을 보내고, 성공하면 새 ScheduleView 전체를 돌려받는다.
import { api } from '../api';

export type Kind = 'task' | 'start_ms' | 'finish_ms';
export type RelType = 'FS' | 'SS' | 'FF' | 'SF';

export interface Constraint {
  type: 'SNET' | 'FNLT';
  date: string;
}

/** 날짜는 모두 YYYY-MM-DD. progress 는 0~1. status: done · late +n · early -n · on_plan · new. */
export interface Activity {
  id: string;
  name: string;
  kind: Kind;
  wbs: string;
  od: number;
  rd: number | null;
  progress: number;
  actual_start: string | null;
  actual_finish: string | null;
  constraint: Constraint | null;
  resources: string[];
  tags: string[];
  es: string;
  ef: string;
  /** 늦은 시작·종료(묶음 2 서버부터). 간트의 여유 꼬리. */
  ls?: string;
  lf?: string;
  plan_start: string | null;
  plan_finish: string | null;
  tf: number;
  ff: number;
  critical: boolean;
  status: string;
  weight: number;
  /** 사람이 넣은 가중치(가중치 방식이 manual 일 때 쓴다). 넣지 않았으면 null. */
  manual_weight?: number | null;
}

/** 공정률 가중치 방식: 기간 비례 · 직접 입력. */
export type WeightMode = 'duration' | 'manual';

export interface Relation {
  pred: string;
  succ: string;
  type: RelType;
  lag: number;
}

export interface Wbs {
  code: string;
  name: string;
  parent: string | null;
}

export interface Resource {
  id: string;
  name: string;
  unit: string;
  capacity: number;
}

/** 그 일정 분야의 표시 설정(분야 묶음의 display, 모르는 분야면 서버 기본값). extra_columns: resources·constraint·es_ef·ls_lf. */
export interface DisplayView {
  gantt_group_by: 'wbs' | 'resource';
  deadline_label: string;
  extra_columns: string[];
}

export interface ScheduleView {
  id: number;
  name: string;
  domain: string;
  level: string;
  version: number;
  data_date: string | null;
  finish: string;
  plan_finish: string | null;
  wbs: Wbs[];
  activities: Activity[];
  relations: Relation[];
  resources: Resource[];
  /** 묶음 2 서버부터. weight_missing = manual 방식에서 가중치를 넣지 않은 작업 수(duration 이면 0). */
  weight_mode?: WeightMode;
  summary: { critical_count: number; negative_float_count: number; warning_count: number; weight_missing?: number };
  /** 조건을 넣은 근무 달력(묶음 2 서버부터): 주 근무일 수, 일정 기간 안의 작업 금지 기간. */
  calendar?: { days_per_week: number; blocked: { tag: string; start: string; finish: string }[] };
  /** 분야 표시 설정(Task 40 서버부터): 간트 처음 묶는 기준·기한 세로선 이름·스케줄표에 처음 켤 칸. */
  display?: DisplayView;
}

export interface PredItem {
  pred: string;
  type: RelType;
  lag: number;
}

export interface VersionItem {
  n: number;
  note: string;
  by_kind: string;
  by_name: string;
  is_plan: boolean;
  created_at: string;
}

/** PATCH 로 고칠 수 있는 칸. rd·actual_*·constraint·manual_weight 는 null 로 지운다. */
export type ActivityFields = Partial<
  Pick<Activity, 'name' | 'kind' | 'wbs' | 'od' | 'rd' | 'progress' | 'actual_start' | 'actual_finish' | 'constraint' | 'manual_weight'>
>;

export interface NewActivity {
  name: string;
  kind: Kind;
  wbs: string;
  od: number;
  /** 주면 그 바로 뒤에 넣고 after → 새 액티비티 FS 0 관계를 단다. */
  after?: string;
}

const base = (id: number) => `/api/schedules/${id}`;
const act = (id: number, aid: string) => `${base(id)}/activities/${encodeURIComponent(aid)}`;
const send = (method: string, body: unknown) => ({ method, body: JSON.stringify(body) });

export const getSchedule = (id: number) => api<ScheduleView>(base(id));
export const getVersions = (id: number) => api<VersionItem[]>(`${base(id)}/versions`);

export const patchActivity = (id: number, aid: string, fields: ActivityFields, baseVersion: number) =>
  api<ScheduleView>(act(id, aid), send('PATCH', { ...fields, base_version: baseVersion }));

export const putPredecessors = (id: number, aid: string, items: PredItem[], baseVersion: number) =>
  api<ScheduleView>(`${act(id, aid)}/predecessors`, send('PUT', { items, base_version: baseVersion }));

export const postActivity = (id: number, input: NewActivity, baseVersion: number) =>
  api<ScheduleView>(`${base(id)}/activities`, send('POST', { ...input, base_version: baseVersion }));

export const deleteActivity = (id: number, aid: string, baseVersion: number) =>
  api<ScheduleView>(`${act(id, aid)}?base_version=${baseVersion}`, { method: 'DELETE' });

/** Data Date 바꾸기(null 이면 지움). 새 버전이 생긴다. */
export const patchSchedule = (id: number, body: { data_date: string | null; base_version: number }) =>
  api<ScheduleView>(base(id), send('PATCH', body));

/** 가중치 방식 바꾸기. 버전은 그대로라 바꾼 뒤 일정을 다시 읽는다. */
export const putWeightMode = (id: number, mode: WeightMode) => api<{ mode: WeightMode }>(`${base(id)}/weight-mode`, send('PUT', { mode }));

export const restoreVersion = (id: number, n: number, baseVersion: number) =>
  api<ScheduleView>(`${base(id)}/versions/${n}/restore`, send('POST', { base_version: baseVersion }));
