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
 * 달 이름. 연도를 달 달(첫 달·1월, 또는 앞 달에서 넘겨받음)은 'YYYY년 M월' → 'YY.M' 가운데 들어가는 것.
 * 둘 다 안 들어가면 그래도 'YY.M' 을 쓰고 다음 달까지 걸쳐 쓰므로 다음 달 이름은 비운다(좁은 창에서도 첫 달·1월은 연도를 단다).
 * 다만 첫 달이 'M월' 도 안 들어가는 조각이면 연도를 다음 달에 넘기고, 다음 달이 1월이면(거기서 연도를 단다) 이 달은 'M월'.
 * 그 밖의 달은 'M월'(안 들어가면 빈칸).
 */
function monthLabels(scale: Scale) {
  const ms = months(scale);
  const fits = (t: string, w: number) => textW(t) <= w;
  let carry: string | null = null;
  let skip = false;
  return ms.map((m, i) => {
    const own = m.label.includes('년') ? m.label.split(' ')[0] : null;
    const year = own ?? carry;
    const month = m.label.split(' ').at(-1)!;
    carry = null;
    if (skip) {
      skip = false;
      return { ...m, label: '' };
    }
    const plain = fits(month, m.w) ? month : '';
    if (!year) return { ...m, label: plain };
    const short = `${year.slice(2, 4)}.${month.replace('월', '')}`;
    const fitted = [`${year} ${month}`, short].find((t) => fits(t, m.w));
    if (fitted) return { ...m, label: fitted };
    const next = ms[i + 1];
    if (next?.label.includes('년')) return { ...m, label: plain };
    if (next && i === 0 && !plain) {
      carry = year;
      return { ...m, label: '' };
    }
    skip = next !== undefined;
    return { ...m, label: short };
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
      {marks.map((m) => {
        // 오른쪽 끝을 넘을 이름표(차트 끝 가까운 기한 등)는 선 왼쪽에 끝을 맞춘다 — 머리 밖으로 잘리지 않게.
        const left = m.x + textW(m.label) > w;
        return (
          <text
            key={m.key}
            className={`gantt-mark is-${m.tone}`}
            data-mark={m.key}
            x={left ? m.x - 3 : m.x + 3}
            y={55}
            textAnchor={left ? 'end' : undefined}
          >
            {m.title && <title>{m.title}</title>}
            {m.label}
          </text>
        );
      })}
    </svg>
  );
}
