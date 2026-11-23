// S-커브 카드: 계획 누적(실선) · 실적 누적(굵은 실선, Data Date 까지) · 예측(점선, Data Date 부터 — 지금 저장된 일정의 계산이라
// 승인해 반영한 지연만 들어 있다. 기록만 한 열린 지연은 창 위 띠로 따로 보인다)
// · 주간(월간) 계획·실적 막대(오른쪽 눈금) · Data Date 세로선. 점·값은 모두 서버 값이다.
import { dot } from '../../shared/schedule/format';
import { md, pct } from './format';
import type { ProgressData, Unit } from './progressApi';
import { scaleCurve, xScale, type Box, type Scaled } from './scurve';
import { useWidth } from './useWidth';

export const CURVE_H = 270;
const LEFT = 44; // 왼쪽 % 눈금 자리
const RIGHT = 48; // 오른쪽 막대 눈금 자리
const BOTTOM = 18; // 아래 날짜 자리
const PAD = 22;

export const periodWord = (unit: Unit) => (unit === 'week' ? '주간' : '월간');

/** 범례: [글, 견본 class]. 화면과 그림 파일이 같이 쓴다. */
export const legend = (unit: Unit): [string, string][] => [
  ['계획 누적', 'is-plan'],
  ['실적 누적', 'is-actual'],
  ['예측(승인·반영된 지연만)', 'is-forecast'],
  [`${periodWord(unit)} 계획`, 'is-bar-plan'],
  [`${periodWord(unit)} 실적`, 'is-bar-actual'],
];

/** 아래 날짜 글: 서로 64px 이상 떨어진 점만. */
function ticks(dates: string[], inner: number): number[] {
  const step = Math.max(1, Math.ceil((dates.length * 64) / Math.max(inner, 1)));
  return dates.map((_, i) => i).filter((i) => i % step === 0);
}

function Bars({ data, s, box }: { data: ProgressData; s: Scaled; box: Box }) {
  const max = Math.max(0, ...data.curve.map((c) => Math.max(c.plan_period, c.actual_period ?? 0)));
  if (max <= 0) return null;
  const full = 0.4 * (box.h - 2 * box.pad);
  const base = box.h - box.pad;
  const hOf = (v: number) => (v / max) * full;
  return (
    <g>
      {s.bars.map((b, i) => {
        const gap = Math.min(2, b.w * 0.1);
        const bw = Math.max((b.w - 2 * gap) / 2, 0.5);
        return (
          <g key={i}>
            <rect className="pg-bar-plan" x={b.x + gap} y={base - hOf(b.plan)} width={bw} height={hOf(b.plan)} />
            {b.actual !== null && <rect className="pg-bar-actual" x={b.x + gap + bw} y={base - hOf(b.actual)} width={bw} height={hOf(b.actual)} />}
          </g>
        );
      })}
      <text className="pg-axis" x={box.w - box.pad + 6} y={base - full + 4}>{`${data.unit === 'week' ? '주' : '월'} ${pct(max)}%`}</text>
    </g>
  );
}

/** 곡선 그림 한 장(width × height). 화면과 그림 내보내기가 같이 쓴다. */
export function CurveSvg({ data, width, height, y = 0 }: { data: ProgressData; width: number; height: number; y?: number }) {
  const box = { w: width - LEFT - RIGHT + 2 * PAD, h: height - BOTTOM, pad: PAD };
  const s = scaleCurve(data.curve, box, data.data_date);
  const dates = data.curve.map((c) => c.date);
  const xOf = xScale(dates, box);
  const right = s.dataDateX > box.w * 0.6;
  const label = `Data Date ${md(data.data_date)} · 계획 ${pct(data.plan_now)}% · 실적 ${pct(data.actual_now)}%`;
  const spoken = `누적 공정률 곡선(계획, 실적, 예측) — Data Date ${dot(data.data_date)}, 계획 ${pct(data.plan_now)}%, 실적 ${pct(data.actual_now)}%`;
  return (
    <svg className="pg-curve" y={y} width={width} height={height} role="img" aria-label={spoken}>
      <g transform={`translate(${LEFT - PAD} 0)`}>
        {[0, 25, 50, 75, 100].map((p) => (
          <g key={p}>
            <line className={p === 0 ? 'pg-grid is-base' : 'pg-grid'} x1={box.pad} x2={box.w - box.pad} y1={s.yOf(p)} y2={s.yOf(p)} />
            <text className="pg-axis" x={box.pad - 6} y={s.yOf(p) + 4} textAnchor="end">{`${p}%`}</text>
          </g>
        ))}
        <Bars data={data} s={s} box={box} />
        <path className="pg-line-plan" d={s.plan} />
        <path className="pg-line-forecast" d={s.forecast} />
        <path className="pg-line-actual" d={s.actual} />
        <line className="pg-dd" x1={s.dataDateX} x2={s.dataDateX} y1={box.pad - 4} y2={box.h - box.pad} />
        <text className="pg-dd-label" x={s.dataDateX + (right ? -6 : 6)} y={box.pad - 8} textAnchor={right ? 'end' : 'start'}>{label}</text>
        {ticks(dates, box.w - 2 * box.pad).map((i) => (
          <text key={i} className="pg-axis" x={xOf(dates[i])} y={box.h - box.pad + 15} textAnchor="middle">{md(dates[i])}</text>
        ))}
      </g>
    </svg>
  );
}

export default function SCurve({ data }: { data: ProgressData }) {
  const { ref, width } = useWidth<HTMLDivElement>(720);
  return (
    <section className="pg-card pg-curve-card" aria-label="S-커브">
      <div className="pg-card-head">
        <h3 className="pg-card-title">{`공정률 — 누적(선)과 ${periodWord(data.unit)}(막대)`}</h3>
        <ul className="pg-legend">
          {legend(data.unit).map(([text, cls]) => (
            <li key={cls}><span className={`pg-swatch ${cls}`} />{text}</li>
          ))}
        </ul>
      </div>
      <div ref={ref} className="pg-curve-box">
        {data.curve.length ? <CurveSvg data={data} width={width} height={CURVE_H} /> : <p className="pg-empty">Plan 이 없어 곡선을 그릴 수 없습니다.</p>}
      </div>
    </section>
  );
}
