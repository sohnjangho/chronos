// WBS 묶음별: 가중치 · 진도 막대(실적 채움 + 계획 위치 눈금) · 계획 · 실적 · 차이(%p). 값은 서버 값.
import Table from '../../shared/ui/Table';
import { pct, signed } from './format';
import type { ProgressData } from './progressApi';

type Row = ProgressData['wbs'][number];

const clamp = (v: number) => Math.min(Math.max(v, 0), 100);

function Track({ row }: { row: Row }) {
  return (
    <div className="pg-track" aria-hidden="true">
      <div className={`pg-track-fill${row.actual < row.plan ? ' is-behind' : ''}`} style={{ width: `${clamp(row.actual)}%` }} />
      <div className="pg-track-plan" style={{ left: `${clamp(row.plan)}%` }} />
    </div>
  );
}

export default function WbsTable({ data }: { data: ProgressData }) {
  return (
    <section className="pg-card pg-low-card" aria-label="WBS 묶음">
      <div className="pg-card-head">
        <h3 className="pg-card-title">WBS 묶음별</h3>
        <span className="pg-legend-item"><span className="pg-swatch is-bar-actual-solid" />실적</span>
        <span className="pg-legend-item"><span className="pg-swatch is-tick" />계획 위치</span>
      </div>
      <div className="pg-card-body">
        <Table<Row>
          label="WBS 묶음별"
          rows={data.wbs}
          rowKey={(r) => r.code}
          empty="Plan 이 있는 WBS 묶음이 없습니다."
          columns={[
            { key: 'name', header: 'WBS', width: 92, render: (r) => <span title={`${r.code} ${r.name}`}>{`${r.code} ${r.name}`}</span> },
            { key: 'weight', header: '가중치', width: 44, align: 'right', render: (r) => `${(r.weight * 100).toFixed(1)}%` },
            { key: 'track', header: '진도', render: (r) => <Track row={r} /> },
            { key: 'plan', header: '계획', width: 40, align: 'right', render: (r) => pct(r.plan) },
            { key: 'actual', header: '실적', width: 40, align: 'right', render: (r) => <b>{pct(r.actual)}</b> },
            { key: 'diff', header: '차이', width: 48, align: 'right', render: (r) => <span className={r.diff < 0 ? 'is-danger' : 'pg-muted'}>{signed(r.diff)}</span> },
          ]}
        />
      </div>
    </section>
  );
}
