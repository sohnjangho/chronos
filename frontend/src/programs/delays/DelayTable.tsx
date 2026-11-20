// 지연 사건 표: 발생 · 사건(원인) · 대상 액티비티 · 책임 · 일수 · 여유 흡수 · 준공 영향 · 상태. 줄을 누르면 오른쪽에 자세히.
// 「분석 필요」는 쓰지 않는다(stale 은 응답에서 늘 false). 일정에 넣지 않은 사건의 몫은 「—」.
import Badge from '../../shared/ui/Badge';
import Table, { type Column } from '../../shared/ui/Table';
import type { DelayEvent } from './delaysApi';
import { dot, respOf, signed, SOURCE_LABEL, statusLabel } from './format';

const share = (e: DelayEvent, pick: (i: NonNullable<DelayEvent['impact']>) => number) =>
  e.impact?.applied ? signed(pick(e.impact)) : '—';

const COLUMNS: Column<DelayEvent>[] = [
  { key: 'start', header: '발생', width: 92, render: (e) => dot(e.start_date) },
  {
    key: 'cause',
    header: '사건(원인)',
    render: (e) => (
      <span className="dl-cause" title={e.cause}>
        <b>{e.cause}</b>
        {SOURCE_LABEL[e.source] && <span className="dl-muted">{` · ${SOURCE_LABEL[e.source]}`}</span>}
      </span>
    ),
  },
  { key: 'activity', header: '대상 액티비티', width: 150, render: (e) => <span title={`${e.activity_id} ${e.activity_name}`}>{`${e.activity_id} ${e.activity_name}`}</span> },
  { key: 'resp', header: '책임', width: 86, render: (e) => <Badge tone={respOf(e.responsibility).tone}>{respOf(e.responsibility).label}</Badge> },
  { key: 'days', header: '일수', width: 56, align: 'right', render: (e) => String(e.days) },
  { key: 'absorbed', header: '여유 흡수', width: 76, align: 'right', render: (e) => (e.impact?.applied ? String(e.impact.absorbed) : '—') },
  {
    key: 'impact',
    header: '준공 영향',
    width: 76,
    align: 'right',
    render: (e) => <b className={(e.impact?.finish_delta ?? 0) > 0 ? 'is-danger' : undefined}>{share(e, (i) => i.finish_delta)}</b>,
  },
  { key: 'status', header: '상태', width: 88, render: (e) => <Badge tone={e.status === 'open' ? 'warning' : 'success'}>{statusLabel(e)}</Badge> },
];

interface Props {
  events: DelayEvent[];
  filtered: boolean;
  selectedId: number | null;
  onSelect: (e: DelayEvent) => void;
}

export default function DelayTable({ events, filtered, selectedId, onSelect }: Props) {
  return (
    <div className="dl-table-wrap">
      <Table
        label="지연 사건"
        columns={COLUMNS}
        rows={events}
        rowKey={(e) => String(e.id)}
        selectedKey={selectedId === null ? undefined : String(selectedId)}
        onRowClick={onSelect}
        empty={filtered ? '맞는 사건이 없습니다.' : '기록한 지연 사건이 없습니다.'}
      />
    </div>
  );
}
