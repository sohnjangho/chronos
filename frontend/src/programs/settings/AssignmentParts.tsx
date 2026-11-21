import { useMemo, useState } from 'react';
import Button from '../../shared/ui/Button';
import { isRouter, STRATEGIES, type Assignment, type Connection, type LlmError, type ModelInfo, type Strategy } from './model';
import { ModelFilterBar, useModelFilter } from './ModelFilters';
import { groupByVendor, modelLabel, priceAsOf, priceText, type VendorGroup } from './models';
import { ErrorLine } from './parts';
import { OFF_LINE } from './ReindexPanel';

/** 한 연결의 모델 목록: 불러온 목록, 또는 불러오지 못한 까닭. 아직 오지 않았으면 없음. */
export type ModelList = { models: ModelInfo[] } | { error: LlmError };
export type ModelLists = Record<number, ModelList>;

export const modelsOf = (list: ModelList | undefined): ModelInfo[] => (list && 'models' in list ? list.models : []);

/** 모델을 바꾸면 라우터는 기준을 두고(없으면 balanced), 라우터가 아니면 기준을 뺀다. */
export const withModel = (d: Assignment, model: string): Partial<Assignment> => ({
  model,
  routing_strategy: isRouter(model) ? (d.routing_strategy ?? 'balanced') : null,
});

const findLimit = 50;

/**
 * 줄의 고르기 상태. 고를 모델(대화 줄은 대화용, 임베딩 줄은 받은 목록 전부)을 업체별로 묶고, 보일 업체는
 * 사용자가 고른 업체 → 지금 모델의 업체 → 첫 업체 차례로 정한다. 업체만 바꿔서는 배정이 바뀌지 않는다.
 */
export function usePicker(draft: Assignment, lists: ModelLists, embedding = false) {
  const all = modelsOf(lists[draft.connection_id ?? -1]);
  const fitGroups = useMemo(() => groupByVendor(embedding ? all : all.filter((m) => m.chat)), [all, embedding]);
  const current = all.find((m) => m.id === draft.model);
  // 지금 모델의 업체에 고를 모델이 없으면 빈 묶음으로 더한다(업체 칸이 엉뚱한 업체를 보이지 않게).
  const missing = current && !fitGroups.some((g) => g.vendor === current.vendor);
  const groups = missing ? [...fitGroups, { vendor: current.vendor, vendor_name: current.vendor_name, models: [] }] : fitGroups;
  const [chosen, setVendor] = useState<string | null>(null);
  const vendor = groups.some((g) => g.vendor === chosen) ? (chosen as string) : (current?.vendor ?? groups[0]?.vendor ?? '');
  const vendorModels = groups.find((g) => g.vendor === vendor)?.models ?? [];
  return { all, groups, current, vendor, setVendor, vendorModels };
}
export type Picker = ReturnType<typeof usePicker>;

function VendorSelect({ label, groups, value, onPick }: { label: string; groups: VendorGroup[]; value: string; onPick(v: string): void }) {
  return (
    <select className="st-select st-select-vendor" aria-label={`${label} 업체`} value={value} onChange={(e) => onPick(e.target.value)}>
      {groups.map((g) => (
        <option key={g.vendor} value={g.vendor}>
          {`${g.vendor_name} (${g.models.length})`}
        </option>
      ))}
    </select>
  );
}

/** 「가격 기준: Liner 공개 가격표(날짜)」. 가격이 있는 모델이 하나도 없으면 보이지 않는다. */
export function PriceNote({ models }: { models: ModelInfo[] }) {
  const asOf = priceAsOf(models);
  return asOf ? <p className="st-muted st-price-note">{`가격 기준: Liner 공개 가격표(${asOf})`}</p> : null;
}

/** 고른 업체의 대화용 모델. 지금 값이 목록에 없으면(다른 업체·목록에 없는 모델) 그 값을 그대로 보인다. */
function ModelSelect({ label, value, picker, onPick }: { label: string; value: string; picker: Picker; onPick(m: string): void }) {
  const { vendorModels, current } = picker;
  const extra = value !== '' && !vendorModels.some((m) => m.id === value);
  return (
    <select className="st-select st-select-model" aria-label={`${label} 모델`} value={value} onChange={(e) => onPick(e.target.value)}>
      {value === '' && (
        <option value="" disabled>
          모델 고르기
        </option>
      )}
      {extra && <option value={value}>{current ? `${current.vendor_name} · ${modelLabel(current)}` : value}</option>}
      {vendorModels.map((m) => (
        <option key={m.id} value={m.id}>
          {modelLabel(m)}
        </option>
      ))}
    </select>
  );
}

function ConnectionSelect({ label, value, connections, onPick }: { label: string; value: number | null; connections: Connection[]; onPick(id: number): void }) {
  return (
    <select className="st-select st-select-conn" aria-label={`${label} 연결`} value={value ?? ''} onChange={(e) => onPick(Number(e.target.value))}>
      {connections.map((c) => (
        <option key={c.id} value={c.id}>
          {c.name}
        </option>
      ))}
    </select>
  );
}

/** 저장된 기준이 없으면 「선택 안 함」을 보인다(보이는 값 = 저장되는 값). */
export function StrategySelect({ label, value, onPick }: { label: string; value: Strategy | null; onPick(s: Strategy): void }) {
  return (
    <select className="st-select" aria-label={`${label} 기준`} value={value ?? ''} onChange={(e) => onPick(e.target.value as Strategy)}>
      {value === null && <option value="">선택 안 함</option>}
      {STRATEGIES.map((s) => (
        <option key={s.value} value={s.value}>
          {s.label}
        </option>
      ))}
    </select>
  );
}

interface CellProps {
  label: string;
  draft: Assignment;
  connections: Connection[];
  picker: Picker;
  finding: boolean;
  onFind(): void;
  onChange(patch: Partial<Assignment>): void;
}

/** 연결(둘 이상일 때) → 업체 → 모델 · [찾기] 를 한 가로줄로 정렬하고, 가격은 아래 작은 한 줄로 보인다. */
export function ModelCell({ label, draft, connections, picker, finding, onFind, onChange }: CellProps) {
  return (
    <div className="st-arow-model">
      <div className="st-arow-controls">
        {connections.length > 1 && (
          <ConnectionSelect
            label={label}
            value={draft.connection_id}
            connections={connections}
            onPick={(id) => onChange({ connection_id: id, model: '', routing_strategy: null })}
          />
        )}
        {picker.groups.length > 0 && <VendorSelect label={label} groups={picker.groups} value={picker.vendor} onPick={picker.setVendor} />}
        <ModelSelect label={label} value={draft.model} picker={picker} onPick={(m) => onChange(withModel(draft, m))} />
        <Button aria-label={`${label} 모델 찾기`} aria-expanded={finding} disabled={picker.all.length === 0} onClick={onFind}>
          찾기
        </Button>
      </div>
      {picker.current?.price && <span className="st-price">{priceText(picker.current.price)}</span>}
    </div>
  );
}

/** 모든 모델에서 찾기·거르개로 고른다. 고르면 업체와 모델이 함께 정해진다. 임베딩 줄은 「대화용만」이 없다. */
export function FindPanel({ label, models, embedding = false, onPick }: { label: string; models: ModelInfo[]; embedding?: boolean; onPick(m: ModelInfo): void }) {
  const { filter, setFilter, results, facets } = useModelFilter(models, !embedding);
  const shown = results.slice(0, findLimit);
  return (
    <div className="st-find" role="group" aria-label={`${label} 모델 찾기`}>
      <ModelFilterBar filter={filter} onChange={setFilter} facets={facets} count={results.length} autoFocus chatToggle={!embedding} />
      <ul className="st-find-list">
        {shown.map((m) => (
          <li key={m.id}>
            <button type="button" className="st-find-item" title={m.id} onClick={() => onPick(m)}>
              <span className="st-find-name">{`${m.vendor_name} · ${modelLabel(m)}`}</span>
              {m.price && <span className="st-price">{priceText(m.price)}</span>}
            </button>
          </li>
        ))}
      </ul>
      {results.length > shown.length && (
        <p className="st-muted">{`${results.length}개 가운데 앞 ${shown.length}개만 보입니다. 더 좁혀 주세요.`}</p>
      )}
    </div>
  );
}

function ListNote({ list, embedding }: { list: ModelList | undefined; embedding: boolean }) {
  if (!list) return null;
  if ('error' in list) return <ErrorLine error={list.error} />;
  // 임베딩 여부는 Task 51 뒤의 연결 시험부터 남는다. 그 전에 시험한 연결은 다시 시험해야 보인다.
  if (embedding) return list.models.length === 0 ? <p className="st-muted">이 연결에서 임베딩 모델을 찾지 못했습니다. 연결 테스트를 다시 해 주세요.</p> : null;
  if (list.models.length === 0) return <p className="st-muted">이 연결에 불러온 모델이 없습니다. 연결 테스트를 먼저 해 주세요.</p>;
  if (!list.models.some((m) => m.chat)) return <p className="st-muted">대화용 모델이 없습니다. 「대화용만」을 끄면 전체가 보입니다.</p>;
  return null;
}

/**
 * 줄 아래 알림: 대화 줄에서 대화용이 아닌 모델을 골랐으면 경고(고를 수는 있다), 그리고 고른 연결의 목록이
 * 비었거나 · 못 불러왔거나 · 고를 모델이 하나도 없을 때의 안내.
 */
export function RowNote({ list, current, embedding = false }: { list: ModelList | undefined; current: ModelInfo | undefined; embedding?: boolean }) {
  return (
    <>
      {!embedding && current && !current.chat && <p className="st-warn">대화용이 아닌 모델입니다. 에이전트가 쓰지 못할 수 있습니다.</p>}
      <ListNote list={list} embedding={embedding} />
    </>
  );
}

export interface RowState {
  busy?: boolean;
  done?: boolean;
  error?: LlmError;
  /** 임베딩 줄 저장이 503(뜻 검색 서버 꺼짐)으로 안 됨 — 오류가 아니라 상태. */
  off?: boolean;
}

export function RowFoot({ state, dirty, canSave, onRevert, onSave }: { state: RowState; dirty: boolean; canSave: boolean; onRevert(): void; onSave(): void }) {
  return (
    <div className="st-arow-foot">
      <ErrorLine error={state.error} />
      {state.off && <p className="st-muted st-wrap" role="status">{`${OFF_LINE} 임베딩 모델은 바꾸지 않았습니다.`}</p>}
      {state.done && !dirty && <span className="st-ok">저장했습니다.</span>}
      {dirty && (
        <>
          <span className="st-gap" />
          <Button onClick={onRevert}>되돌리기</Button>
          <Button variant="primary" onClick={onSave} disabled={!canSave}>
            저장
          </Button>
        </>
      )}
    </div>
  );
}
