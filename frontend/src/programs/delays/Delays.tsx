// 「지연 기록」 창(Task 36). 위 KPI 넷 · 도구줄 · 사건 표 · 오른쪽 자세히/양식.
// params: id(일정, 없으면 OS 지금 일정) · event(고를 사건) · activity·days·before(실적 입력의 지연 알림이 채워 여는 새 사건 양식).
// 모든 값은 지연 API(서버 계산)에서 온다. 화면은 날짜를 계산하지 않는다. 다른 프로그램은 open 으로만 연다.
import { useEffect, useRef, useState } from 'react';
import { useCurrentSchedule } from '../../os/currentSchedule';
import type { ProgramProps } from '../../os/registry';
import { useUiContext } from '../../os/uiContext';
import { useWindows } from '../../os/windowStore';
import Button from '../../shared/ui/Button';
import { VisualButton } from '../../shared/visual/VisualFrame';
import DelayDetail from './DelayDetail';
import DelayForm from './DelayForm';
import type { ScheduleView } from '../../shared/schedule/scheduleApi';
import { patchDelay, postDelay, type DelayEvent, type DelaysData } from './delaysApi';
import DelayTable from './DelayTable';
import { emptyValues, toBody, toPatch, valuesOf, type FormValues } from './form';
import { RESPONSIBILITIES } from './format';
import KpiBar from './KpiBar';
import { ASK_ALL, openProgram, useActions, type Notice } from './useActions';
import { clearDelayPreview, errText, useDelays } from './useDelays';
import './delays.css';

const NAME = '지연 기록';
const positiveInt = (s: string | undefined) => (s && /^\d+$/.test(s) && Number(s) > 0 ? Number(s) : null);

type Params = Record<string, string> | undefined;
type Mode =
  | { kind: 'detail' }
  | { kind: 'new'; initial: FormValues; before: number | null; badBefore: string | null; n: number }
  | { kind: 'edit'; event: DelayEvent };

let formSeq = 0; // 새 양식마다 다른 열쇠(같은 params 로 다시 열어도 칸을 새로 채운다)

/**
 * activity·days·before 가 있으면 그것으로 채운 새 사건 양식. before 가 있는데 버전 번호가 아니면 badBefore 로 남긴다 —
 * 일반 사건으로 저장하면 이미 일정에 들어간 늦음을 두 번 세므로 양식이 저장을 막는다.
 */
function prefill(params: Params): Mode | null {
  if (!params?.activity && !params?.days && !params?.before) return null;
  const before = positiveInt(params.before);
  const badBefore = params.before !== undefined && before === null ? params.before : null;
  return { kind: 'new', initial: emptyValues({ activity_id: params.activity ?? '', days: params.days ?? '' }), before, badBefore, n: ++formSeq };
}

interface ToolbarProps {
  scheduleId: number;
  filters: { resp: string; status: string };
  onFilters: (f: { resp: string; status: string }) => void;
  onAdd: () => void;
  onCompare: () => void;
  canCompare: boolean;
  busy: boolean;
}

function Toolbar({ scheduleId, filters, onFilters, onAdd, onCompare, canCompare, busy }: ToolbarProps) {
  return (
    <div role="group" aria-label="지연 기록 도구" className="dl-toolbar">
      <Button variant="primary" onClick={onAdd}>
        + 지연 사건
      </Button>
      <select className="dl-input dl-filter" aria-label="책임 거르기" value={filters.resp} onChange={(e) => onFilters({ ...filters, resp: e.target.value })}>
        <option value="all">책임: 전체</option>
        {RESPONSIBILITIES.map((r) => (
          <option key={r.key} value={r.key}>{`책임: ${r.label}`}</option>
        ))}
      </select>
      <select className="dl-input dl-filter" aria-label="상태 거르기" value={filters.status} onChange={(e) => onFilters({ ...filters, status: e.target.value })}>
        <option value="all">상태: 전체</option>
        <option value="open">상태: 열림</option>
        <option value="reflected">상태: 반영됨</option>
      </select>
      <span className="dl-gap" />
      {!canCompare && <span className="dl-muted">열린 사건이 없어 비교판을 만들 수 없습니다.</span>}
      <Button onClick={onCompare} disabled={busy || !canCompare}>
        비교판에서 보기
      </Button>
      <Button onClick={() => openProgram('chat', { ask: ASK_ALL })}>만회 계획 요청</Button>
      <VisualButton scheduleId={scheduleId} kind="delay_impact" />
    </div>
  );
}

function NoticeBar({ notice, onClose }: { notice: Notice | null; onClose: () => void }) {
  if (!notice) return null;
  return (
    <div className={`dl-notice is-${notice.tone}`} role={notice.tone === 'error' ? 'alert' : 'status'}>
      <span>{notice.text}</span>
      <button type="button" className="dl-x" aria-label="알림 닫기" onClick={onClose}>
        ×
      </button>
    </div>
  );
}

function useWindowContext(windowId: string, scheduleId: number, scheduleName: string | null, activity: string | null) {
  useEffect(() => {
    useWindows.getState().setTitle(windowId, scheduleName ? `${NAME} — ${scheduleName}` : NAME);
  }, [windowId, scheduleName]);
  useEffect(() => {
    useUiContext.getState().publish(windowId, { program: 'delays', schedule_id: scheduleId, selected_activity: activity });
  }, [windowId, scheduleId, activity]);
  useEffect(() => () => clearDelayPreview(scheduleId), [scheduleId]); // 창을 닫거나 다른 일정으로 바뀌면
}

/** 오른쪽 칸의 모드와 고른 사건. 새 params 가 오면(같은 창을 다시 열면) 양식을 채우거나 사건을 고른다. */
function useMode(params: Params, data: DelaysData | null) {
  const [mode, setMode] = useState<Mode>(() => prefill(params) ?? { kind: 'detail' });
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const prefilled = useRef(params);
  useEffect(() => {
    if (prefilled.current === params) return; // 처음 params 는 useState 가 채웠다
    prefilled.current = params;
    const next = prefill(params);
    if (next) setMode(next);
  }, [params]);
  const eventParam = useRef<unknown>(null);
  useEffect(() => {
    if (!data || !params?.event || eventParam.current === params) return;
    eventParam.current = params;
    const id = Number(params.event);
    if (!data.events.some((e) => e.id === id)) return;
    setSelectedId(id);
    setMode({ kind: 'detail' });
  }, [data, params]);
  return { mode, setMode, selectedId, setSelectedId };
}

/** 양식 보내기: 고치기는 바뀐 칸만(없으면 보내지 않음), 새 사건은 등록 뒤 그 사건을 고른다. 실패 글은 양식이 보인다. */
function useSubmit(
  scheduleId: number,
  data: DelaysData | null,
  mode: Mode,
  setMode: (m: Mode) => void,
  setSelectedId: (id: number | null) => void,
  redraw: (d: DelaysData) => void,
) {
  return async (values: FormValues): Promise<string | null> => {
    try {
      if (mode.kind === 'edit') {
        const patch = toPatch(values, mode.event);
        if (Object.keys(patch).length > 0) redraw(await patchDelay(scheduleId, mode.event.id, patch));
      } else if (mode.kind === 'new') {
        const known = new Set(data?.events.map((e) => e.id));
        const d = await postDelay(scheduleId, toBody(values, mode.before));
        redraw(d);
        setSelectedId(d.events.find((e) => !known.has(e.id))?.id ?? null);
      }
      setMode({ kind: 'detail' });
      return null;
    } catch (e) {
      return errText(e, '저장할 수 없습니다.');
    }
  };
}

interface SideProps {
  mode: Mode;
  setMode: (m: Mode) => void;
  selected: DelayEvent | null;
  act: ReturnType<typeof useActions>;
  submit: (values: FormValues) => Promise<string | null>;
  view: ScheduleView | null;
  viewError: string | null;
}

/** 오른쪽 칸: 고른 사건의 자세히, 또는 새 사건·고치기 양식. */
function SidePane({ mode, setMode, selected, act, submit, view, viewError }: SideProps) {
  if (mode.kind === 'detail') {
    return (
      <DelayDetail
        event={selected}
        busy={act.busy}
        onEdit={() => selected && setMode({ kind: 'edit', event: selected })}
        onGantt={() => selected && void act.gantt(selected)}
        onRecover={() => selected && act.recover(selected)}
        onAnalyze={() => void act.analyze()}
      />
    );
  }
  return (
    <DelayForm
      key={mode.kind === 'edit' ? `e${mode.event.id}` : `n${mode.n}`}
      event={mode.kind === 'edit' ? mode.event : null}
      initial={mode.kind === 'edit' ? valuesOf(mode.event) : mode.initial}
      before={mode.kind === 'new' ? mode.before : null}
      badBefore={mode.kind === 'new' ? mode.badBefore : null}
      view={view}
      viewError={viewError}
      onSubmit={submit}
      onCancel={() => setMode({ kind: 'detail' })}
    />
  );
}

function DelaysBody({ windowId, scheduleId, params }: { windowId: string; scheduleId: number; params: Params }) {
  const { data, setData, loadError, view, viewError } = useDelays(scheduleId);
  const { mode, setMode, selectedId, setSelectedId } = useMode(params, data);
  const [filters, setFilters] = useState({ resp: 'all', status: 'all' });
  const act = useActions(scheduleId, setData);
  const selected = data?.events.find((e) => e.id === selectedId) ?? null;
  useWindowContext(windowId, scheduleId, view?.name ?? null, selected?.activity_id ?? null);

  const submit = useSubmit(scheduleId, data, mode, setMode, setSelectedId, act.redraw);

  /** 줄 고르기. 고치는 중에 다른 사건을 고르면 양식을 닫고 그 사건의 자세히로(다른 사건에 저장되지 않게). */
  const select = (e: DelayEvent) => {
    setSelectedId(e.id);
    if (mode.kind === 'edit' && mode.event.id !== e.id) setMode({ kind: 'detail' });
  };
  const events = (data?.events ?? []).filter(
    (e) => (filters.resp === 'all' || e.responsibility === filters.resp) && (filters.status === 'all' || e.status === filters.status),
  );
  const list = loadError ? (
    <p className="dl-error dl-pad" role="alert">
      {loadError}
    </p>
  ) : data ? (
    <DelayTable events={events} filtered={events.length < data.events.length} selectedId={selectedId} onSelect={select} />
  ) : (
    <p className="dl-muted dl-pad">지연 기록을 읽는 중…</p>
  );
  return (
    <div className="dl-root">
      {data && <KpiBar totals={data.totals} finish={data.finish} />}
      <Toolbar
        scheduleId={scheduleId}
        filters={filters}
        onFilters={setFilters}
        onAdd={() => setMode({ kind: 'new', initial: emptyValues(), before: null, badBefore: null, n: ++formSeq })}
        onCompare={() => void act.compare()}
        canCompare={(data?.totals.open_count ?? 0) > 0}
        busy={act.busy}
      />
      <NoticeBar notice={act.notice} onClose={() => act.setNotice(null)} />
      <div className="dl-main">
        <section className="dl-list" aria-label="지연 사건 목록">
          {list}
          <p className="dl-foot">사건은 대화나 실적 입력에서도 등록됩니다. 여러 건은 발생 순서대로 넣어 각각의 몫을 계산합니다.</p>
        </section>
        <section className="dl-side" aria-label={mode.kind === 'detail' ? '사건 자세히' : '지연 사건 양식'}>
          <SidePane mode={mode} setMode={setMode} selected={selected} act={act} submit={submit} view={view} viewError={viewError} />
        </section>
      </div>
    </div>
  );
}

/** 일정이 없을 때(params.id 도 OS 지금 일정도 없음). */
function NoSchedule({ windowId }: { windowId: string }) {
  useEffect(() => {
    useWindows.getState().setTitle(windowId, NAME);
    useUiContext.getState().publish(windowId, { program: 'delays', schedule_id: null, selected_activity: null });
  }, [windowId]);
  return <p className="dl-muted dl-pad">메뉴바에서 일정을 고르세요.</p>;
}

export default function Delays({ windowId, params }: ProgramProps) {
  const current = useCurrentSchedule((s) => s.current);
  const scheduleId = positiveInt(params?.id) ?? current?.id ?? null;
  if (scheduleId === null) return <NoSchedule windowId={windowId} />;
  return <DelaysBody key={scheduleId} windowId={windowId} scheduleId={scheduleId} params={params} />;
}
