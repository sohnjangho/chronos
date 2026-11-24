// 실행 추적의 「관리 포인트」 단계(계획 5 Task 7): 계산 → 겨냥 검색 n회(갈래별) → Search Agent n회, 호출마다 비용 종류.
// 값은 서버 그대로(schemas.PointsStageOut). 비용은 Liner 가 알리지 않아 호출 수 × 단가로 어림한 것이다.
import Badge from '../../shared/ui/Badge';
import type { PointsStage as Stage } from './devApi';
import { count, dayGroup, hourMinute } from './format';
import { estimate, per1k, stageTitle } from './pointsText';

const RISK: Record<string, { label: string; tone: 'info' | 'success' | 'danger' | 'neutral' }> = {
  looking: { label: '외부 영향 찾는 중', tone: 'info' },
  done: { label: '찾기 끝', tone: 'success' },
  failed: { label: '외부 영향을 찾지 못함', tone: 'danger' },
  none: { label: '새 포인트 없음 — 찾지 않음', tone: 'neutral' },
};

const failedText = (n: number) => (n ? ` (실패 ${count(n)})` : '');

export default function PointsStage({ stage }: { stage: Stage }) {
  const risk = RISK[stage.risk_status] ?? { label: stage.risk_status, tone: 'neutral' as const };
  const total = stage.searches.reduce((n, s) => n + s.calls, 0);
  const agent = stage.search_agent;
  const c = stage.compute;
  return (
    <section className="dc-pt-stage" aria-label={`관리 포인트 — ${stageTitle(stage)}`}>
      <header className="dc-pt-stage-h">
        <b>관리 포인트</b>
        <span>{stageTitle(stage)}</span>
        <span className="dc-muted">{`${dayGroup(stage.changed_at)} ${hourMinute(stage.changed_at)}`}</span>
        <Badge tone={risk.tone}>{risk.label}</Badge>
      </header>
      <ol className="dc-pt-flow">
        <li className="dc-pt-step">
          <span className="dc-pt-step-h">계산</span>
          <span>{`포인트 ${count(c.points)}곳 · 새로 들어옴 ${count(c.new)} · 여유 줄어듦 ${count(c.tightened)} · 빠짐 ${count(c.removed)}`}</span>
          <span className="dc-muted">코드 계산 — 비용 없음</span>
        </li>
        <li className="dc-pt-step">
          <span className="dc-pt-step-h">{`겨냥 검색 ${count(total)}회`}</span>
          <ul className="dc-pt-calls">
            {stage.searches.map((s) => (
              <li key={s.branch}>
                <span>{`${s.label} ${count(s.calls)}회${failedText(s.failed)}`}</span>
                <span className="dc-pt-kind">{`${s.cost_kind} · ${per1k(s.per_1k)}`}</span>
              </li>
            ))}
          </ul>
          {stage.skipped > 0 && <span className="dc-muted">{`건너뛴 자료 ${count(stage.skipped)}개(현장 주소 없음 등 — 부르지 않음)`}</span>}
        </li>
        <li className="dc-pt-step">
          <span className="dc-pt-step-h">{`Search Agent ${count(agent.calls)}회`}</span>
          <ul className="dc-pt-calls">
            <li>
              <span>{`근거 문장${failedText(agent.failed)}${agent.pending ? ` · 찾는 중 ${count(agent.pending)}` : ''}`}</span>
              <span className="dc-pt-kind">{`${agent.cost_kind} · ${per1k(agent.per_1k)}`}</span>
            </li>
          </ul>
          <span className="dc-muted">[근거 문장 보기]를 누른 줄만 부릅니다.</span>
        </li>
      </ol>
      <p className="dc-pt-cost">
        어림 비용 <b>{estimate(stage.cost)}</b> <span className="dc-muted">= 호출 수 × 단가(Liner 가 값을 알려 주지 않음). 검색 수는 차이를 적은 때부터 찾기가 끝난 때까지 시각으로 이은 값입니다.</span>
      </p>
    </section>
  );
}

/** 턴 아래에 붙는 묶음(이 턴 동안 바뀐 관리 포인트). */
export function PointsStages({ stages }: { stages: Stage[] }) {
  if (stages.length === 0) return null;
  return (
    <div className="dc-pt-stages">
      {stages.map((s) => (
        <PointsStage key={`${s.schedule_id}/${s.version}/${s.what_if}`} stage={s} />
      ))}
    </div>
  );
}
