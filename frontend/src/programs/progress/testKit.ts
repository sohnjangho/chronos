// 공정률 시험 전용 도우미: Task 24 진행 API 시험의 응답 값 그대로(가상 일정)와 가짜 진행 API.
// 화면 코드는 이 파일을 import 하지 않는다.
import { vi } from 'vitest';
import { fetchMock } from '../../shared/schedule/testKit';
import { json } from '../../test-helpers';
import type { ProgressData } from './progressApi';

/** A(5일, 기초) → B(5일, 골조) → M(준공). Data Date 3/3, A 실적 시작 3/1·진도 0.2. */
export const P: ProgressData = {
  schedule_id: 1, version: 1, data_date: '2027-03-03', data_date_assumed: false, unit: 'week', weight_mode: 'duration',
  plan_now: 20.0, actual_now: 10.0, gap: -10.0, spi: 0.5,
  added_after_plan: { count: 0, actual_pct: 0.0 },
  finish: { current: '2027-03-15', plan: '2027-03-12', deadline: null, delta: 1, deadline_float: null },
  counts: { total: 2, done: 0, in_progress: 1, late: 2 },
  curve: [
    { date: '2027-03-01', plan_cum: 0.0, actual_cum: 0.0, forecast_cum: null, plan_period: 0.0, actual_period: 0.0 },
    { date: '2027-03-03', plan_cum: 20.0, actual_cum: 10.0, forecast_cum: 10.0, plan_period: 20.0, actual_period: 10.0 },
    { date: '2027-03-08', plan_cum: 50.0, actual_cum: null, forecast_cum: 40.0, plan_period: 30.0, actual_period: null },
    { date: '2027-03-15', plan_cum: 100.0, actual_cum: null, forecast_cum: 90.0, plan_period: 50.0, actual_period: null },
    { date: '2027-03-16', plan_cum: 100.0, actual_cum: null, forecast_cum: 100.0, plan_period: 0.0, actual_period: null },
  ],
  spi_trend: [{ date: '2027-03-03', spi: 0.5 }],
  wbs: [
    { code: '1', name: '기초', weight: 0.5, plan: 40.0, actual: 20.0, diff: -20.0 },
    { code: '2', name: '골조', weight: 0.5, plan: 0.0, actual: 0.0, diff: 0.0 },
  ],
  milestones: [{ id: 'M', name: '준공', plan: '2027-03-12', actual_or_forecast: '2027-03-15', delta: 1, status: '지연' }],
  top_delays: [
    { id: 'A', name: '작업 A', delay: 1, tf: 0, finish_impact: 1 },
    { id: 'B', name: '작업 B', delay: 1, tf: 0, finish_impact: 1 },
  ],
  lookahead: {
    from: '2027-03-03', to: '2027-03-23',
    starts: [{ id: 'B', name: '작업 B', date: '2027-03-09' }],
    finishes: [{ id: 'A', name: '작업 A', date: '2027-03-08' }, { id: 'B', name: '작업 B', date: '2027-03-15' }],
    blocked: [{ id: 'B', name: '작업 B', date: '2027-03-09', reason: '선행 미완료: A' }],
  },
  cpm: {
    plan_compliance: null,
    critical_variance: { days: 1, max_id: 'A' },
    finish_variance: { days: 1, plan: '2027-03-12', current: '2027-03-15' },
  },
};

let reply: { status: number; body: unknown } = { status: 200, body: P };
let urls: string[] = [];

/** 다음 진행 API 응답(모든 GET 이 이것을 받는다). */
export function mockProgress(body: ProgressData | { status: number; body: unknown }) {
  reply = 'status' in body && 'body' in body ? body : { status: 200, body };
}

/** 일정 1 의 가짜 일정 서버(shared testKit, setup 뒤) 위에 진행 API 를 얹는다. */
export function stubProgressApi() {
  reply = { status: 200, body: P };
  urls = [];
  const base = fetchMock;
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (!url.startsWith('/api/schedules/1/progress')) return base(input, init);
      urls.push(url);
      const unit = new URL(url, 'http://x').searchParams.get('unit') ?? 'week';
      const body = reply.status === 200 ? { ...(reply.body as ProgressData), unit } : reply.body; // 서버처럼 단위를 되돌려 준다
      return Promise.resolve(json(reply.status, body));
    }),
  );
}

/** 진행 API 를 부른 주소들. */
export const progressUrls = () => urls;
export const lastUrl = () => urls.at(-1) ?? '';
