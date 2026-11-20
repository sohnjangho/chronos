// 보고서용 그림 API(Task 44). 모양은 서버 app/programs/visuals/schemas.py 의 VisualOut 그대로.
// 표(columns·rows)는 서버가 저장된 일정에서 계산한 값이다. 화면은 값을 계산하지 않고 그대로 그린다.
import { api } from '../api';

export type VisualKind = 'summary' | 'delay_impact' | 'scenario_compare' | 's_curve' | 'resource_load';
export type Cell = string | number | null;

export interface VisualData {
  id: number;
  schedule_id: number;
  kind: VisualKind;
  title: string;
  version: number;
  /** 기준일(YYYY-MM-DD). */
  data_date: string | null;
  columns: string[];
  rows: Cell[][];
  /** 우리 그림(SVG)의 모양. */
  chart: 'timeline' | 'bars' | 'line';
  /** Liner 가 그린 HTML. null 이면(대조 실패·Liner 실패) 우리 그림으로 대신한다. */
  html: string | null;
  theme: string;
  description: string;
  resource_id: string;
  verified: boolean;
  passed: number;
  total: number;
  fallback: boolean;
  /** 대신한 까닭(예: 「Liner 그림 검증 실패 → 기본 그림」). 통과면 빈 글. */
  note: string;
  external: string[];
  latency_ms: number | null;
  created_at: string;
}

/** 그림 한 장을 만든다(같은 입력의 통과한 그림이 있으면 서버가 그것을 준다). 20~30초 걸릴 수 있다. */
export function makeVisual(scheduleId: number, kind: VisualKind, version?: number): Promise<VisualData> {
  return api<VisualData>(`/api/schedules/${scheduleId}/visuals`, {
    method: 'POST',
    body: JSON.stringify(version === undefined ? { kind } : { kind, version }),
  });
}

export function getVisual(scheduleId: number, visualId: number): Promise<VisualData> {
  return api<VisualData>(`/api/schedules/${scheduleId}/visuals/${visualId}`);
}
