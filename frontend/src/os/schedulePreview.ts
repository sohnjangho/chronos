// 일정 미리 보기: 조건·규칙 창(나중에 지연 기록)이 저장하지 않고 계산한 일정을 간트차트(나중에 CPM)에 넘기는 OS 저장소.
// 프로그램끼리는 import 하지 않으므로 여기(os)에 둔다. 간트는 previews[일정 id] 가 있으면 그 일정을 그리고, 저장된 보기와
// 액티비티마다 서버 값을 견주어 바뀐 칸(Plan 칸 plan_* · Actual·예측 칸 es/ef)의 이전 자리를 점선 막대로 남긴다.
// moved 는 목록·글에만 쓴다. 로그아웃(resetShellState)·조건 창 닫기·되돌리기·확정에서 지운다.
import { create } from 'zustand';

/** 미리 보기 일정의 액티비티(서버 ScheduleView 의 activities 한 줄). 날짜는 'YYYY-MM-DD'. */
export interface PreviewActivity {
  id: string;
  name: string;
  kind: string;
  wbs: string;
  od: number;
  rd: number | null;
  progress: number;
  actual_start: string | null;
  actual_finish: string | null;
  constraint: { type: string; date: string } | null;
  resources: string[];
  tags: string[];
  es: string;
  ef: string;
  /** 늦은 시작·종료(간트의 여유 꼬리). */
  ls?: string;
  lf?: string;
  plan_start: string | null;
  plan_finish: string | null;
  tf: number;
  ff: number;
  critical: boolean;
  status: string;
  weight: number;
}

/**
 * 서버 ScheduleView 와 같은 모양. version 은 기준 버전 그대로다(저장하지 않았다).
 * plan_* 은 미리 본 일정의 Plan(바꾼 조건을 넣고 실적 없이 계산한 것, Task 16d), es/ef 는 미리 본 지금 계산.
 */
export interface PreviewView {
  id: number;
  name: string;
  domain: string;
  level: string;
  version: number;
  data_date: string | null;
  finish: string;
  plan_finish: string | null;
  wbs: { code: string; name: string; parent: string | null }[];
  activities: PreviewActivity[];
  relations: { pred: string; succ: string; type: string; lag: number }[];
  resources: { id: string; name: string; unit: string; capacity: number }[];
  summary: { critical_count: number; negative_float_count: number; warning_count: number };
  /** 조건을 넣은 근무 달력(주 근무일 수 · 일정 기간 안의 작업 금지 기간). */
  calendar?: { days_per_week: number; blocked: { tag: string; start: string; finish: string }[] };
}

/** 시작이나 끝이 움직인 액티비티(서버가 Plan 날짜로 센 것 — 목록·글용. 간트의 점선은 보기를 견주어 그린다). */
export interface MovedActivity {
  activity_id: string;
  name: string;
  before: { start: string; finish: string };
  after: { start: string; finish: string };
}

export interface SchedulePreview {
  scheduleId: number;
  view: PreviewView;
  moved: MovedActivity[];
  source: 'conditions';
}

interface SchedulePreviewState {
  /** 일정 id → 그 일정의 미리 보기(일정마다 하나). */
  previews: Record<number, SchedulePreview>;
  /** 미리 보기를 넣는다(같은 일정이면 바꾼다). */
  set(preview: SchedulePreview): void;
  /** 그 일정의 미리 보기를 지운다. */
  clear(scheduleId: number): void;
  reset(): void;
}

export const useSchedulePreview = create<SchedulePreviewState>((set) => ({
  previews: {},
  set: (preview) => set((s) => ({ previews: { ...s.previews, [preview.scheduleId]: preview } })),
  clear: (scheduleId) =>
    set((s) => {
      if (!(scheduleId in s.previews)) return {};
      const previews = { ...s.previews };
      delete previews[scheduleId];
      return { previews };
    }),
  reset: () => set({ previews: {} }),
}));
