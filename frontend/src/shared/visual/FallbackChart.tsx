// 우리 그림(SVG) — Liner 그림을 쓸 수 없을 때 서버 표 그대로 그린다(Task 44). 값은 계산하지 않고 위치만 정한다.
// timeline: 줄마다 날짜 열의 처음~끝 막대 · bars: 줄마다 숫자 열 막대(음수는 0 왼쪽) · line: 첫 열(날짜) 순서로 숫자 열마다 선.
import type { Cell, VisualData } from './visualApi';

const W = 640;
const LABEL = 150;
const PAD = 16;
const PLOT = W - LABEL - PAD * 2 - 30; // 막대 끝 값 글자 자리
const ISO = /^\d{4}-\d{2}-\d{2}$/;

const isDate = (v: Cell) => typeof v === 'string' && ISO.test(v);
const short = (s: string) => (s.length > 14 ? `${s.slice(0, 13)}…` : s);
/** 첫 열 말고 비지 않은 칸이 모두 test 를 지나는 열. */
const columnsWhere = (d: VisualData, test: (v: Cell) => boolean) =>
  d.columns.map((_, i) => i).filter((i) => i > 0 && d.rows.some((r) => r[i] !== null) && d.rows.every((r) => r[i] === null || test(r[i])));

function Legend({ names, y }: { names: string[]; y: number }) {
  return (
    <g>
      {names.map((n, k) => (
        <g key={n} transform={`translate(${LABEL + PAD + k * 150}, ${y})`}>
          <rect width={10} height={10} className={`vf-s${k % 4}`} />
          <text x={14} y={9} className="vf-axis">{short(n)}</text>
        </g>
      ))}
    </g>
  );
}

function Timeline({ d }: { d: VisualData }) {
  const cols = columnsWhere(d, isDate);
  const days = d.rows.flatMap((r) => cols.map((i) => r[i])).filter(isDate).map((v) => Date.parse(String(v)));
  const lo = Math.min(...days);
  const span = Math.max(Math.max(...days) - lo, 1);
  const x = (v: Cell) => LABEL + PAD + ((Date.parse(String(v)) - lo) / span) * PLOT;
  const h = d.rows.length * 26 + 40;
  return (
    <svg className="vf-svg" viewBox={`0 0 ${W} ${h}`} role="img" aria-label={`${d.title} (기본 그림)`}>
      {d.rows.map((r, i) => {
        const xs = cols.map((c) => r[c]).filter(isDate).map(x);
        const y = 12 + i * 26;
        return (
          <g key={i}>
            <text x={LABEL} y={y + 11} textAnchor="end" className="vf-axis">{short(String(r[0] ?? ''))}</text>
            {xs.length > 0 && <rect className="vf-mark vf-s0" x={Math.min(...xs)} y={y} width={Math.max(Math.max(...xs) - Math.min(...xs), 3)} height={14} rx={3} />}
          </g>
        );
      })}
      <text x={LABEL + PAD} y={h - 8} className="vf-axis">{new Date(lo).toISOString().slice(0, 10)}</text>
      <text x={W - PAD} y={h - 8} textAnchor="end" className="vf-axis">{new Date(lo + span).toISOString().slice(0, 10)}</text>
    </svg>
  );
}

function Bars({ d }: { d: VisualData }) {
  const cols = columnsWhere(d, (v) => typeof v === 'number');
  const values = d.rows.flatMap((r) => cols.map((i) => Number(r[i] ?? 0)));
  const lo = Math.min(0, ...values);
  const span = Math.max(Math.max(0, ...values) - lo, 1);
  const x = (v: number) => LABEL + PAD + ((v - lo) / span) * PLOT;
  const group = cols.length * 12 + 12;
  const h = d.rows.length * group + 40;
  return (
    <svg className="vf-svg" viewBox={`0 0 ${W} ${h}`} role="img" aria-label={`${d.title} (기본 그림)`}>
      {d.rows.map((r, i) => (
        <g key={i}>
          <text x={LABEL} y={8 + i * group + group / 2} textAnchor="end" className="vf-axis">{short(String(r[0] ?? ''))}</text>
          {cols.map((c, k) => {
            const v = Number(r[c] ?? 0);
            return (
              <g key={c}>
                <rect className={`vf-mark vf-s${k % 4}`} x={Math.min(x(0), x(v))} y={8 + i * group + k * 12} width={Math.max(Math.abs(x(v) - x(0)), 1)} height={10} />
                <text x={Math.max(x(0), x(v)) + 4} y={17 + i * group + k * 12} className="vf-axis">{r[c] === null ? '' : String(r[c])}</text>
              </g>
            );
          })}
        </g>
      ))}
      <line x1={x(0)} x2={x(0)} y1={4} y2={h - 30} className="vf-zero" />
      <Legend names={cols.map((c) => d.columns[c])} y={h - 20} />
    </svg>
  );
}

function Line({ d }: { d: VisualData }) {
  const cols = columnsWhere(d, (v) => typeof v === 'number');
  const top = Math.max(1, ...d.rows.flatMap((r) => cols.map((i) => Number(r[i] ?? 0))));
  const h = 260;
  const plotH = h - 70;
  const x = (i: number) => LABEL / 2 + (i / Math.max(d.rows.length - 1, 1)) * (W - LABEL / 2 - PAD);
  const y = (v: number) => 12 + plotH - (v / top) * plotH;
  return (
    <svg className="vf-svg" viewBox={`0 0 ${W} ${h}`} role="img" aria-label={`${d.title} (기본 그림)`}>
      <line x1={LABEL / 2} x2={W - PAD} y1={y(0)} y2={y(0)} className="vf-zero" />
      <text x={LABEL / 2 - 6} y={y(top) + 4} textAnchor="end" className="vf-axis">{String(top)}</text>
      <text x={LABEL / 2 - 6} y={y(0) + 4} textAnchor="end" className="vf-axis">0</text>
      {cols.map((c, k) => (
        <polyline
          key={c}
          className={`vf-mark vf-line vf-s${k % 4}`}
          points={d.rows.flatMap((r, i) => (r[c] === null ? [] : [`${x(i)},${y(Number(r[c]))}`])).join(' ')}
        />
      ))}
      <text x={LABEL / 2} y={y(0) + 18} className="vf-axis">{String(d.rows[0]?.[0] ?? '')}</text>
      <text x={W - PAD} y={y(0) + 18} textAnchor="end" className="vf-axis">{String(d.rows[d.rows.length - 1]?.[0] ?? '')}</text>
      <Legend names={cols.map((c) => d.columns[c])} y={h - 20} />
    </svg>
  );
}

export default function FallbackChart({ data }: { data: VisualData }) {
  if (data.rows.length === 0) return <p className="vf-note">그릴 값이 없습니다.</p>;
  const Chart = data.chart === 'timeline' ? Timeline : data.chart === 'line' ? Line : Bars;
  return (
    <div className="vf-fallback">
      <Chart d={data} />
    </div>
  );
}
