// 「비교판」: 두 안(기준·비교)과 여러 안 요약을 나란히 본다. params: id(일정, 없으면 OS 의 지금 일정) ·
// base(기본 current) · other(기본: 열린 복사본 가운데 가장 새것, 없으면 plan). 꼴이 틀린 ref 는 기본값으로.
// 날짜·차이·기한·위반은 모두 서버 값(비교·요약 API)이고, 화면은 그리기만 한다.
import { useEffect, useState } from 'react';
import { useCurrentSchedule, type CurrentSchedule } from '../../os/currentSchedule';
import type { ProgramProps } from '../../os/registry';
import { useUiContext } from '../../os/uiContext';
import { useWindows } from '../../os/windowStore';
import { api } from '../../shared/api';
import { scenarioId, validRef, type CompareOut, type SideOut } from './compareApi';
import DiffTable from './DiffTable';
import DiscardDialog from './DiscardDialog';
import OverlayChart from './OverlayChart';
import { planGroups } from './PlanPicker';
import { CHANGE_LABEL, visibleRows } from './rows';
import SideBySide from './SideBySide';
import SubmitDialog from './SubmitDialog';
import SummaryTable from './SummaryTable';
import Toolbar, { type View } from './Toolbar';
import { useCompareData, type Load } from './useCompare';
import WhatIfDialog from './WhatIfDialog';
import './compare.css';

const positiveId = (s: string | undefined) => (s && /^\d+$/.test(s) && Number(s) > 0 ? Number(s) : null);
const fromParams = (p: Record<string, string> | undefined) => ({ base: validRef(p?.base) ?? 'current', other: validRef(p?.other) });
const FIXED_LABEL: Record<string, string> = { current: '현재 일정', plan: 'Plan' };
const VIEW_NOTE: Record<View, string> = { overlay: '윗줄 기준 · 아랫줄 비교', side: '두 간트를 같은 척도로', diff: '차이는 근무일' };

type Modal = { kind: 'whatif' } | { kind: 'submit' | 'discard'; sid: number; name: string } | null;

/** 창 제목에 쓸 일정 이름: OS 의 지금 일정이면 그 이름, 아니면 일정 목록에서 찾는다. */
function useScheduleName(id: number | null, current: CurrentSchedule | null): string | null {
  const known = current && current.id === id ? current.name : null;
  const [found, setFound] = useState<{ id: number; name: string } | null>(null);
  useEffect(() => {
    if (id === null || known) return;
    let live = true;
    api<{ id: number; name: string }[]>('/api/schedules')
      .then((list) => {
        const s = list.find((x) => x.id === id);
        if (live && s) setFound({ id, name: s.name });
      })
      .catch(() => undefined); // 이름 없이도 비교판은 쓸 수 있다
    return () => {
      live = false;
    };
  }, [id, known]);
  return known ?? (found?.id === id ? found.name : null);
}

/** 보기 위 줄: 무엇을 보는지 · 범례 · [달라진 것만 | 전체]. */
function ViewBar({ data, view, onlyChanged, setOnlyChanged }: { data: CompareOut; view: View; onlyChanged: boolean; setOnlyChanged(v: boolean): void }) {
  const kinds = new Set(data.rows.map((r) => r.change));
  const legend = [...(['pulled', 'pushed', 'same'] as const), ...(['added', 'duration'] as const).filter((k) => kinds.has(k))];
  const due = [data.base, data.other].some((s) => s.deadline && s.deadline_float !== null);
  return (
    <div className="cmp-viewbar">
      <span>
        <b>{VIEW_NOTE[view]}</b> <span className="cmp-muted">· 달라진 액티비티 {data.changed_count}개</span>
      </span>
      {view !== 'diff' && (
        <span className="cmp-legend" aria-label="범례">
          <span><i className="cmp-swatch is-base" />기준</span>
          {legend.map((k) => (
            <span key={k}><i className={`cmp-swatch is-${k}`} />비교 · {CHANGE_LABEL[k]}</span>
          ))}
          {due && <span><i className="cmp-dueline" />기한</span>}
        </span>
      )}
      <div className="cmp-grow" />
      <div className="cmp-seg" role="group" aria-label="줄 거르기">
        <button type="button" aria-pressed={onlyChanged} onClick={() => setOnlyChanged(true)}>달라진 것만</button>
        <button type="button" aria-pressed={!onlyChanged} onClick={() => setOnlyChanged(false)}>전체</button>
      </div>
    </div>
  );
}

function ViewArea({ load, view, onlyChanged, setOnlyChanged }: { load: Load<CompareOut>; view: View; onlyChanged: boolean; setOnlyChanged(v: boolean): void }) {
  if (load.kind === 'loading') return <p className="cmp-empty">비교를 읽는 중…</p>;
  if (load.kind === 'failed') return <p className="cmp-empty is-error" role="alert">{load.message}</p>;
  const rows = visibleRows(load.data.rows, onlyChanged);
  return (
    <>
      <ViewBar data={load.data} view={view} onlyChanged={onlyChanged} setOnlyChanged={setOnlyChanged} />
      <div className="cmp-view">
        {view === 'overlay' && <OverlayChart data={load.data} rows={rows} />}
        {view === 'side' && <SideBySide data={load.data} rows={rows} />}
        {view === 'diff' && <DiffTable rows={rows} />}
      </div>
    </>
  );
}

function Board({ scheduleId, params }: { scheduleId: number; params?: Record<string, string> }) {
  const [pick, setPick] = useState(() => fromParams(params));
  const [seen, setSeen] = useState({ params, n: 0 });
  if (seen.params !== params) {
    // 열린 창에 새 params(에이전트가 방금 만든 복사본 등)가 오면 그 안들로, 요약·버전도 다시 읽는다.
    setSeen({ params, n: seen.n + 1 });
    setPick(fromParams(params));
  }
  const [view, setView] = useState<View>('overlay');
  const [onlyChanged, setOnlyChanged] = useState(false);
  const [modal, setModal] = useState<Modal>(null);
  const d = useCompareData(scheduleId, pick.base, pick.other, seen.n);
  const sides = d.summary.kind === 'ready' ? d.summary.data : [];
  const c = d.compare.kind === 'ready' ? d.compare.data : null;
  const copy = c && scenarioId(c.other.ref) !== null ? c.other : null;
  const known: SideOut[] = [...(c ? [c.base, c.other] : []), ...sides];
  const labelOf = (ref: string) => known.find((s) => s.ref === ref)?.label ?? FIXED_LABEL[ref] ?? (ref.startsWith('v:') ? `버전 ${ref.slice(2)}` : ref);
  const ask = (kind: 'submit' | 'discard') => copy && setModal({ kind, sid: scenarioId(copy.ref)!, name: copy.label });
  const close = () => setModal(null);
  const after = (other: string | null, base?: string) => {
    setPick((p) => ({ base: base ?? p.base, other }));
    setModal(null);
    d.reload();
  };
  return (
    <>
      <div className="cmp-scroll">
        <Toolbar
          base={pick.base}
          other={d.other}
          labelOf={labelOf}
          groups={planGroups(sides, d.versions)}
          onBase={(base) => setPick((p) => ({ ...p, base }))}
          onOther={(other) => setPick((p) => ({ ...p, other }))}
          view={view}
          onView={setView}
          copy={copy}
          onWhatIf={() => setModal({ kind: 'whatif' })}
          onDiscard={() => ask('discard')}
          onSubmit={() => ask('submit')}
        />
        {d.summary.kind === 'failed' && <p className="cmp-empty is-error" role="alert">{d.summary.message}</p>}
        {sides.length > 0 && <SummaryTable sides={sides} base={pick.base} other={d.other} onPick={(other) => setPick((p) => ({ ...p, other }))} />}
        <ViewArea load={d.compare} view={view} onlyChanged={onlyChanged} setOnlyChanged={setOnlyChanged} />
      </div>
      {/* 겹화면은 굴러가는 칸 밖(창 본문에 고정) — 아래로 굴린 뒤 열어도 보인다. */}
      {modal?.kind === 'whatif' && <WhatIfDialog onClose={close} />}
      {modal?.kind === 'submit' && (
        <SubmitDialog scheduleId={scheduleId} scenarioId={modal.sid} name={modal.name} onClose={close} onSent={() => after(`s:${modal.sid}`)} onStale={d.reload} />
      )}
      {modal?.kind === 'discard' && (
        <DiscardDialog
          scheduleId={scheduleId}
          scenarioId={modal.sid}
          name={modal.name}
          onClose={close}
          onDone={() => after(null, pick.base === `s:${modal.sid}` ? 'current' : undefined)}
        />
      )}
    </>
  );
}

export default function Compare({ windowId, params }: ProgramProps) {
  const current = useCurrentSchedule((s) => s.current);
  const scheduleId = positiveId(params?.id) ?? current?.id ?? null;
  const name = useScheduleName(scheduleId, current);
  useEffect(() => {
    useWindows.getState().setTitle(windowId, name ? `비교판 — ${name}` : '비교판');
  }, [windowId, name]);
  useEffect(() => {
    useUiContext.getState().publish(windowId, { program: 'compare', schedule_id: scheduleId });
  }, [windowId, scheduleId]);
  return (
    <div className="cmp-root">
      {scheduleId === null ? <p className="cmp-empty">메뉴바에서 일정을 고르세요.</p> : <Board key={scheduleId} scheduleId={scheduleId} params={params} />}
    </div>
  );
}
