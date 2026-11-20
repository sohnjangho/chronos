// S-커브 그림 자리: 서버가 낸 점(날짜·퍼센트)을 SVG 좌표로 옮기기만 한다. 날짜를 새로 만들지 않는다.
// weekLabel 의 주 수 셈만 예외(brief 가 허락한 글: n = ceil((Data Date − Plan 시작) 일 / 7), N = ceil((Plan 준공 − Plan 시작 + 1) 일 / 7)).
import type { CurvePoint } from './progressApi';

export interface Box {
  w: number;
  h: number;
  pad: number;
}

export interface Bar {
  /** 기간(앞 점 ~ 이 점)의 왼쪽 x 와 폭. */
  x: number;
  w: number;
  /** 그 기간의 계획·실적 몫(퍼센트, 서버 값). 실적은 Data Date 뒤면 null. */
  plan: number;
  actual: number | null;
}

export interface Scaled {
  plan: string;
  actual: string;
  forecast: string;
  bars: Bar[];
  dataDateX: number;
  yOf(pct: number): number;
}

const DAY = 86_400_000;
const r2 = (v: number) => Math.round(v * 100) / 100;
const ms = (iso: string) => Date.parse(`${iso}T00:00:00Z`);

/** 날짜 → x(첫 점 ~ 끝 점을 pad 안쪽에 펼침). 범위 밖이면 끝에 붙인다. */
export function xScale(dates: string[], box: Box): (iso: string) => number {
  const t0 = dates.length ? ms(dates[0]) : 0;
  const span = dates.length ? Math.max(ms(dates[dates.length - 1]) - t0, 1) : 1;
  const inner = box.w - 2 * box.pad;
  return (iso) => r2(box.pad + Math.min(Math.max((ms(iso) - t0) / span, 0), 1) * inner);
}

/** 0~100% → y(100% 가 pad, 0% 가 h − pad). */
export function yScale(box: Box): (pct: number) => number {
  return (pct) => r2(box.pad + ((100 - pct) / 100) * (box.h - 2 * box.pad));
}

/** null 점은 건너뛰고 이은 SVG 경로. */
function path(points: [number, number | null][]): string {
  return points
    .filter((p): p is [number, number] => p[1] !== null)
    .map(([x, y], i) => `${i ? 'L' : 'M'}${x} ${y}`)
    .join('');
}

export function scaleCurve(curve: CurvePoint[], box: Box, dataDate: string): Scaled {
  const xOf = xScale(curve.map((c) => c.date), box);
  const yOf = yScale(box);
  const line = (pick: (c: CurvePoint) => number | null) =>
    path(curve.map((c) => {
      const v = pick(c);
      return [xOf(c.date), v === null ? null : yOf(v)];
    }));
  const bars = curve.slice(1).map((c, i) => {
    const x = xOf(curve[i].date);
    return { x, w: r2(xOf(c.date) - x), plan: c.plan_period, actual: c.actual_period };
  });
  return {
    plan: line((c) => c.plan_cum),
    actual: line((c) => c.actual_cum),
    forecast: line((c) => c.forecast_cum),
    bars,
    dataDateX: curve.length ? xOf(dataDate) : box.pad,
    yOf,
  };
}

export function weekLabel(dataDate: string, planStart: string, planFinish: string): string {
  const days = (a: string, b: string) => Math.round((ms(b) - ms(a)) / DAY);
  const n = Math.ceil(days(planStart, dataDate) / 7);
  const total = Math.ceil((days(planStart, planFinish) + 1) / 7);
  return `${n}주차 / ${total}주`;
}
