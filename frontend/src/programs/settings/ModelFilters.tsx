import { useMemo, useState } from 'react';
import Button from '../../shared/ui/Button';
import type { ModelInfo } from './model';
import { DEFAULT_FILTER, filterModels, isDefaultFilter, vendorFacets, type ModelFilter } from './models';

/** 찾기·거르개 상태와 그 결과. */
export function useModelFilter(models: ModelInfo[]) {
  const [filter, setFilter] = useState<ModelFilter>(DEFAULT_FILTER);
  const results = useMemo(() => filterModels(models, filter), [models, filter]);
  const facets = useMemo(() => vendorFacets(models, filter), [models, filter]);
  return { filter, setFilter, results, facets };
}

type Facets = ReturnType<typeof vendorFacets>;

/** 업체 여럿 고르기. 단추를 누르면 업체마다 수가 붙은 체크 목록이 열린다. */
function VendorMenu({ facets, chosen, onChange }: { facets: Facets; chosen: string[]; onChange(v: string[]): void }) {
  const [open, setOpen] = useState(false);
  const toggle = (vendor: string) =>
    onChange(chosen.includes(vendor) ? chosen.filter((v) => v !== vendor) : [...chosen, vendor]);
  return (
    <div className="st-vendor-menu">
      <Button aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        {chosen.length ? `업체: ${chosen.length}곳` : '업체: 전체'}
      </Button>
      {open && (
        <div className="st-vendor-list" role="group" aria-label="업체 고르기">
          {facets.map((f) => (
            <label key={f.vendor} className="st-check">
              <input type="checkbox" checked={chosen.includes(f.vendor)} onChange={() => toggle(f.vendor)} />
              {f.vendor_name} <span className="st-muted">{f.count}</span>
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

interface BarProps {
  filter: ModelFilter;
  onChange(f: ModelFilter): void;
  facets: Facets;
  count: number;
  autoFocus?: boolean;
}

/** 찾기 칸 + 업체 · 문맥 길이 · 대화용만 · Liner 라우터만, 찾은 수, 한 번에 지우기. */
export function ModelFilterBar({ filter, onChange, facets, count, autoFocus }: BarProps) {
  const set = (patch: Partial<ModelFilter>) => onChange({ ...filter, ...patch });
  return (
    <div className="st-filters">
      <input
        type="search"
        className="st-search"
        aria-label="모델 찾기"
        placeholder="모델 찾기 (이름 · ID · 업체)"
        autoFocus={autoFocus}
        value={filter.query}
        onChange={(e) => set({ query: e.target.value })}
      />
      <div className="st-filter-row">
        <VendorMenu facets={facets} chosen={filter.vendors} onChange={(vendors) => set({ vendors })} />
        <span className="st-muted" aria-hidden="true">
          문맥
        </span>
        <select
          className="st-select st-select-auto"
          aria-label="문맥 길이"
          value={filter.minContext}
          onChange={(e) => set({ minContext: Number(e.target.value) })}
        >
          <option value={0}>전체</option>
          <option value={128_000}>128K 이상</option>
          <option value={1_000_000}>1M 이상</option>
        </select>
        <label className="st-check">
          <input type="checkbox" checked={filter.chatOnly} onChange={(e) => set({ chatOnly: e.target.checked })} />
          대화용만
        </label>
        <label className="st-check">
          <input type="checkbox" checked={filter.linerRouters} onChange={(e) => set({ linerRouters: e.target.checked })} />
          Liner 라우터만
        </label>
        <span className="st-gap" />
        <output className="st-count" aria-label="찾은 모델 수">
          {count}개
        </output>
        <Button onClick={() => onChange(DEFAULT_FILTER)} disabled={isDefaultFilter(filter)}>
          필터 지우기
        </Button>
      </div>
    </div>
  );
}
