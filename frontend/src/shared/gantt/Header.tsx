import { useLayoutEffect, useRef, useState, type RefObject } from 'react';
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

/** 글자 폭 어림(글꼴 크기 px 에 곱하는 비율: 한글 0.95 · 점 0.25 · 빈칸 0.3 · 그 밖 0.6). */
const textWidth = (t: string, px: number) =>
  [...t].reduce((n, ch) => n + (/[가-힣]/.test(ch) ? 0.95 : ch === '.' ? 0.25 : ch === ' ' ? 0.3 : 0.6), 0) * px;

/** 머리 글꼴 크기(px). 토큰(--fs-11 이름표·좁은 달, --fs-12 달)은 기기마다 다르다(휴대폰 13·14px) — 그린 svg 에서 읽는다. */
function useFontSizes(ref: RefObject<SVGSVGElement | null>) {
  const [fs, setFs] = useState({ small: 11, month: 12 });
  useLayoutEffect(() => {
    if (!ref.current) return;
    const style = getComputedStyle(ref.current);
    const read = (name: string, fallback: number) => parseFloat(style.getPropertyValue(name)) || fallback;
    const next = { small: read('--fs-11', 11), month: read('--fs-12', 12) };
    setFs((cur) => (cur.small === next.small && cur.month === next.month ? cur : next));
  });
  return fs;
}
/** 이름표는 선에서 3px 떨어져 쓰고, 이웃 이름표와는 글자끼리 GAP 이상 띄운다. */
const PAD = 3;
const GAP = 4;

/** 이름표가 겹칠 때 덜 중요한 것부터 줄이거나 뺀다: 오늘 < 기한 < Data Date. */
const WEIGHT: Record<HeaderMark['tone'], number> = { data: 3, deadline: 2, today: 1 };

interface Placed {
  text: string;
  left: boolean;
}

/** 줄여 쓰는 차례: 전체 이름 → 짧은 이름(「DD 04.17」, 기한은 분야가 정한 이름의 끝 낱말 — 「준공 기한」→「기한」,
 * 「제품 납기」→「납기」) → 날짜만(끝 낱말). 겹치는 글은 하나로. */
function shortened(m: HeaderMark): string[] {
  const words = m.label.split(' ');
  const date = words.at(-1)!;
  const name = m.tone === 'data' ? `DD ${date}` : m.tone === 'deadline' && words.length > 1 ? `${words.at(-2)} ${date}` : m.label;
  return [...new Set([m.label, name, date])];
}

/**
 * 세로선 이름표 자리(재확인 ④·재확인 2: 좁은 휴대폰 간트에서 「Data Date」와 「준공 기한」이 겹쳤고, 날짜만 남으면 무엇인지
 * 몰랐다). 이름표마다 선 오른쪽 · 왼쪽 × 전체 이름 · 짧은 이름 · 날짜만 가운데, 글자끼리 겹치지 않는 조합 중 값이 가장 작은 것을
 * 고른다 — 빼기 1000 · 날짜만 30 · 짧은 이름 5(× 중요도), 머리 밖으로 나감 100, 왼쪽 1. 둘 데가 없으면 그 이름표는 뺀다
 * (선은 차트에 그대로). 이름표는 몇 개뿐이라 다 따져 본다.
 */
function placeMarks(marks: HeaderMark[], w: number, px: number): (Placed | null)[] {
  type Option = { text: string; left: boolean; box: [number, number] | null; cost: number };
  const order = marks.map((_, i) => i).sort((a, b) => WEIGHT[marks[b].tone] - WEIGHT[marks[a].tone]);
  const choices = order.map((i): Option[] => {
    const m = marks[i];
    const opts = shortened(m).flatMap((text, tier) =>
      [false, true].map((left): Option => {
        const gw = textWidth(text, px);
        const box: [number, number] = left ? [m.x - PAD - gw, m.x - PAD] : [m.x + PAD, m.x + PAD + gw];
        const outside = box[0] < 0 || box[1] > w;
        const cut = text === m.label ? 0 : tier === 1 && text !== m.label.split(' ').at(-1) ? 5 : 30; // 날짜만은 무엇인지 몰라 크게
        return { text, left, box, cost: cut * WEIGHT[m.tone] + (left ? 1 : 0) + (outside ? 100 : 0) };
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
      if (b && picks.some((p) => p.box && b[0] < p.box[1] + GAP && p.box[0] < b[1] + GAP)) continue;
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
 * 달 이름(재확인 2: 보이는 달은 모두 칸 이름이 있다 — 걸쳐 쓰느라 다음 달을 비우지 않는다).
 * 연도를 달 달(첫 달·1월, 또는 앞 달에서 넘겨받음)은 'YYYY년 M월' → 'YY.M', 그 밖은 'M월' 가운데 들어가는 것.
 * 연도를 못 달았으면 다음 달로 넘긴다. 'M월' 도 안 들어가면 숫자만 작은 글꼴로(tight), 그것도 안 들어가면 빈칸.
 */
function monthLabels(scale: Scale, fs: { small: number; month: number }) {
  const monthW = (t: string) => textWidth(t, fs.month) + 6; // 앞 여백 6
  let carry: string | null = null;
  return months(scale).map((m) => {
    const own = m.label.includes('년') ? m.label.split(' ')[0] : null;
    const year = own ?? carry;
    const month = m.label.split(' ').at(-1)!;
    const n = month.replace('월', '');
    const forms = [...(year ? [`${year} ${month}`, `${year.slice(2, 4)}.${n}`] : []), month];
    const named = forms.find((f) => monthW(f) <= m.w);
    carry = year !== null && (named === undefined || named === month) ? year : null;
    if (named !== undefined) return { ...m, label: named, tight: false, squeeze: null };
    // 아주 좁은 달: 숫자만(앞 여백 2). 그래도 넘치면 글자 사이·폭을 줄여 칸 안에(textLength), 그것도 어려우면 빈칸.
    const fit = textWidth(n, fs.small);
    if (fit + 2 <= m.w) return { ...m, label: n, tight: true, squeeze: null };
    return fit * 0.7 + 2 <= m.w ? { ...m, label: n, tight: true, squeeze: m.w - 3 } : { ...m, label: '', tight: true, squeeze: null };
  });
}

/** 날짜 머리(SVG): 달 · 주(월요일, 좁으면 건너뛴다) · 세로선 이름표. 차트와 같은 폭이다. */
export default function Header({ scale, marks = [] }: { scale: Scale; marks?: HeaderMark[] }) {
  const w = width(scale);
  const step = Math.max(1, Math.ceil(36 / (7 * scale.pxPerDay)));
  const svgRef = useRef<SVGSVGElement>(null);
  const fs = useFontSizes(svgRef);
  const placed = placeMarks(marks, w, fs.small);
  return (
    <>
      <svg ref={svgRef} className="gantt-svg gantt-header" width={w} height={HEADER_H} aria-hidden="true">
        <rect className="gantt-head-bg" width={w} height={HEADER_H} />
        {monthLabels(scale, fs).map((m, i) => (
          <g key={`m${i}`}>
            <line className="gantt-head-line" x1={m.x} x2={m.x} y1={0} y2={42} />
            <text
              className={`gantt-month${m.tight ? ' is-tight' : ''}`}
              x={m.x + (m.tight ? 2 : 6)}
              y={15}
              {...(m.squeeze ? { textLength: m.squeeze, lengthAdjust: 'spacingAndGlyphs' } : {})}
            >
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
