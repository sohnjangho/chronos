import { Fragment, useEffect, useMemo, useState } from 'react';
import { FindPanel, ModelCell, modelsOf, PriceNote, RowNote, RowFoot, StrategySelect, usePicker, withModel, type ModelLists, type RowState } from './AssignmentParts';
import { llmApi } from './llmApi';
import { isRouter, PURPOSES, type Assignment, type Connection, type LlmError, type ModelInfo } from './model';
import { ErrorLine, toProblem } from './parts';
import ReindexDialog from './ReindexDialog';
import ReindexPanel, { reindexProblem } from './ReindexPanel';

/** 대화 줄의 목록: 연결의 전체 목록에서 임베딩 모델을 뺀다. */
function withoutEmbedding(lists: ModelLists, embedding: ModelLists): ModelLists {
  return Object.fromEntries(
    Object.entries(lists).map(([id, list]) => {
      const embed = new Set(modelsOf(embedding[Number(id)]).map((m) => m.id));
      return [id, 'models' in list ? { models: list.models.filter((m) => !embed.has(m.id)) } : list];
    }),
  );
}

/**
 * 연결마다 마지막으로 성공한 시험의 모델 목록(all), 그리고 서버가 거른 임베딩 모델(embedding, ?for=embedding —
 * 임베딩 여부는 이 목록으로만 안다). chat 은 all 에서 임베딩 모델을 뺀 것. 못 불러오면 서버 글을 둔다.
 */
function useModelLists(connections: Connection[] | null) {
  const [lists, setLists] = useState<ModelLists>({});
  const [embedding, setEmbedding] = useState<ModelLists>({});
  useEffect(() => {
    if (!connections) return;
    let live = true;
    for (const c of connections) {
      llmApi
        .models(c.id)
        .then((r) => live && setLists((l) => ({ ...l, [c.id]: { models: r.models } })))
        .catch((e) => live && setLists((l) => ({ ...l, [c.id]: { error: toProblem(e) } })));
    }
    llmApi
      .modelsFor('embedding')
      .then((r) => live && setEmbedding(Object.fromEntries(r.connections.map((c) => [c.connection_id, { models: c.models }]))))
      .catch((e) => live && setEmbedding(Object.fromEntries(connections.map((c) => [c.id, { error: toProblem(e) }]))));
    return () => {
      live = false;
    };
  }, [connections]);
  const chat = useMemo(() => withoutEmbedding(lists, embedding), [lists, embedding]);
  return { all: lists, chat, embedding };
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
  /** 임베딩 줄: 모델을 바꿔 저장했으면(다시 넣기 시작) 부른다. */
  onReindex?(): void;
}

/**
 * 줄 저장: 그 줄 하나만 보내고 결과를 그 줄에 둔다. 임베딩 줄의 503(뜻 검색 서버 꺼짐)은 오류가 아니라 상태(off),
 * 409 already_running 은 「이미 다시 넣는 중입니다.」.
 */
function useRowSave(draft: Assignment, onSaved: RowProps['onSaved'], embedding: boolean, onReindex?: () => void) {
  const [state, setState] = useState<RowState>({});
  async function save() {
    setState({ busy: true });
    try {
      onSaved((await llmApi.saveAssignment(draft)).items);
      setState({ done: true });
      onReindex?.();
    } catch (e) {
      const problem = embedding ? reindexProblem(e) : { error: toProblem(e) };
      setState('off' in problem ? { off: true } : { error: problem.error });
    }
  }
  return { state, setState, save };
}

/**
 * 배정 한 줄. 고친 줄만 [저장] 이 생기고, 저장은 그 줄 하나만 보낸다. 오류도 그 줄에 보인다.
 * 임베딩 줄에서 모델을 바꿔 저장하면 먼저 확인 창을 띄운다(자료를 전부 다시 넣으므로).
 */
function AssignmentRow({ item, connections, lists, onSaved, onReindex }: RowProps) {
  const [draft, setDraft] = useDraft(item, connections);
  const embedding = item.purpose === 'embedding';
  const changing = embedding && draft.model !== item.model;
  const { state, setState, save } = useRowSave(draft, onSaved, embedding, changing ? onReindex : undefined);
  const [asking, setAsking] = useState(false);
  const picker = usePicker(draft, lists, embedding);
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
          {!embedding && isRouter(draft.model) ? (
            <StrategySelect label={label} value={draft.routing_strategy} onPick={(s) => change({ routing_strategy: s })} />
          ) : (
            <span className="st-direct-pill" aria-hidden="true">
              직접 호출
            </span>
          )}
        </span>
      </div>
      {finding && <FindPanel label={label} models={picker.all} embedding={embedding} onPick={pickFound} />}
      <RowNote list={draft.connection_id === null ? undefined : lists[draft.connection_id]} current={picker.current} embedding={embedding} />
      {(dirty || state.error || state.done) && (
        <RowFoot state={state} dirty={dirty} canSave={canSave} onRevert={() => change(item)} onSave={changing ? () => setAsking(true) : save} />
      )}
      {asking && (
        <ReindexDialog
          from={item.model}
          to={draft.model}
          toInfo={picker.current}
          busy={!!state.busy}
          onCancel={() => setAsking(false)}
          onConfirm={async () => {
            await save();
            setAsking(false);
          }}
        />
      )}
    </div>
  );
}

/**
 * 작업별 모델 배정 표(6줄). 모델은 그 줄이 고른 연결의 불러온 목록에서 고르고, 라우터 모델만 기준을 고른다.
 * 임베딩 줄 바로 아래에 다시 넣기 상태를 펼친다.
 */
export default function AssignmentTable({ connections }: { connections: Connection[] | null }) {
  const [items, setItems] = useState<Assignment[] | null>(null);
  const [error, setError] = useState<LlmError | null>(null);
  const lists = useModelLists(connections);
  const [reindexTick, setReindexTick] = useState(0);
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
        items?.map((item) =>
          item.purpose === 'embedding' ? (
            <Fragment key={item.purpose}>
              <AssignmentRow item={item} connections={connections} lists={lists.embedding} onSaved={merge} onReindex={() => setReindexTick((t) => t + 1)} />
              <ReindexPanel tick={reindexTick} />
            </Fragment>
          ) : (
            <AssignmentRow key={item.purpose} item={item} connections={connections} lists={lists.chat} onSaved={merge} />
          ),
        )}
      <PriceNote models={Object.values(lists.all).flatMap(modelsOf)} />
    </div>
  );
}
