// 진행 API(Task 24): GET /api/schedules/{id}/progress?unit=week|month. 모양은 서버 ProgressOut 그대로.
// 공정률·S-커브·지연·앞으로 3주는 모두 서버(app/core) 계산값이다. 날짜는 YYYY-MM-DD, 퍼센트는 소수 1자리.
import { api } from '../../shared/api';

export type Unit = 'week' | 'month';
export type MilestoneStatus = '완료' | '예정' | '지연' | '앞섬';

export interface CurvePoint {
  date: string;
  plan_cum: number;
  /** Data Date 까지만(그 뒤는 null). */
  actual_cum: number | null;
  /** Data Date 부터만(그 앞은 null). 지금 저장된 일정의 예측(승인·반영된 지연만, 열린 지연은 넣지 않음). */
  forecast_cum: number | null;
  plan_period: number;
  actual_period: number | null;
}

export interface ProgressData {
  schedule_id: number;
  version: number;
  data_date: string;
  /** 일정에 Data Date 가 없어 서버가 오늘로 가정했다. */
  data_date_assumed: boolean;
  unit: Unit;
  weight_mode: string;
  plan_now: number;
  actual_now: number;
  gap: number;
  /** 계획 공정률이 0 이면 null. */
  spi: number | null;
  /** Plan 이 계산되지 않은 액티비티(Plan 선·SPI 밖). 보통 0. */
  added_after_plan: { count: number; actual_pct: number };
  finish: { current: string; plan: string | null; deadline: string | null; delta: number | null; deadline_float: number | null };
  counts: { total: number; done: number; in_progress: number; late: number };
  curve: CurvePoint[];
  spi_trend: { date: string; spi: number }[];
  wbs: { code: string; name: string; weight: number; plan: number; actual: number; diff: number }[];
  milestones: { id: string; name: string; plan: string | null; actual_or_forecast: string; delta: number | null; status: MilestoneStatus }[];
  top_delays: { id: string; name: string; delay: number; tf: number; finish_impact: number }[];
  lookahead: {
    from: string;
    to: string;
    starts: { id: string; name: string; date: string }[];
    finishes: { id: string; name: string; date: string }[];
    /** reason 은 서버 글 그대로("선행 미완료: A, C · 선행 미착수: B"). */
    blocked: { id: string; name: string; date: string; reason: string }[];
  };
  cpm: {
    plan_compliance: { pct: number; done: number; due: number } | null;
    critical_variance: { days: number; max_id: string } | null;
    finish_variance: { days: number; plan: string; current: string } | null;
  };
}

export const getProgress = (id: number, unit: Unit) => api<ProgressData>(`/api/schedules/${id}/progress?unit=${unit}`);
