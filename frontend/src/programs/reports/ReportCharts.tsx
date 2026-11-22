import type { ReportBlock } from './reportsApi';

export function ReportChart({ chart }: { chart: NonNullable<ReportBlock['chart']> }) {
  const points = chart.points ?? [];
  if (!points.length) return <p className="rp-muted">표시할 차트 데이터가 없습니다.</p>;

  const w = 640;
  const h = 210;
  const left = 44;
  const right = 20;
  const top = 16;
  const bottom = 26;
  const iw = w - left - right;
  const ih = h - top - bottom;
  const sx = (i: number) => left + (points.length === 1 ? iw / 2 : (i / (points.length - 1)) * iw);

  if (chart.kind === 'spi_trend') {
    const vals = points.map((p) => Number(p.spi ?? 1));
    const lo = Math.max(0, Math.min(0.8, Math.min(...vals) - 0.05));
    const hi = Math.max(1.15, Math.max(...vals) + 0.05);
    const sy = (v: number) => top + ((hi - v) / Math.max(hi - lo, 0.01)) * ih;
    const d = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${sx(i).toFixed(1)} ${sy(Number(p.spi ?? 1)).toFixed(1)}`).join(' ');
    const y1 = sy(1.0);
    const y09 = sy(0.9);
    return (
      <svg className="rp-chart-svg" viewBox={`0 0 ${w} ${h}`} role="img" aria-label="SPI 추이 차트">
        <rect className="rp-spi-risk" x={left} y={y09} width={iw} height={Math.max(0, top + ih - y09)} />
        <line className="rp-grid-ref" x1={left} x2={w - right} y1={y1} y2={y1} />
        <line className="rp-grid-danger" x1={left} x2={w - right} y1={y09} y2={y09} />
        <text className="rp-axis" x={left - 6} y={y1 + 4} textAnchor="end">1.00</text>
        <text className="rp-axis is-danger" x={left - 6} y={y09 + 4} textAnchor="end">0.90</text>
        <path className="rp-line-spi" d={d} />
        {points.map((p, i) => (
          <circle key={i} className="rp-dot-spi" cx={sx(i)} cy={sy(Number(p.spi ?? 1))} r={3.5} />
        ))}
        <text className="rp-axis" x={left} y={h - 6}>{String(points[0].date ?? '')}</text>
        <text className="rp-axis" x={w - right} y={h - 6} textAnchor="end">{String(points[points.length - 1].date ?? '')}</text>
      </svg>
    );
  }

  const sy = (v: number) => top + ((100 - Math.max(0, Math.min(100, v))) / 100) * ih;
  const planD = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${sx(i).toFixed(1)} ${sy(Number(p.plan_cum ?? 0)).toFixed(1)}`).join(' ');
  const actPts = points.map((p, i) => [i, p.actual_cum] as const).filter(([, v]) => v !== null && v !== undefined);
  const actD = actPts.map(([i, v], j) => `${j === 0 ? 'M' : 'L'}${sx(i).toFixed(1)} ${sy(Number(v)).toFixed(1)}`).join(' ');
  const fcPts = points.map((p, i) => [i, p.forecast_cum] as const).filter(([, v]) => v !== null && v !== undefined);
  const fcD = fcPts.map(([i, v], j) => `${j === 0 ? 'M' : 'L'}${sx(i).toFixed(1)} ${sy(Number(v)).toFixed(1)}`).join(' ');

  return (
    <svg className="rp-chart-svg" viewBox={`0 0 ${w} ${h}`} role="img" aria-label="월간 공정률 S-커브">
      {[0, 25, 50, 75, 100].map((tick) => (
        <g key={tick}>
          <line className="rp-grid-line" x1={left} x2={w - right} y1={sy(tick)} y2={sy(tick)} />
          <text className="rp-axis" x={left - 6} y={sy(tick) + 4} textAnchor="end">{`${tick}%`}</text>
        </g>
      ))}
      <path className="rp-line-plan" d={planD} />
      {fcD && <path className="rp-line-forecast" d={fcD} />}
      {actD && <path className="rp-line-actual" d={actD} />}
      <text className="rp-axis" x={left} y={h - 6}>{String(points[0].date ?? '')}</text>
      <text className="rp-axis" x={w - right} y={h - 6} textAnchor="end">{String(points[points.length - 1].date ?? '')}</text>
    </svg>
  );
}
