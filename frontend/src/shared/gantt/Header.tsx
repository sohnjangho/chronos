import { months, weeks, width, type Scale } from './scale';
import './gantt.css';

/** 머리 높이: 달 22 · 주 20 · 표시(Data Date·기한·오늘) 18. */
export const HEADER_H = 60;

export interface HeaderMark {
  key: string;
  x: number;
  label: string;
  tone: 'data' | 'deadline' | 'today';
  title?: string;
}

/** 글 폭 어림(12px 굵은 글꼴: 한글 11 · 그 밖 7) + 앞 여백 6 · 뒤 2. */
const textW = (t: string) => [...t].reduce((n, ch) => n + (/[가-힣]/.test(ch) ? 11 : 7), 8);

/**
 * 달 이름: 연도를 달 달(첫 달·1월, 또는 앞 달에서 넘겨받음)은 'YYYY년 M월' → 'YY.M' 차례로 들어가는 것을, 그 밖은 'M월'.
 * 연도가 들어가지 않으면 그 달은 'M월'(들어가면)로 쓰고 연도는 다음 달에 한 번만 넘긴다 — 넘겨받은 달에도 안 들어가면 버린다
 * (좁은 창에서 연도를 계속 넘겨 모든 달이 빈칸이 되지 않게). 'M월' 도 안 들어가면 빈칸.
 */
function monthLabels(scale: Scale) {
  let carry: string | null = null;
  return months(scale).map((m) => {
    const own = m.label.includes('년') ? m.label.split(' ')[0] : null;
    const year = own ?? carry;
    const month = m.label.split(' ').at(-1)!;
    carry = null;
    const tries = year ? [`${year} ${month}`, `${year.slice(2, 4)}.${month.replace('월', '')}`] : [];
    const withYear = tries.find((t) => textW(t) <= m.w);
    if (withYear) return { ...m, label: withYear };
    if (own) carry = own;
    return { ...m, label: textW(month) <= m.w ? month : '' };
  });
}

/** 날짜 머리(SVG): 달 · 주(월요일, 좁으면 건너뛴다) · 세로선 이름표. 차트와 같은 폭이다. */
export default function Header({ scale, marks = [] }: { scale: Scale; marks?: HeaderMark[] }) {
  const w = width(scale);
  const step = Math.max(1, Math.ceil(36 / (7 * scale.pxPerDay)));
  return (
    <svg className="gantt-svg gantt-header" width={w} height={HEADER_H} aria-hidden="true">
      <rect className="gantt-head-bg" width={w} height={HEADER_H} />
      {monthLabels(scale).map((m, i) => (
        <g key={`m${i}`}>
          <line className="gantt-head-line" x1={m.x} x2={m.x} y1={0} y2={42} />
          <text className="gantt-month" x={m.x + 6} y={15}>
            {m.label}
          </text>
        </g>
      ))}
      <line className="gantt-head-line" x1={0} x2={w} y1={22} y2={22} />
      {weeks(scale).map((t, i) => (
        <g key={t.x}>
          <line className="gantt-head-tick" x1={t.x} x2={t.x} y1={22} y2={42} />
          {i % step === 0 && (
            <text className="gantt-week" x={t.x + 3} y={36}>
              {t.label}
            </text>
          )}
        </g>
      ))}
      <line className="gantt-head-line" x1={0} x2={w} y1={42} y2={42} />
      {marks.map((m) => (
        <text key={m.key} className={`gantt-mark is-${m.tone}`} data-mark={m.key} x={m.x + 3} y={55}>
          {m.title && <title>{m.title}</title>}
          {m.label}
        </text>
      ))}
    </svg>
  );
}
