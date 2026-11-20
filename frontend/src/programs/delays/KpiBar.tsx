// 위 KPI 넷: 준공 영향 합계 · 책임별 준공 영향 · 여유로 흡수된 지연 · 비용 환산. 모두 서버 합계(열림·반영 사건 모두).
import type { Finish, Totals } from './delaysApi';
import { impactDays, RESPONSIBILITIES, shortPair, won } from './format';

function finishLine(f: Finish): { text: string; late: boolean } {
  const parts: string[] = [];
  if (f.plan) {
    const [plan, now] = shortPair(f.plan, f.with_open);
    parts.push(`Plan ${plan} → ${now}`);
  } else parts.push(`준공 ${shortPair(f.with_open, f.with_open)[0]} · Plan 없음`);
  const fl = f.deadline_float;
  if (fl !== null) parts.push(fl >= 0 ? `기한 여유 ${fl}일` : `기한 ${-fl}일 넘음`);
  return { text: parts.join(' · '), late: fl !== null && fl < 0 };
}

function ByResponsibility({ totals }: { totals: Totals }) {
  const sum = totals.finish_impact;
  return (
    <div className="dl-kpi is-wide">
      <div className="dl-kpi-l">책임별 준공 영향</div>
      <div className="dl-resp-bar" aria-hidden="true">
        {sum > 0 &&
          RESPONSIBILITIES.map((r) => {
            const n = totals.by_responsibility[r.key];
            return n > 0 ? <span key={r.key} className={`dl-resp is-${r.key}`} style={{ width: `${(n / sum) * 100}%` }} /> : null;
          })}
      </div>
      <div className="dl-resp-legend">
        {RESPONSIBILITIES.map((r) => (
          <span key={r.key}>
            <i className={`dl-resp-dot is-${r.key}`} aria-hidden="true" />
            {`${r.label} ${totals.by_responsibility[r.key]}일`}
          </span>
        ))}
      </div>
    </div>
  );
}

export default function KpiBar({ totals, finish }: { totals: Totals; finish: Finish }) {
  const line = finishLine(finish);
  return (
    <div role="group" aria-label="지연 요약" className="dl-kpis">
      <div className="dl-kpi">
        <div className="dl-kpi-l">준공 영향 합계</div>
        <div className={`dl-kpi-v${totals.finish_impact > 0 ? ' is-danger' : ''}`}>{impactDays(totals.finish_impact)}</div>
        <div className={`dl-kpi-s${line.late ? ' is-danger' : ''}`}>{line.text}</div>
      </div>
      <ByResponsibility totals={totals} />
      <div className="dl-kpi">
        <div className="dl-kpi-l">여유로 흡수된 지연</div>
        <div className="dl-kpi-v">{`${totals.absorbed}일`}</div>
        <div className="dl-kpi-s">{`사건 ${totals.absorbed_events}건`}</div>
      </div>
      <div className="dl-kpi">
        <div className="dl-kpi-l">비용 환산</div>
        <div className="dl-kpi-v">{won(totals.cost)}</div>
        <div className="dl-kpi-s">하루 금액 × 준공 영향</div>
      </div>
    </div>
  );
}
