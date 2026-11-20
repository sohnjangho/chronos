import { useState } from 'react';
import Button from '../../shared/ui/Button';
import Table, { type Column } from '../../shared/ui/Table';
import type { ModelInfo, Probe } from './model';
import { ModelFilterBar, useModelFilter } from './ModelFilters';
import { contextText, groupByVendor, priceShort, priceText, shortName, type VendorGroup } from './models';
import { PriceNote } from './AssignmentParts';
import { ErrorLine } from './parts';

const COLUMNS: Column<ModelInfo>[] = [
  { key: 'name', header: '이름', render: (m) => <span title={m.name}>{shortName(m)}</span> },
  { key: 'id', header: 'ID', render: (m) => <span title={m.id}>{m.id}</span> },
  { key: 'context', header: '문맥 길이', align: 'right', render: (m) => contextText(m.context_length) },
  { key: 'price', header: '입력 / 출력 ($/1M)', align: 'right', render: (m) => <span title={priceText(m.price) || undefined}>{priceShort(m.price) || '-'}</span> },
];

/** 열린 묶음이 한 번에 보이는 줄 수. 넘으면 「N개 더 보기」. */
const PAGE = 50;

/**
 * 업체 한 묶음. 처음에는 접혀 있고, 찾는 중이면 열린 채로 시작한다. 찾는 중에도 사용자가 접고 열 수 있다.
 * 열면 이름 · ID · 문맥 길이 표를 50줄씩 보인다.
 */
function VendorGroupView({ group, openByDefault }: { group: VendorGroup; openByDefault: boolean }) {
  const [choice, setChoice] = useState<boolean | null>(null);
  const [limit, setLimit] = useState(PAGE);
  const shown = choice ?? openByDefault;
  const rest = group.models.length - limit;
  return (
    <section className="st-vgroup">
      <button type="button" className="st-vgroup-head" aria-expanded={shown} onClick={() => setChoice(!shown)}>
        <span>{group.vendor_name}</span> <span className="st-muted">{group.models.length}개</span>
      </button>
      {shown && (
        <>
          <Table label={`${group.vendor_name} 모델`} columns={COLUMNS} rows={group.models.slice(0, limit)} rowKey={(m) => m.id} />
          {rest > 0 && (
            <Button className="st-more" onClick={() => setLimit(limit + PAGE)}>
              {`${rest}개 더 보기`}
            </Button>
          )}
        </>
      )}
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
          <VendorGroupView key={g.vendor} group={g} openByDefault={searching} />
        ))}
        {results.length === 0 && <p className="st-muted">찾는 모델이 없습니다.</p>}
      </div>
      <PriceNote models={probe.models} />
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
