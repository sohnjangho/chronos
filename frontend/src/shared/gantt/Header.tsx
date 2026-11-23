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

/** 이름표가 겹칠 때 덜 중요한 것부터 줄이거나 뺀다: 오늘 < 기한 < Data Date. */
const WEIGHT: Record<HeaderMark['tone'], number> = { data: 3, deadline: 2, today: 1 };

interface Placed {
  text: string;
  left: boolean;
}

/**
 * 세로선 이름표 자리(재확인 ④: 좁은 휴대폰 간트에서 「Data Date」와 「준공 기한」이 겹쳤다). 이름표마다 선 오른쪽 · 왼쪽 ×
 * 전체 이름 · 날짜만(끝 낱말) 가운데, 서로 겹치지 않는 조합 중 값이 가장 작은 것을 고른다 — 빼기 1000 · 날짜만 10(× 중요도),
 * 머리 밖으로 나감 100, 왼쪽 1. 둘 데가 없으면 그 이름표는 뺀다(선은 차트에 그대로). 이름표는 몇 개뿐이라 다 따져 본다.
 */
function placeMarks(marks: HeaderMark[], w: number): (Placed | null)[] {
  type Option = { text: string; left: boolean; box: [number, number] | null; cost: number };
  const order = marks.map((_, i) => i).sort((a, b) => WEIGHT[marks[b].tone] - WEIGHT[marks[a].tone]);
  const choices = order.map((i): Option[] => {
    const m = marks[i];
    const texts = [...new Set([m.label, m.label.split(' ').at(-1)!])];
    const opts = texts.flatMap((text) =>
      [false, true].map((left): Option => {
        const tw = textW(text);
        const box: [number, number] = left ? [m.x - tw, m.x] : [m.x, m.x + tw];
        const outside = box[0] < 0 || box[1] > w;
        return { text, left, box, cost: (text === m.label ? 0 : 10 * WEIGHT[m.tone]) + (left ? 1 : 0) + (outside ? 100 : 0) };
      }),
    );
    return [...opts, { text: '', left: false, box: null, cost: 1000 * WEIGHT[m.tone] }];
  });
  let best: { cost: number; picks: Option[] } = { cost: Infinity, picks: [] };
  const picks: Option[] = [];
  const go = (k: number, cost: number) => {
    if (cost >= best.cost) return;
    if (k === order.length) {
      best = { cost, picks: [...picks] };
      return;
    }
    for (const o of choices[k]) {
      const b = o.box;
      if (b && picks.some((p) => p.box && b[0] < p.box[1] && p.box[0] < b[1])) continue;
      picks.push(o);
      go(k + 1, cost + o.cost);
      picks.pop();
    }
  };
  go(0, 0);
  const out: (Placed | null)[] = marks.map(() => null);
  order.forEach((i, k) => {
    const o = best.picks[k];
    out[i] = o.box ? { text: o.text, left: o.left } : null;
  });
  return out;
}

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
  const placed = placeMarks(marks, w);
  return (
    <>
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
        {marks.map((m, i) => {
          // 오른쪽 끝을 넘을 이름표(차트 끝 가까운 기한 등)는 선 왼쪽에 끝을 맞춘다 — 머리 밖으로 잘리지 않게.
          // 다른 이름표와 겹치면 날짜만 남긴다(전체 이름은 title) — placeMarks.
          const p = placed[i];
          if (!p) return null;
          const title = m.title ?? (p.text !== m.label ? m.label : undefined);
          return (
            <text
              key={m.key}
              className={`gantt-mark is-${m.tone}`}
              data-mark={m.key}
              x={p.left ? m.x - 3 : m.x + 3}
              y={55}
              textAnchor={p.left ? 'end' : undefined}
            >
              {title && <title>{title}</title>}
              {p.text}
            </text>
          );
        })}
      </svg>
      {/* svg 는 aria-hidden — 세로선 이름(전체)은 보이지 않는 글로 보조 기술에 알린다(화면은 그대로) */}
      {marks.length > 0 && <span className="os-sr-only">{`세로선: ${marks.map((m) => m.label).join(' · ')}`}</span>}
    </>
  );
}
