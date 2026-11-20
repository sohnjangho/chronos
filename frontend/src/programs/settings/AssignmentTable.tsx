import { useEffect, useState } from 'react';
import Button from '../../shared/ui/Button';
import { llmApi } from './llmApi';
import { isRouter, PURPOSES, STRATEGIES, type Assignment, type Connection, type LlmError, type Strategy } from './model';
import { ErrorLine, toProblem } from './parts';

type ModelLists = Record<number, string[]>;

/** 연결마다 마지막으로 성공한 시험의 모델 목록. */
function useModelLists(connections: Connection[] | null): ModelLists {
  const [lists, setLists] = useState<ModelLists>({});
  useEffect(() => {
    if (!connections) return;
    let live = true;
    for (const c of connections) {
      llmApi
        .models(c.id)
        .then((r) => live && setLists((l) => ({ ...l, [c.id]: r.models })))
        .catch(() => {});
    }
    return () => {
      live = false;
    };
  }, [connections]);
  return lists;
}

/** 모델을 바꾸면 라우터는 기준을 두고(없으면 balanced), 라우터가 아니면 기준을 뺀다. */
const withModel = (d: Assignment, model: string): Partial<Assignment> => ({
  model,
  routing_strategy: isRouter(model) ? (d.routing_strategy ?? 'balanced') : null,
});

const same = (a: Assignment, b: Assignment) =>
  a.connection_id === b.connection_id && a.model === b.model && a.routing_strategy === b.routing_strategy;

interface RowProps {
  item: Assignment;
  connections: Connection[];
  lists: ModelLists;
  onSaved(items: Assignment[]): void;
}

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

function StrategySelect({ label, value, onPick }: { label: string; value: Strategy | null; onPick(s: Strategy): void }) {
  return (
    <select className="st-select" aria-label={`${label} 기준`} value={value ?? 'balanced'} onChange={(e) => onPick(e.target.value as Strategy)}>
      {STRATEGIES.map((s) => (
        <option key={s} value={s}>
          {s}
        </option>
      ))}
    </select>
  );
}

interface RowState {
  busy?: boolean;
  done?: boolean;
  error?: LlmError;
}

function RowFoot({ state, dirty, canSave, onRevert, onSave }: { state: RowState; dirty: boolean; canSave: boolean; onRevert(): void; onSave(): void }) {
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

/** 연결(둘 이상일 때)과 모델. 연결을 바꾸면 그 연결의 목록에서 모델을 다시 고른다. */
function ModelCell({ label, draft, connections, lists, onChange }: {
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
        models={lists[draft.connection_id ?? -1] ?? []}
        onPick={(m) => onChange(withModel(draft, m))}
      />
    </span>
  );
}

/** 배정 한 줄. 고친 줄만 [저장] 이 생기고, 저장은 그 줄 하나만 보낸다. 오류도 그 줄에 보인다. */
function AssignmentRow({ item, connections, lists, onSaved }: RowProps) {
  const [draft, setDraft] = useState(item);
  const [state, setState] = useState<RowState>({});
  const { label, desc } = PURPOSES[item.purpose];
  const dirty = !same(draft, item);
  const change = (patch: Partial<Assignment>) => {
    setDraft((d) => ({ ...d, ...patch }));
    setState({});
  };
  async function save() {
    setState({ busy: true });
    try {
      onSaved((await llmApi.saveAssignment(draft)).items);
      setState({ done: true });
    } catch (e) {
      setState({ error: toProblem(e) });
    }
  }
  const canSave = !state.busy && draft.model !== '' && draft.connection_id !== null;
  return (
    <div className="st-arow" role="group" aria-label={label}>
      <div className="st-arow-main">
        <span className="st-arow-what">
          <b>{label}</b>
          <span className="st-muted">{desc}</span>
        </span>
        <ModelCell label={label} draft={draft} connections={connections} lists={lists} onChange={change} />
        <span className="st-arow-std">
          {isRouter(draft.model) && (
            <StrategySelect label={label} value={draft.routing_strategy} onPick={(s) => change({ routing_strategy: s })} />
          )}
        </span>
      </div>
      {(dirty || state.error || state.done) && (
        <RowFoot state={state} dirty={dirty} canSave={canSave} onRevert={() => change(item)} onSave={save} />
      )}
    </div>
  );
}

/** 작업별 모델 배정 표(4줄). 모델은 그 줄이 고른 연결의 불러온 목록에서 고르고, 라우터 모델만 기준을 고른다. */
export default function AssignmentTable({ connections }: { connections: Connection[] | null }) {
  const [data, setData] = useState<{ items: Assignment[]; seq: number } | null>(null);
  const [error, setError] = useState<LlmError | null>(null);
  const lists = useModelLists(connections);
  // 연결 목록이 바뀌면(추가·삭제·시험) 배정도 다시 읽는다. 연결을 지우면 서버가 그 배정을 기본값으로 돌린다.
  useEffect(() => {
    if (!connections) return;
    let live = true;
    llmApi
      .assignments()
      .then((r) => live && setData((d) => ({ items: r.items, seq: (d?.seq ?? 0) + 1 })))
      .catch((e) => live && setError(toProblem(e)));
    return () => {
      live = false;
    };
  }, [connections]);
  const merge = (saved: Assignment[]) =>
    setData((d) => d && { ...d, items: d.items.map((i) => saved.find((s) => s.purpose === i.purpose) ?? i) });

  if (connections?.length === 0) {
    return <p className="st-muted">연결이 없습니다. 먼저 「LLM 연결」에서 연결을 추가해 주세요.</p>;
  }
  return (
    <div className="st-assign">
      <ErrorLine error={error} />
      <div className="st-arow-main st-arow-head" aria-hidden="true">
        <span className="st-arow-what">에이전트가 하는 일</span>
        <span className="st-arow-model">모델 · 라우터</span>
        <span className="st-arow-std">기준</span>
      </div>
      {connections &&
        data?.items.map((item) => (
          <AssignmentRow key={`${item.purpose}:${data.seq}`} item={item} connections={connections} lists={lists} onSaved={merge} />
        ))}
    </div>
  );
}
