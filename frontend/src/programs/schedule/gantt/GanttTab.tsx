// 일정판 간트 탭(설계 8-2): 왼쪽 WBS/ID 표 + 가운데 나눔선 + 오른쪽 날짜 막대 차트 + 아래 자원 줄.
// 고치기는 모두 일정판 쓰기 줄(useSchedule)로 보내고 서버가 다시 계산한 일정으로 다시 그린다.
// 조건·규칙 창의 미리 보기(OS useSchedulePreview)가 있으면 그 일정을 그리고, 움직인 것의 이전 자리를 점선으로 남긴다.
import { useMemo, useRef, useState, type KeyboardEvent, type PointerEvent as ReactPointerEvent } from 'react';
import { useSchedulePreview } from '../../../os/schedulePreview';
import { dot } from '../format';
import type { ScheduleView } from '../scheduleApi';
import { useSchedule } from '../scheduleStore';
import type { ColumnDef } from '../table/columns';
import { download, toCsv } from '../table/csv';
import Chart from './Chart';
import type { ChartModel } from './ChartRows';
import { exportImage } from './exportSheet';
import GanttToolbar from './GanttToolbar';
import LeftGrid from './LeftGrid';
import { useConditionMarks } from './marks';
import { cellTexts, rangeOf, rowIndex, todayIso, vmarks } from './model';
import ResourceStrip from './ResourceStrip';
import { useDrag } from './useDrag';
import { useEditing, useGanttColumns, useLayersAndRows, useReveal } from './useGanttState';
import { useViewport, type Viewport } from './useViewport';
import './gantt-tab.css';

const LEFT_MIN = 220;
const CHART_MIN = 240;
const SPLIT_W = 6;
const NO_TEXT = { preds: '', wbsLabel: '', resources: '' };

/** 가운데 나눔선: 끌거나 ←→(16px)로 왼쪽 표 폭을 바꾼다. */
function Splitter({ value, max, onChange }: { value: number; max: number; onChange(w: number): void }) {
  const set = (w: number) => onChange(Math.min(max, Math.max(LEFT_MIN, w)));
  const onPointerDown = (e: ReactPointerEvent) => {
    const x0 = e.clientX;
    const move = (ev: PointerEvent) => set(value + ev.clientX - x0);
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };
  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    e.preventDefault();
    set(value + (e.key === 'ArrowRight' ? 16 : -16));
  };
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="표와 차트 나눔선"
      aria-valuenow={value}
      aria-valuemin={LEFT_MIN}
      aria-valuemax={max}
      tabIndex={0}
      className="gt-split"
      onPointerDown={onPointerDown}
      onKeyDown={onKeyDown}
    />
  );
}

function Foot({ rows, total, locked }: { rows: number; total: number; locked: boolean }) {
  const pending = useSchedule((s) => s.pending);
  return (
    <div className="sch-foot">
      <span>{`${rows} 행 · 액티비티 ${total}개`}</span>
      {pending > 0 && <span className="sch-saving">저장 중…</span>}
      <span className="sch-gap" />
      {!locked && <span className="sch-muted">막대를 누르면 고릅니다 · 오른쪽 끝을 끌면 OD · 막대를 끌면 SNET · 두 번 누르면 고칩니다</span>}
    </div>
  );
}

function PreviewBanner() {
  return (
    <div className="gt-preview" role="status">
      <b>미리 보기 중 — 조건·규칙 창에서 확정하거나 되돌리세요</b>
      <span>미리 보기 중에는 고칠 수 없습니다</span>
    </div>
  );
}

/** 보일 일정: 이 일정의 조건 미리 보기가 있으면 그것(모양이 ScheduleView 와 같다), 없으면 저장된 일정. */
function useShown() {
  const stored = useSchedule((s) => s.view)!;
  const preview = useSchedulePreview((s) => s.previews[stored.id]);
  const view = preview ? (preview.view as unknown as ScheduleView) : stored;
  const ghosts = useMemo(() => new Map((preview?.moved ?? []).map((mv) => [mv.activity_id, mv.before])), [preview]);
  return { stored, view, preview, ghosts };
}

export default function GanttTab() {
  const { stored, view, preview, ghosts } = useShown();
  const selected = useSchedule((s) => s.selected);
  const g = useLayersAndRows(view);
  const marks = useConditionMarks(stored.id, stored.version);
  const range = useMemo(() => rangeOf(view, marks), [view, marks]);
  const vp = useViewport(range, g.rows.length);
  const cols = useGanttColumns();
  const ed = useEditing(g.rows, cols.columns, !!preview, vp, g.toggle);
  useReveal(view, g.rows, g.groupBy, g.setCollapsed, vp);
  const { drag, begin } = useDrag(vp.scale);
  const texts = useMemo(() => cellTexts(view), [view]);
  const mainRef = useRef<HTMLDivElement>(null);
  const [leftW, setLeftW] = useState(470);
  const maxLeft = Math.max(LEFT_MIN, (mainRef.current?.clientWidth || 1400) - CHART_MIN - SPLIT_W);
  const left = Math.min(leftW, maxLeft);

  const today = todayIso();
  const m: ChartModel = {
    view, rows: g.rows, scale: vp.scale, total: vp.total, layers: g.layers, selected, ghosts,
    dues: new Map(marks.milestoneBy.map((d) => [d.activityId, marks.milestoneBy.filter((x) => x.activityId === d.activityId)])),
    rowOf: rowIndex(g.rows), vmarks: vmarks(view, marks, vp.scale, today, vp.total), editable: !preview, drag,
    onBar: begin, onEdit: (key) => ed.onEdit(key, cols.visible.includes('od') ? 'od' : 'name'), onPick: (aid) => useSchedule.getState().select(aid),
  };
  const act = toolbarActions({ stored, view, m, vp, range, today, selected, columns: cols.columns });

  return (
    <div className="gt-tab">
      <GanttToolbar
        layers={g.layers} onLayer={g.flipLayer} groupBy={g.groupBy} onGroupBy={(by) => {
          g.groupByWith(by);
          vp.nav.top();
        }}
        visible={cols.visible} onVisible={cols.change} hasSelection={!!selected} hasDataDate={!!view.data_date}
        onZoom={vp.nav.zoom} onFit={vp.nav.fit} onExpandAll={g.expandAll} onCollapseAll={g.collapseAll} onPage={vp.nav.page}
        {...act}
      />
      {preview && <PreviewBanner />}
      <div className="gt-main" ref={mainRef}>
        <LeftGrid
          rows={g.rows} vp={vp} width={left} columns={cols.columns} texts={texts} selected={selected} editing={ed.editing}
          onRowKey={ed.onRowKey} onToggle={g.toggle} onEdit={ed.onEdit} onCommit={ed.onCommit} onCancel={ed.onCancel}
          onPick={(row) => row.activity && useSchedule.getState().select(row.activity.id)}
        />
        <Splitter value={left} max={maxLeft} onChange={setLeftW} />
        <Chart m={m} vp={vp} />
      </div>
      <ResourceStrip view={view} scale={vp.scale} total={vp.total} nameWidth={left + SPLIT_W} vp={vp} />
      <Foot rows={g.rows.length} total={view.activities.length} locked={!!preview} />
    </div>
  );
}

interface ActionCtx {
  stored: ScheduleView;
  view: ScheduleView;
  m: ChartModel;
  vp: Viewport;
  range: { start: string; end: string };
  today: string;
  selected: string | null;
  columns: ColumnDef[];
}

/** 도구줄의 맞춤·이동·내보내기. CSV 는 저장된 일정(미리 보기 아님)을 스케줄표와 같은 안전한 CSV 로. */
function toolbarActions({ stored, view, m, vp, range, today, selected, columns }: ActionCtx) {
  return {
    onFitSelected() {
      const a = view.activities.find((x) => x.id === selected);
      if (!a) return;
      vp.nav.fitRange(a.es, a.ef);
      const i = m.rowOf.get(a.id);
      if (i !== undefined) vp.nav.toRow(i);
    },
    onDataDate: () => view.data_date && vp.nav.toDate(view.data_date),
    onToday() {
      if (m.vmarks.some((v) => v.kind === 'today')) vp.nav.toDate(today);
      else useSchedule.getState().setNotice({ tone: 'info', text: `오늘(${dot(today)})은 이 일정 기간 밖입니다(${dot(range.start)} ~ ${dot(range.end)}).` });
    },
    onCsv() {
      const texts = cellTexts(stored);
      download(`${stored.name} v${stored.version} 간트.csv`, toCsv(stored, columns, (aid) => texts.get(aid) ?? NO_TEXT));
    },
    onImage: () => void exportImage(m, `${stored.name} v${stored.version} 간트`),
  };
}
