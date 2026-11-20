import { useEffect, useState } from 'react';
import { FindPanel, ListNote, ModelCell, RowFoot, StrategySelect, usePicker, withModel, type ModelLists, type RowState } from './AssignmentParts';
import { llmApi } from './llmApi';
import { isRouter, PURPOSES, type Assignment, type Connection, type LlmError, type ModelInfo } from './model';
import { ErrorLine, toProblem } from './parts';

/** 연결마다 마지막으로 성공한 시험의 모델 목록. 못 불러오면 서버 글을 둔다. */
function useModelLists(connections: Connection[] | null): ModelLists {
  const [lists, setLists] = useState<ModelLists>({});
  useEffect(() => {
    if (!connections) return;
    let live = true;
    for (const c of connections) {
      llmApi
        .models(c.id)
        .then((r) => live && setLists((l) => ({ ...l, [c.id]: { models: r.models } })))
        .catch((e) => live && setLists((l) => ({ ...l, [c.id]: { error: toProblem(e) } })));
    }
    return () => {
      live = false;
    };
  }, [connections]);
  return lists;
}

const same = (a: Assignment, b: Assignment) =>
  a.connection_id === b.connection_id && a.model === b.model && a.routing_strategy === b.routing_strategy;

/**
 * 줄의 고친 값. 서버 값(item)이나 연결 목록이 새로 오면 고치지 않은 줄만 새 값을 따라간다.
 * 고친 값이 지운 연결을 가리키면 버린다.
 */
function useDraft(item: Assignment, connections: Connection[]) {
  const [draft, setDraft] = useState(item);
  const [seen, setSeen] = useState({ item, connections });
  if (seen.item !== item || seen.connections !== connections) {
    setSeen({ item, connections });
    const edited = !same(draft, seen.item);
    const gone = draft.connection_id !== null && !connections.some((c) => c.id === draft.connection_id);
    if (!edited || gone) setDraft(item);
  }
  return [draft, setDraft] as const;
}

interface RowProps {
  item: Assignment;
  connections: Connection[];
  lists: ModelLists;
  onSaved(items: Assignment[]): void;
}

/** 줄 저장: 그 줄 하나만 보내고 결과를 그 줄에 둔다. */
function useRowSave(draft: Assignment, onSaved: RowProps['onSaved']) {
  const [state, setState] = useState<RowState>({});
  async function save() {
    setState({ busy: true });
    try {
      onSaved((await llmApi.saveAssignment(draft)).items);
      setState({ done: true });
    } catch (e) {
      setState({ error: toProblem(e) });
    }
  }
  return { state, setState, save };
}

/** 배정 한 줄. 고친 줄만 [저장] 이 생기고, 저장은 그 줄 하나만 보낸다. 오류도 그 줄에 보인다. */
function AssignmentRow({ item, connections, lists, onSaved }: RowProps) {
  const [draft, setDraft] = useDraft(item, connections);
  const { state, setState, save } = useRowSave(draft, onSaved);
  const picker = usePicker(draft, lists);
  const [finding, setFinding] = useState(false);
  const { label, desc } = PURPOSES[item.purpose];
  const dirty = !same(draft, item);
  const change = (patch: Partial<Assignment>) => {
    setDraft((d) => ({ ...d, ...patch }));
    setState({});
  };
  const pickFound = (m: ModelInfo) => {
    picker.setVendor(m.vendor);
    setFinding(false);
    change(withModel(draft, m.id));
  };
  const canSave = !state.busy && draft.model !== '' && draft.connection_id !== null;
  return (
    <div className="st-arow" role="group" aria-label={label}>
      <div className="st-arow-main">
        <span className="st-arow-what">
          <b>{label}</b>
          <span className="st-muted">{desc}</span>
        </span>
        <ModelCell label={label} draft={draft} connections={connections} picker={picker} finding={finding} onFind={() => setFinding((f) => !f)} onChange={change} />
        <span className="st-arow-std">
          {isRouter(draft.model) && <StrategySelect label={label} value={draft.routing_strategy} onPick={(s) => change({ routing_strategy: s })} />}
        </span>
      </div>
      {finding && <FindPanel label={label} models={picker.all} onPick={pickFound} />}
      <ListNote list={draft.connection_id === null ? undefined : lists[draft.connection_id]} />
      {(dirty || state.error || state.done) && (
        <RowFoot state={state} dirty={dirty} canSave={canSave} onRevert={() => change(item)} onSave={save} />
      )}
    </div>
  );
}

/** 작업별 모델 배정 표(4줄). 모델은 그 줄이 고른 연결의 불러온 목록에서 고르고, 라우터 모델만 기준을 고른다. */
export default function AssignmentTable({ connections }: { connections: Connection[] | null }) {
  const [items, setItems] = useState<Assignment[] | null>(null);
  const [error, setError] = useState<LlmError | null>(null);
  const lists = useModelLists(connections);
  // 연결 목록이 바뀌면(추가·삭제·시험) 배정도 다시 읽는다. 연결을 지우면 서버가 그 배정을 기본값으로 돌린다.
  useEffect(() => {
    if (!connections) return;
    let live = true;
    llmApi
      .assignments()
      .then((r) => live && setItems(r.items))
      .catch((e) => live && setError(toProblem(e)));
    return () => {
      live = false;
    };
  }, [connections]);
  const merge = (saved: Assignment[]) =>
    setItems((cur) => cur && cur.map((i) => saved.find((s) => s.purpose === i.purpose) ?? i));

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
        items?.map((item) => (
          <AssignmentRow key={item.purpose} item={item} connections={connections} lists={lists} onSaved={merge} />
        ))}
    </div>
  );
}
