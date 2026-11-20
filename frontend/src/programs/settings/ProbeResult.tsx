import { useState } from 'react';
import Table, { type Column } from '../../shared/ui/Table';
import type { ModelInfo, Probe } from './model';
import { ModelFilterBar, useModelFilter } from './ModelFilters';
import { contextText, groupByVendor, shortName, type VendorGroup } from './models';
import { ErrorLine } from './parts';

const COLUMNS: Column<ModelInfo>[] = [
  { key: 'name', header: '이름', render: (m) => <span title={m.name}>{shortName(m)}</span> },
  { key: 'id', header: 'ID', render: (m) => <span title={m.id}>{m.id}</span> },
  { key: 'context', header: '문맥 길이', align: 'right', render: (m) => contextText(m.context_length) },
];

/** 업체 한 묶음. 접혀 있고, 누르면 이름 · ID · 문맥 길이 표가 열린다. 찾는 중이면 열어 둔다. */
function VendorGroupView({ group, forceOpen }: { group: VendorGroup; forceOpen: boolean }) {
  const [open, setOpen] = useState(false);
  const shown = forceOpen || open;
  return (
    <section className="st-vgroup">
      <button type="button" className="st-vgroup-head" aria-expanded={shown} onClick={() => setOpen(!shown)}>
        <span>{group.vendor_name}</span> <span className="st-muted">{group.models.length}개</span>
      </button>
      {shown && <Table label={`${group.vendor_name} 모델`} columns={COLUMNS} rows={group.models} rowKey={(m) => m.id} />}
    </section>
  );
}

/** 요약 줄 + 찾기·거르개 + 업체별 묶음. 원문 목록을 늘어놓지 않는다. */
function ModelBrowser({ probe }: { probe: Probe }) {
  const { filter, setFilter, results, facets } = useModelFilter(probe.models);
  const chat = probe.models.filter((m) => m.chat).length;
  const vendors = new Set(probe.models.map((m) => m.vendor)).size;
  const searching = filter.query.trim() !== '' || filter.vendors.length > 0 || filter.linerRouters;
  return (
    <>
      <div className="st-probe st-probe-ok" role="status">
        {`연결됨 · ${probe.latency_ms}ms · 모델 ${probe.models.length}개 (대화용 ${chat}개) · 업체 ${vendors}곳`}
      </div>
      <ModelFilterBar filter={filter} onChange={setFilter} facets={facets} count={results.length} />
      <div className="st-vgroups">
        {groupByVendor(results).map((g) => (
          <VendorGroupView key={g.vendor} group={g} forceOpen={searching} />
        ))}
        {results.length === 0 && <p className="st-muted">찾는 모델이 없습니다.</p>}
      </div>
    </>
  );
}

/** 연결 시험 결과: 성공이면 요약과 업체별 모델, 실패면 서버의 글과 코드. 마법사와 카드가 함께 쓴다. */
export default function ProbeResult({ probe }: { probe: Probe }) {
  if (!probe.ok) {
    return (
      <div className="st-probe st-probe-fail">
        <div>
          <b>연결하지 못했습니다</b>
          {` · 응답 ${probe.latency_ms}ms`}
        </div>
        <ErrorLine error={probe.error ?? { code: 'unknown', message: '원인을 알 수 없습니다.' }} />
      </div>
    );
  }
  return <ModelBrowser probe={probe} />;
}
