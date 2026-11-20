// CPM 요약 줄이 읽는 서버 값: 진행 API(Task 24)의 cpm 묶음, 반영된 단축안(Task 26)의 만회 기록. 화면은 계산하지 않는다.
import { api } from '../../shared/api';

export interface CpmBlock {
  /** Plan 종료가 Data Date 앞인 작업 가운데 Plan 종료까지 끝낸 비율(정수 %). 대상이 없으면 null. */
  plan_compliance: { pct: number; done: number; due: number } | null;
  /** 크리티컬 작업의 (지금 근무일 − Plan 근무일) 합과 가장 큰 것. */
  critical_variance: { days: number; max_id: string } | null;
  /** 준공: Plan → 지금(근무일 차이). Plan 준공이 없으면 null. */
  finish_variance: { days: number; plan: string; current: string } | null;
}

/** 반영된 단축안의 목표 단축(근무일)과 지금 만회한 근무일(지금 일정을 계산할 수 없으면 null). */
export interface Recovery {
  planned_gain: number;
  achieved: number | null;
}

export const getCpmBlock = (id: number) => api<{ cpm: CpmBlock }>(`/api/schedules/${id}/progress`).then((r) => r.cpm);

/** 가장 최근(목록은 새것부터) 반영된 단축안의 만회 기록. 없으면 null. */
export const getRecovery = (id: number) =>
  api<{ recovery: Recovery | null }[]>(`/api/schedules/${id}/scenarios?status=applied`).then((list) => list.find((s) => s.recovery)?.recovery ?? null);
