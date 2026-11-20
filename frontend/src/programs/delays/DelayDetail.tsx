// 오른쪽 자세히: 원인·책임·기간·하루 금액·근거 문서 [고치기] · 영향 분석(서버 계산값) · [이 사건 만회안 요청] · [다시 분석].
import type { ReactNode } from 'react';
import Badge from '../../shared/ui/Badge';
import Button from '../../shared/ui/Button';
import type { DelayEvent, Impact } from './delaysApi';
import { dot, impactDays, respOf, won } from './format';

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="dl-kv">
      <span>{label}</span>
      <span>{children}</span>
    </div>
  );
}

const milestoneLine = (i: Impact) =>
  i.milestones.length ? i.milestones.map((m) => `${m.name} ${m.delta > 0 ? '+' : ''}${m.delta}`).join(' · ') : '바뀌지 않음';

function criticalLine(i: Impact): string {
  const names = (list: Impact['critical_added']) => list.map((n) => n.name).join('·');
  const parts: string[] = [];
  if (i.critical_added.length) parts.push(`${names(i.critical_added)} 가 새로 크리티컬`);
  if (i.critical_removed.length) parts.push(`${names(i.critical_removed)} 는 크리티컬에서 빠짐`);
  return parts.length ? parts.join(' · ') : '바뀌지 않음';
}

const clashLine = (i: Impact) =>
  i.new_clashes.length
    ? i.new_clashes.map((c) => `${dot(c.first)} 부터 ${c.days}일 ${c.name} 겹침이 새로 생김`).join(' · ')
    : '새 겹침 없음';

function ImpactRows({ impact, onGantt, busy }: { impact: Impact | null; onGantt: () => void; busy: boolean }) {
  if (!impact) return <p className="dl-muted">아직 분석하지 않았습니다. [다시 분석]을 누르세요.</p>;
  if (!impact.applied) return <p className="dl-note">{impact.note ?? '일정에 넣지 않은 사건입니다.'}</p>;
  return (
    <>
      <Row label="준공">
        <b className={impact.finish_delta > 0 ? 'is-danger' : undefined}>{`${impactDays(impact.finish_delta)} (여유 흡수 ${impact.absorbed}일)`}</b>
      </Row>
      <Row label="주요 날짜">{milestoneLine(impact)}</Row>
      <Row label="크리티컬 패스">{criticalLine(impact)}</Row>
      <Row label="영향 액티비티">
        <span className="dl-inline">
          <span>{`${impact.affected.length}개`}</span>
          <Button onClick={onGantt} disabled={busy}>
            간트에서 보기
          </Button>
        </span>
      </Row>
      <Row label="자원">{clashLine(impact)}</Row>
      <Row label="비용 환산">{won(impact.cost)}</Row>
    </>
  );
}

interface Props {
  event: DelayEvent | null;
  busy: boolean;
  onEdit: () => void;
  onGantt: () => void;
  onRecover: () => void;
  onAnalyze: () => void;
}

export default function DelayDetail({ event, busy, onEdit, onGantt, onRecover, onAnalyze }: Props) {
  if (!event) return <p className="dl-muted dl-pad">표에서 사건을 고르면 원인과 영향 분석이 보입니다.</p>;
  const resp = respOf(event.responsibility);
  return (
    <div className="dl-detail">
      <div className="dl-detail-head">
        <h3 className="dl-title">{`${event.activity_id} ${event.activity_name}`}</h3>
        <Button onClick={onEdit} disabled={busy}>
          고치기
        </Button>
      </div>
      <Row label="원인">{event.cause}</Row>
      <Row label="책임">
        <Badge tone={resp.tone}>{resp.label}</Badge>
      </Row>
      <Row label="기간">{`${dot(event.start_date)} 부터 ${event.days}일`}</Row>
      <Row label="하루 금액">{won(event.daily_cost)}</Row>
      <Row label="근거 문서">{event.evidence || '—'}</Row>
      <h4 className="dl-sec">영향 분석</h4>
      <ImpactRows impact={event.impact} onGantt={onGantt} busy={busy} />
      <div className="dl-actions">
        <Button variant="primary" onClick={onRecover}>
          이 사건 만회안 요청
        </Button>
        <Button onClick={onAnalyze} disabled={busy}>
          다시 분석
        </Button>
      </div>
    </div>
  );
}
