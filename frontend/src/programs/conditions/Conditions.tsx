import { useEffect, useMemo, useState, type KeyboardEvent } from 'react';
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

/** 화살표로 상태 고르기를 옮긴다(라디오 묶음: 고른 것만 Tab 으로 닿고, 화살표가 고르며 옮긴다). */
function arrowTo(e: KeyboardEvent<HTMLDivElement>, values: StateFilter[], state: StateFilter, setState: (s: StateFilter) => void) {
  const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
  if (!step) return;
  e.preventDefault();
  const next = (values.indexOf(state) + step + values.length) % values.length;
  setState(values[next]);
  e.currentTarget.querySelectorAll<HTMLButtonElement>('[role=radio]')[next]?.focus();
}

/** 읽을 수 없는 저장 조건(점검하지 않음): 접어 두고 펼치면 까닭. */
function Unreadable({ items }: { items: CondView['invalid'] }) {
  if (items.length === 0) return null;
  return (
    <details className="cd-invalid">
      <summary>{`읽을 수 없는 조건 ${items.length}개 (점검하지 않음)`}</summary>
      <ul>
        {items.map((i, n) => (
          <li key={`${i.condition_id}-${n}`}>{`${i.condition_id}: ${i.message}`}</li>
        ))}
      </ul>
    </details>
  );
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
      <div
        className="cd-chips"
        role="radiogroup"
        aria-label="상태로 거르기"
        onKeyDown={(e) => arrowTo(e, chips.map(([v]) => v), state, setState)}
      >
        {chips.map(([value, label]) => (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={state === value}
            tabIndex={state === value ? 0 : -1}
            className={`cd-chip is-${value}`}
            onClick={() => setState(value)}
          >
            {label}
          </button>
        ))}
      </div>
      <Unreadable items={shown.invalid} />
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
        fieldsKey={model.fieldsKey}
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
