// 비교판 글·줄 도우미. 서버가 준 값(날짜 글·근무일 차이)을 보이는 모양으로만 바꾼다 — 날짜를 계산하지 않는다.
import type { Change, RowOut, SideOut } from './compareApi';

/** 달라진 것만이면 같음(same)이 아닌 줄만, 서버 차례 그대로. */
export function visibleRows(rows: RowOut[], onlyChanged: boolean): RowOut[] {
  return onlyChanged ? rows.filter((r) => r.change !== 'same') : rows;
}

/** 근무일 차이: −3일 · +2일 · 0 · —(없음). 빼기는 U+2212. */
export function deltaText(n: number | null): string {
  if (n === null) return '—';
  if (n === 0) return '0';
  return n < 0 ? `−${-n}일` : `+${n}일`;
}

/** 기한 여유(근무일): 6일 · 0일 · −3일(늦음) · —(기한 없음). */
export const floatText = (n: number | null) => (n === null ? '—' : n < 0 ? `−${-n}일` : `${n}일`);

/** 차이 글의 색: 당김(음수) 좋음 · 밀림(양수) 나쁨. invert 면 반대(기한 여유는 음수가 나쁨). */
export function toneOf(n: number | null, invert = false): string {
  if (!n) return '';
  return n < 0 !== invert ? 'is-good' : 'is-bad';
}

/** 2027-03-16 → 2027.03.16 */
export const dot = (iso: string) => iso.replaceAll('-', '.');
/** 2027-03-16 → 03.16 */
export const monthDay = (iso: string) => iso.slice(5).replace('-', '.');

export const CHANGE_LABEL: Record<Change, string> = {
  pulled: '당겨짐',
  pushed: '밀림',
  same: '같음',
  added: '새로 생김',
  removed: '빠짐',
  duration: '기간만 바뀜',
};

/** 줄들의 첫 시작·마지막 종료(글자 비교로 고르기만 한다)와 더 넣을 날(기한). 줄이 없으면 null. */
export function spanOf(rows: RowOut[], extra: string[]): { start: string; end: string } | null {
  const days = rows.flatMap((r) => [r.base, r.other].flatMap((c) => (c ? [c.start, c.finish] : [])));
  if (!days.length) return null;
  const all = [...days, ...extra].sort();
  return { start: all[0], end: all[all.length - 1] };
}

/** OD 칸: 같으면 하나, 다르면 기준 → 비교, 한쪽에 없으면 —. */
export function odText(r: RowOut): string {
  const a = r.base?.od ?? null;
  const b = r.other?.od ?? null;
  if (a !== null && a === b) return String(a);
  return `${a ?? '—'} → ${b ?? '—'}`;
}

/** 기한 세로선: deadline_float 이 있는 안의 기한(서버 글). 날이 하나면 「기한 MM.DD」, 다르면 안 이름을 앞에 붙인다. */
export function deadlinesOf(sides: [string, SideOut][]): { date: string; label: string }[] {
  const live = sides.flatMap(([who, s]) => (s.deadline && s.deadline_float !== null ? [{ who, date: s.deadline }] : []));
  const dates = [...new Set(live.map((d) => d.date))];
  if (dates.length <= 1) return dates.map((date) => ({ date, label: `기한 ${monthDay(date)}` }));
  return live.map((d) => ({ date: d.date, label: `${d.who} 기한 ${monthDay(d.date)}` }));
}
