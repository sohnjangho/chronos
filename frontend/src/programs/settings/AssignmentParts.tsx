import Button from '../../shared/ui/Button';
import { isRouter, STRATEGIES, type Assignment, type Connection, type LlmError, type Strategy } from './model';
import { ErrorLine } from './parts';

/** 한 연결의 모델 목록: 불러온 목록, 또는 불러오지 못한 까닭. 아직 오지 않았으면 없음. */
export type ModelList = { models: string[] } | { error: LlmError };
export type ModelLists = Record<number, ModelList>;

export const modelsOf = (list: ModelList | undefined): string[] => (list && 'models' in list ? list.models : []);

/** 모델을 바꾸면 라우터는 기준을 두고(없으면 balanced), 라우터가 아니면 기준을 뺀다. */
export const withModel = (d: Assignment, model: string): Partial<Assignment> => ({
  model,
  routing_strategy: isRouter(model) ? (d.routing_strategy ?? 'balanced') : null,
});

function ModelSelect({ label, value, models, onPick }: { label: string; value: string; models: string[]; onPick(m: string): void }) {
  return (
    <select className="st-select" aria-label={`${label} 모델`} value={value} onChange={(e) => onPick(e.target.value)}>
      {value === '' && (
        <option value="" disabled>
          모델 고르기
        </option>
      )}
      {value !== '' && !models.includes(value) && <option value={value}>{value}</option>}
      {models.map((m) => (
        <option key={m} value={m}>
          {m}
        </option>
      ))}
    </select>
  );
}

function ConnectionSelect({ label, value, connections, onPick }: { label: string; value: number | null; connections: Connection[]; onPick(id: number): void }) {
  return (
    <select className="st-select" aria-label={`${label} 연결`} value={value ?? ''} onChange={(e) => onPick(Number(e.target.value))}>
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

/** 연결(둘 이상일 때)과 모델. 연결을 바꾸면 그 연결의 목록에서 모델을 다시 고른다. */
export function ModelCell({ label, draft, connections, lists, onChange }: {
  label: string;
  draft: Assignment;
  connections: Connection[];
  lists: ModelLists;
  onChange(patch: Partial<Assignment>): void;
}) {
  return (
    <span className="st-arow-model">
      {connections.length > 1 && (
        <ConnectionSelect
          label={label}
          value={draft.connection_id}
          connections={connections}
          onPick={(id) => onChange({ connection_id: id, model: '', routing_strategy: null })}
        />
      )}
      <ModelSelect
        label={label}
        value={draft.model}
        models={modelsOf(lists[draft.connection_id ?? -1])}
        onPick={(m) => onChange(withModel(draft, m))}
      />
    </span>
  );
}

/** 고른 연결의 목록이 비었거나 못 불러왔을 때 그 줄에 알린다. */
export function ListNote({ list }: { list: ModelList | undefined }) {
  if (!list) return null;
  if ('error' in list) return <ErrorLine error={list.error} />;
  if (list.models.length > 0) return null;
  return <p className="st-muted">이 연결에 불러온 모델이 없습니다. 연결 테스트를 먼저 해 주세요.</p>;
}

export interface RowState {
  busy?: boolean;
  done?: boolean;
  error?: LlmError;
}

export function RowFoot({ state, dirty, canSave, onRevert, onSave }: { state: RowState; dirty: boolean; canSave: boolean; onRevert(): void; onSave(): void }) {
  return (
    <div className="st-arow-foot">
      <ErrorLine error={state.error} />
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
