// 마일스톤 추적: Plan 대비 실적(끝난 것)·예측(아직 안 온 것, 승인·반영된 지연만). 상태·차이는 서버 값.
import Badge, { type Tone } from '../../shared/ui/Badge';
import Table from '../../shared/ui/Table';
import { days, md, signed } from './format';
import type { MilestoneStatus, ProgressData } from './progressApi';

type Milestone = ProgressData['milestones'][number];

const TONE: Record<MilestoneStatus, Tone> = { 완료: 'neutral', 예정: 'success', 지연: 'danger', 앞섬: 'info' };

function statusText(m: Milestone): string {
  if ((m.status === '지연' || m.status === '앞섬') && m.delta !== null) return `${m.status} ${days(m.delta)}`;
  return m.status;
}

export default function MilestoneTable({ data }: { data: ProgressData }) {
  return (
    <section className="pg-card pg-ms-card" aria-label="마일스톤">
      <div className="pg-card-head">
        <h3 className="pg-card-title">마일스톤 추적</h3>
        <span className="pg-muted">Plan 대비 실적 · 아직 안 온 것은 예측(승인·반영된 지연만)</span>
      </div>
      <div className="pg-card-body pg-ms-body">
        <Table<Milestone>
          label="마일스톤 추적"
          rows={data.milestones}
          rowKey={(m) => m.id}
          empty="마일스톤이 없습니다."
          columns={[
            {
              key: 'name',
              header: '마일스톤',
              render: (m) => (
                <span title={`${m.id} ${m.name}`}>
                  <span className={`pg-diamond is-${TONE[m.status]}`} aria-hidden="true" />
                  {m.name}
                </span>
              ),
            },
            { key: 'plan', header: 'Plan', width: 44, render: (m) => md(m.plan) },
            { key: 'actual', header: '실적·영향', width: 56, render: (m) => md(m.actual_or_forecast) },
            { key: 'delta', header: '차이', width: 36, align: 'right', render: (m) => (m.delta === null ? '—' : signed(m.delta, 0)) },
            { key: 'status', header: '상태', width: 80, align: 'right', render: (m) => <Badge tone={TONE[m.status]}>{statusText(m)}</Badge> },
          ]}
        />
      </div>
    </section>
  );
}
