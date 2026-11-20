import { useEffect, useMemo, useState } from 'react';
import { useCurrentSchedule } from '../../os/currentSchedule';
import type { ProgramProps } from '../../os/registry';
import { useUiContext } from '../../os/uiContext';
import { useWindows } from '../../os/windowStore';
import type { Cond, CondView } from './condApi';
import { useConditionsModel, type ConditionsModel } from './condStore';
import { allConds, condLabel, LAYERS, matches, STATE_LABEL, type StateFilter } from './labels';
import LayerColumn from './LayerColumn';
import PreviewBar from './PreviewBar';
import './conditions.css';

const NO_SCHEDULE = '일정을 먼저 고르세요. 메뉴바에서 현장을 고르면 그 일정의 조건이 보입니다.';

function positiveId(raw: string | undefined): number | null {
  const n = Number(raw);
  return Number.isInteger(n) && n > 0 ? n : null;
}

/** 상태 고르기(수 포함) + 찾기. 고른 것과 찾는 글로 모든 칸을 거른다. */
function Filters({ shown, state, setState, query, setQuery }: {
  shown: CondView;
  state: StateFilter;
  setState(s: StateFilter): void;
  query: string;
  setQuery(q: string): void;
}) {
  const off = allConds(shown).filter((c) => c.state === 'off').length;
  const chips: [StateFilter, string][] = [
    ['all', '전체'],
    ['passed', `${STATE_LABEL.passed} ${shown.summary.passed}`],
    ['violated', `${STATE_LABEL.violated} ${shown.summary.violated}`],
    ['uncheckable', `${STATE_LABEL.uncheckable} ${shown.summary.uncheckable}`],
    ['off', `${STATE_LABEL.off} ${off}`],
  ];
  return (
    <div className="cd-filters">
      <div className="cd-chips" role="radiogroup" aria-label="상태로 거르기">
        {chips.map(([value, label]) => (
          <button key={value} type="button" role="radio" aria-checked={state === value} className={`cd-chip is-${value}`} onClick={() => setState(value)}>
            {label}
          </button>
        ))}
      </div>
      {shown.invalid.length > 0 && <span className="cd-invalid">{`읽을 수 없는 조건 ${shown.invalid.length}개 (점검하지 않음)`}</span>}
      <span className="cd-gap" />
      <input className="cd-search" type="search" aria-label="조건 찾기" placeholder="조건 찾기" value={query} onChange={(e) => setQuery(e.target.value)} />
    </div>
  );
}

function Columns({ model, shown, state, query }: { model: ConditionsModel; shown: CondView; state: StateFilter; query: string }) {
  const saved = useMemo(() => new Map(model.view ? allConds(model.view).map((c): [string, Cond] => [c.id, c]) : []), [model.view]);
  const column = (i: number) => {
    const spec = LAYERS[i];
    const all = shown.layers[spec.layer];
    const label = (c: Cond) => condLabel(saved.get(c.id) ?? c, shown.resources);
    return (
      <LayerColumn
        key={spec.layer}
        {...spec}
        items={all.filter((c) => matches(c, label(c), query, state))}
        total={all.length}
        saved={saved}
        edits={model.edits}
        resources={shown.resources}
        generation={model.generation}
        onEdit={model.edit}
      />
    );
  };
  return (
    <div className="cd-cols">
      <div className="cd-left">{[0, 1, 2].map(column)}</div>
      {column(3)}
    </div>
  );
}

/** 조건·규칙 프로그램. params.id(일정), 없으면 OS 의 지금 일정. 네 겹을 나란히 보이고 값을 바꿔 미리 본다. */
export default function Conditions({ windowId, params }: ProgramProps) {
  const current = useCurrentSchedule((s) => s.current?.id ?? null);
  const scheduleId = positiveId(params?.id) ?? current;
  const model = useConditionsModel(scheduleId);
  const [state, setState] = useState<StateFilter>('all');
  const [query, setQuery] = useState('');
  const name = model.view?.name ?? null;
  useEffect(() => {
    useWindows.getState().setTitle(windowId, name ? `조건·규칙 — ${name}` : '조건·규칙');
  }, [windowId, name]);
  useEffect(() => {
    // 대화창이 「보는 것」으로 이 일정을 보내게 알린다(창이 닫히면 OS 가 지운다).
    if (scheduleId !== null) useUiContext.getState().publish(windowId, { program: 'conditions', schedule_id: scheduleId });
  }, [windowId, scheduleId]);

  if (scheduleId === null || model.load.kind !== 'ready' || !model.shown) {
    const text = scheduleId === null ? NO_SCHEDULE : model.load.kind === 'failed' ? model.load.message : '조건을 읽는 중…';
    return (
      <div className="cd-root">
        <p className="cd-empty-page" role={model.load.kind === 'failed' ? 'alert' : undefined}>
          {text}
        </p>
      </div>
    );
  }
  return (
    <div className="cd-root">
      <div className="cd-page">
        <PreviewBar model={model} />
        <Filters shown={model.shown} state={state} setState={setState} query={query} setQuery={setQuery} />
        <Columns model={model} shown={model.shown} state={state} query={query} />
      </div>
    </div>
  );
}
