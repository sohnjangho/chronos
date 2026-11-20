// 간트 날짜 눈금: 날짜(YYYY-MM-DD) ↔ 가로 px. 화면에 그리기만 한다 — 일정 날짜 계산(근무일·여유)은 서버가 한다.
// 날짜는 UTC 0시로 다뤄 시간대·일광 절약 시간에 흔들리지 않게 한다. 간트·CPM·비교 판이 같이 쓴다.

export interface Scale {
  /** 보이는 첫날(0시). */
  start: Date;
  /** 보이는 마지막 날(이 날까지 포함). */
  end: Date;
  pxPerDay: number;
}

const DAY = 86_400_000;

export const toDate = (iso: string) => new Date(`${iso}T00:00:00Z`);
export const isoOf = (d: Date) => d.toISOString().slice(0, 10);
export const addDays = (iso: string, n: number) => isoOf(new Date(toDate(iso).getTime() + n * DAY));
/** a 부터 b 까지 날 수 차이(b - a). */
export const daysBetween = (a: string, b: string) => Math.round((toDate(b).getTime() - toDate(a).getTime()) / DAY);

/** 보이는 날 수(처음·끝 포함). */
export const dayCount = (s: Scale) => Math.round((s.end.getTime() - s.start.getTime()) / DAY) + 1;
/** 차트 전체 폭. */
export const width = (s: Scale) => dayCount(s) * s.pxPerDay;

/** start~end(포함)를 padDays 씩 넓혀 widthPx 에 꼭 맞춘 눈금. */
export function makeScale(start: string, end: string, widthPx: number, padDays = 7): Scale {
  const s = new Date(toDate(start).getTime() - padDays * DAY);
  const e = new Date(toDate(end).getTime() + padDays * DAY);
  const days = Math.round((e.getTime() - s.getTime()) / DAY) + 1;
  return { start: s, end: e, pxPerDay: widthPx / days };
}

/** 같은 기간, pxPerDay 만 factor 배. */
export const zoomed = (s: Scale, factor: number): Scale => ({ ...s, pxPerDay: s.pxPerDay * factor });

/** 그 날 0시의 x. */
export const x = (s: Scale, iso: string) => ((toDate(iso).getTime() - s.start.getTime()) / DAY) * s.pxPerDay;

/** 막대 자리. finish 날도 포함한다 — 하루짜리도 pxPerDay 폭. */
export function barRect(s: Scale, start: string, finish: string): { x: number; w: number } {
  const x0 = x(s, start);
  return { x: x0, w: x(s, finish) + s.pxPerDay - x0 };
}

/** px 가 놓인 날. */
export const dateAt = (s: Scale, px: number) => isoOf(new Date(s.start.getTime() + Math.floor(px / s.pxPerDay + 1e-9) * DAY));

/** 달 머리: 첫 달과 1월은 'YYYY년 M월', 나머지는 'M월'. 보이는 기간으로 잘린다. */
export function months(s: Scale): { label: string; x: number; w: number }[] {
  const out: { label: string; x: number; w: number }[] = [];
  const total = width(s);
  let y = s.start.getUTCFullYear();
  let m = s.start.getUTCMonth();
  while (Date.UTC(y, m, 1) <= s.end.getTime()) {
    const from = Math.max(0, ((Date.UTC(y, m, 1) - s.start.getTime()) / DAY) * s.pxPerDay);
    const to = Math.min(total, ((Date.UTC(y, m + 1, 1) - s.start.getTime()) / DAY) * s.pxPerDay);
    const label = out.length === 0 || m === 0 ? `${y}년 ${m + 1}월` : `${m + 1}월`;
    out.push({ label, x: from, w: to - from });
    m += 1;
    if (m === 12) [y, m] = [y + 1, 0];
  }
  return out;
}

/** 보이는 기간 안의 월요일마다 눈금(라벨 'M/D'). */
export function weeks(s: Scale): { x: number; label: string }[] {
  const out: { x: number; label: string }[] = [];
  const lead = (8 - s.start.getUTCDay()) % 7; // 첫 월요일까지
  for (let t = s.start.getTime() + lead * DAY; t <= s.end.getTime(); t += 7 * DAY) {
    const d = new Date(t);
    out.push({ x: ((t - s.start.getTime()) / DAY) * s.pxPerDay, label: `${d.getUTCMonth() + 1}/${d.getUTCDate()}` });
  }
  return out;
}

/** 보이는 기간 안의 쉬는 요일: 주 5일 = 토·일, 6일 = 일, 7일 = 없음(근무 달력의 요일만 — 공휴일은 모른다). */
export function weekends(s: Scale, daysPerWeek = 5): { date: string; x: number }[] {
  const off = daysPerWeek >= 7 ? [] : daysPerWeek === 6 ? [0] : [0, 6];
  const out: { date: string; x: number }[] = [];
  for (let t = s.start.getTime(), i = 0; t <= s.end.getTime(); t += DAY, i += 1) {
    if (off.includes(new Date(t).getUTCDay())) out.push({ date: isoOf(new Date(t)), x: i * s.pxPerDay });
  }
  return out;
}
