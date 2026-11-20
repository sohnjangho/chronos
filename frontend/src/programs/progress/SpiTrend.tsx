// 일정 수행 지수 추이(서버 spi_trend): 1.00 선 · 0.90 선("0.90 아래: 대응 필요")과 그 아래 칠함 · 최근 값.
import { md } from './format';
import type { ProgressData } from './progressApi';
import { xScale } from './scurve';
import { useWidth } from './useWidth';

const H = 180;
const LEFT = 34;
const TOP = 10;
const BOTTOM = 22;
const PAD = 12;

function Chart({ points, width }: { points: ProgressData['spi_trend']; width: number }) {
  const values = points.map((p) => p.spi);
  const lo = Math.floor(Math.min(0.8, Math.min(...values) - 0.02) * 10) / 10;
  const hi = Math.ceil(Math.max(1.1, Math.max(...values) + 0.02) * 10) / 10;
  const yOf = (v: number) => TOP + ((hi - v) / (hi - lo)) * (H - TOP - BOTTOM);
  const xOf = xScale(points.map((p) => p.date), { w: width - LEFT, h: H, pad: PAD });
  const x0 = LEFT + PAD;
  const x1 = width - PAD;
  const d = points.map((p, i) => `${i ? 'L' : 'M'}${LEFT + xOf(p.date)} ${yOf(p.spi)}`).join('');
  const last = points[points.length - 1];
  const lx = LEFT + xOf(last.date);
  return (
    <svg className="pg-spi" width={width} height={H} role="img" aria-label={`일정 수행 지수 추이: 최근 ${last.spi.toFixed(2)}`}>
      <rect className="pg-spi-risk" x={x0} y={yOf(0.9)} width={Math.max(x1 - x0, 0)} height={yOf(lo) - yOf(0.9)} />
      <line className="pg-spi-one" x1={x0} x2={x1} y1={yOf(1)} y2={yOf(1)} />
      <line className="pg-spi-limit" x1={x0} x2={x1} y1={yOf(0.9)} y2={yOf(0.9)} />
      <text className="pg-axis" x={LEFT - 4} y={yOf(1) + 4} textAnchor="end">1.00</text>
      <text className="pg-axis" x={LEFT - 4} y={yOf(0.9) + 4} textAnchor="end">0.90</text>
      <text className="pg-axis is-danger" x={x0 + 4} y={yOf(0.9) + 14}>0.90 아래: 대응 필요</text>
      <path className="pg-spi-line" d={d} />
      <circle className="pg-spi-dot" cx={lx} cy={yOf(last.spi)} r={4.5} />
      <text className="pg-axis" x={LEFT + xOf(points[0].date)} y={H - 6} textAnchor="start">{md(points[0].date)}</text>
      {points.length > 1 && <text className="pg-axis" x={lx} y={H - 6} textAnchor="end">{md(last.date)}</text>}
    </svg>
  );
}

export default function SpiTrend({ data }: { data: ProgressData }) {
  const { ref, width } = useWidth<HTMLDivElement>(320);
  const last = data.spi_trend.at(-1);
  return (
    <section className="pg-card pg-low-card" aria-label="일정 수행 지수 추이">
      <div className="pg-card-head">
        <h3 className="pg-card-title">일정 수행 지수 추이</h3>
        <span className="pg-muted">{`${data.unit === 'week' ? '주별' : '월별'} · 1.00 아래면 늦는 중`}</span>
        {last && <span className={`pg-spi-last${last.spi < 0.9 ? ' is-danger' : ''}`}>{`최근 ${last.spi.toFixed(2)}`}</span>}
      </div>
      <div ref={ref} className="pg-card-body pg-spi-box">
        {data.spi_trend.length ? <Chart points={data.spi_trend} width={width} /> : <p className="pg-empty">아직 실적이 없습니다.</p>}
      </div>
    </section>
  );
}
