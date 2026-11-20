// 위 띠: 상태(계획보다 늦음/계획대로 · n주차 / N주 · 준공 +n일 · 준공 여유 m일) + KPI 다섯
// (계획 공정률 · 실적 공정률(차이 %p) · 일정 수행 지수 · 준공 · 액티비티). 값은 모두 서버 값.
import type { ReactNode } from 'react';
import Badge from '../../shared/ui/Badge';
import { days, md, pct, signed } from './format';
import type { ProgressData } from './progressApi';
import { weekLabel } from './scurve';

function finishText(delta: number | null): string {
  if (delta === null) return 'Plan 준공 없음';
  if (delta > 0) return `준공 ${days(delta)}`;
  if (delta < 0) return `준공 ${Math.abs(delta)}일 앞섬`;
  return '준공 Plan 대로';
}

function floatText(float: number | null): string | null {
  if (float === null) return null; // 기한(finish_by)이 없다
  return float >= 0 ? `준공 여유 ${float}일` : `기한 넘김 ${Math.abs(float)}일`;
}

function Status({ data, planStart }: { data: ProgressData; planStart: string | null }) {
  const late = data.spi !== null && data.spi < 1;
  const plan = data.finish.plan;
  const float = floatText(data.finish.deadline_float);
  return (
    <div className="pg-status">
      <div className="pg-status-top">
        <Badge tone={late ? 'danger' : 'success'}>{late ? '계획보다 늦음' : '계획대로'}</Badge>
        {planStart && plan && <span className="pg-muted">{weekLabel(data.data_date, planStart, plan)}</span>}
      </div>
      <div className="pg-status-main">
        <span className={(data.finish.delta ?? 0) > 0 ? 'is-danger' : undefined}>{finishText(data.finish.delta)}</span>
        {float && <span className="pg-status-sub">{`· ${float}`}</span>}
      </div>
    </div>
  );
}

function Stat({ label, value, extra, sub, danger }: { label: string; value: string; extra?: ReactNode; sub: string; danger?: 'value' | 'sub' }) {
  return (
    <div className="pg-stat">
      <div className="pg-stat-l">{label}</div>
      <div className={`pg-stat-v${danger === 'value' ? ' is-danger' : ''}`}>
        {value}
        {extra}
      </div>
      <div className={`pg-stat-s${danger === 'sub' ? ' is-danger' : ''}`}>{sub}</div>
    </div>
  );
}

export default function KpiRow({ data, planStart }: { data: ProgressData; planStart: string | null }) {
  const { finish: f, counts: c, spi } = data;
  return (
    <section className="pg-card pg-kpis" aria-label="공정률 요약">
      <Status data={data} planStart={planStart} />
      <Stat label="계획 공정률" value={`${pct(data.plan_now)}%`} sub="Data Date 기준" />
      <Stat label="실적 공정률" value={`${pct(data.actual_now)}%`} sub={`${signed(data.gap)}%p`} danger={data.gap < 0 ? 'sub' : undefined} />
      <Stat
        label="일정 수행 지수 (실적 ÷ 계획)"
        value={spi === null ? '—' : spi.toFixed(2)}
        sub={spi === null ? '계획 공정률이 0 이라 계산하지 않습니다' : '1.00 이상이면 계획대로'}
        danger={spi !== null && spi < 1 ? 'value' : undefined}
      />
      <Stat
        label="준공"
        value={md(f.current)}
        extra={f.delta ? <span className={`pg-stat-x${f.delta > 0 ? ' is-danger' : ''}`}>{days(f.delta)}</span> : null}
        sub={`Plan ${md(f.plan)} · ${f.deadline ? `기한 ${md(f.deadline)}` : '기한 없음'}`}
      />
      <Stat label="액티비티" value={String(c.done)} extra={<span className="pg-stat-x is-muted">{`/ ${c.total} 완료`}</span>} sub={`진행 ${c.in_progress} · 지연 ${c.late}`} />
    </section>
  );
}
