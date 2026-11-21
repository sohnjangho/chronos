// 간트차트 화면(설계 8-2): 왼쪽 WBS/ID 표 + 가운데 나눔선 + 오른쪽 날짜 막대 차트 + 아래 자원 줄.
// 고치기는 모두 일정 저장소의 쓰기 줄(같은 일정을 보는 창들이 함께 씀)로 보내고 서버가 다시 계산한 일정으로 다시 그린다.
// 조건·규칙 창의 미리 보기(OS useSchedulePreview)가 있으면 그 일정을 그리고, 움직인 것의 이전 자리를 점선으로 남긴다.
import { useMemo, useRef, type CSSProperties, type KeyboardEvent, type PointerEvent as ReactPointerEvent } from 'react';
import { useSchedulePreview, type SchedulePreview } from '../../os/schedulePreview';
import { pushToast } from '../../os/ToastStack';
import { ROW_H } from '../../shared/gantt/Bars';
import Button from '../../shared/ui/Button';
import { dot } from '../../shared/schedule/format';
import type { ScheduleView } from '../../shared/schedule/scheduleApi';
import { useNotify, useSchedule, useSelect } from '../../shared/schedule/scope';
import type { ColumnDef } from '../../shared/schedule/columns';
import { download, toCsv } from '../../shared/schedule/csv';
import { useColWidths } from '../../shared/schedule/useColWidths';
import Chart from './Chart';
import type { ChartModel } from './ChartRows';
import { exportImage } from './exportSheet';
import { useGanttColors } from './ganttColors';
import GanttToolbar from './GanttToolbar';
import LeftGrid from './LeftGrid';
import { useConditionMarks } from './marks';
import { cellTexts, deadlineLabel, planOf, previewGhosts, rangeOf, rowIndex, todayIso, vmarks } from './model';
import ResourceStrip from './ResourceStrip';
import { useDrag } from './useDrag';
import { useEditing, useGanttColumns, useGanttLeftWidth, useLayersAndRows, useReveal } from './useGanttState';
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

/** 미리 보기를 건 창마다 할 일. */
const PREVIEW_TEXT: Record<SchedulePreview['source'], string> = {
  conditions: '미리 보기 중 — 조건·규칙 창에서 확정하거나 되돌리세요',
  delays: '지연 미리 보기 중 — 지연 기록 창에서 등록·고치면 반영됩니다',
};

/** 미리 보기 띠: 건 창(출처)에 맞는 안내 + [미리 보기 끄기](이 일정의 미리 보기를 지우고 고칠 수 있게 돌아간다). */
function PreviewBanner({ scheduleId, source }: { scheduleId: number; source: SchedulePreview['source'] }) {
  return (
    <div className="gt-preview" role="status">
      <b>{PREVIEW_TEXT[source]}</b>
      <span>미리 보기 중에는 고칠 수 없습니다</span>
      <Button onClick={() => useSchedulePreview.getState().clear(scheduleId)}>미리 보기 끄기</Button>
    </div>
  );
}

/**
 * 보일 일정: 이 일정의 미리 보기(조건·지연)가 있으면 그것(모양이 ScheduleView 와 같다), 없으면 저장된 일정.
 * 이전 자리 점선은 저장된 보기와 견주어 두 칸 모두(moved[] 는 쓰지 않는다). 이 창의 고르기·안내도 준다.
 */
function useShown() {
  const select = useSelect();
  const notify = useNotify();
  const stored = useSchedule((s) => s.view)!;
  const preview = useSchedulePreview((s) => s.previews[stored.id]);
  const view = preview ? (preview.view as ScheduleView) : stored;
  const ghosts = useMemo(() => previewGhosts(stored, view), [stored, view]);
  const noPlan = view.activities.length > 0 && view.activities.every((a) => !planOf(a));
  return { select, notify, stored, view, preview, ghosts, noPlan };
}

/** 모든 액티비티의 Plan 이 없을 때 창에 한 번 알린다(줄마다 쓰지 않는다). */
function NoPlanBanner() {
  return (
    <div className="gt-preview gt-noplan" role="status">
      <b>Plan 을 계산할 수 없어 Plan 줄이 비어 있습니다</b>
      <span>Actual·예측 줄은 지금 계산 그대로 보입니다</span>
    </div>
  );
}

export default function GanttTab() {
  const { select, notify, stored, view, preview, ghosts, noPlan } = useShown();
  const selected = useSchedule((s) => s.selected);
  const g = useLayersAndRows(view);
  const marks = useConditionMarks(stored.id, stored.version);
  const range = useMemo(() => rangeOf([view, stored], marks), [view, stored, marks]);
  const vp = useViewport(range, g.rows.length);
  const cols = useGanttColumns();
  const colW = useColWidths('schedule.gantt.colWidths');
  const { colors, setColor, setLinkOpacity, resetColors } = useGanttColors();
  const ed = useEditing(g.rows, cols.columns, !!preview, vp, g.toggle);
  useReveal(view, g.rows, g.groupBy, g.setCollapsed, vp);
  const { drag, begin } = useDrag(vp.scale, view.calendar);
  const texts = useMemo(() => cellTexts(view), [view]);
  const mainRef = useRef<HTMLDivElement>(null);
  const [leftW, setLeftW] = useGanttLeftWidth(470);
  const maxLeft = Math.max(LEFT_MIN, (mainRef.current?.clientWidth || 1400) - CHART_MIN - SPLIT_W);
  const left = Math.min(leftW, maxLeft);

  const today = todayIso();
  const m: ChartModel = {
    view, rows: g.rows, scale: vp.scale, total: vp.total, layers: g.layers, selected, ghosts, noPlan,
    dues: new Map(marks.milestoneBy.map((d) => [d.activityId, marks.milestoneBy.filter((x) => x.activityId === d.activityId)])),
    rowOf: rowIndex(g.rows), vmarks: vmarks(view, marks, vp.scale, today, vp.total), editable: !preview, drag,
    labelY: vp.top - vp.first * ROW_H,
    onBar: begin, onEdit: (key) => ed.onEdit(key, cols.visible.includes('od') ? 'od' : 'name'), onPick: select,
  };
  const act = toolbarActions({ notify, stored, view, m, vp, range, today, selected, columns: cols.columns });

  const colorStyle = {
    '--gt-plan': colors.plan,
    '--gt-actual': colors.actual,
    '--gt-cpm': colors.cpm,
    '--gt-link-opacity': colors.linkOpacity,
  } as CSSProperties;

  return (
    <div className="gt-tab" style={colorStyle}>
      <GanttToolbar
        layers={g.layers} onLayer={g.flipLayer} colors={colors} onColor={setColor} onLinkOpacity={setLinkOpacity} onResetColors={() => { resetColors(); pushToast('간트 색상을 기본값으로 복원했습니다.', 'success'); }} groupBy={g.groupBy} onGroupBy={(by) => {
          g.groupByWith(by);
          vp.nav.top();
        }}
        visible={cols.visible} onVisible={cols.change} deadlineLabel={deadlineLabel(view)} hasSelection={!!selected} hasDataDate={!!view.data_date}
        onZoom={vp.nav.zoom} onFit={vp.nav.fit} onExpandAll={g.expandAll} onCollapseAll={g.collapseAll} onPage={vp.nav.page}
        {...act}
      />
      {preview && <PreviewBanner scheduleId={stored.id} source={preview.source} />}{noPlan && <NoPlanBanner />}
      <div className="gt-main" ref={mainRef}>
        <LeftGrid
          rows={g.rows} vp={vp} width={left} columns={cols.columns} layers={g.layers} widthOf={colW.widthOf} onResizeCol={colW.resize}
          query={g.query} onQuery={g.setQuery} filter={g.filter} onFilter={g.setFilter} wbs={view.wbs}
          texts={texts} selected={selected} editing={ed.editing}
          onRowKey={ed.onRowKey} onToggle={g.toggle} onEdit={ed.onEdit} onCommit={ed.onCommit} onCancel={ed.onCancel}
          onPick={(row) => row.activity && select(row.activity.id)}
        />
        <Splitter value={left} max={maxLeft} onChange={setLeftW} />
        <Chart m={m} vp={vp} />
      </div>
      <ResourceStrip view={view} scale={vp.scale} total={vp.total} nameWidth={left + SPLIT_W} vp={vp} plan={g.layers.plan} />
      <Foot rows={g.rows.length} total={view.activities.length} locked={!!preview} />
    </div>
  );
}

interface ActionCtx {
  /** 이 창에만 보일 안내. */
  notify(tone: 'error' | 'info', text: string): void;
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
function toolbarActions({ notify, stored, view, m, vp, range, today, selected, columns }: ActionCtx) {
  return {
    /** 고른 액티비티의 두 칸(Plan·지금 계산)이 모두 들어오게. */
    onFitSelected() {
      const a = view.activities.find((x) => x.id === selected);
      if (!a) return;
      const p = planOf(a);
      vp.nav.fitRange(p && p.start < a.es ? p.start : a.es, p && p.finish > a.ef ? p.finish : a.ef);
      const i = m.rowOf.get(a.id);
      if (i !== undefined) vp.nav.toRow(i);
    },
    onDataDate: () => view.data_date && vp.nav.toDate(view.data_date),
    onToday() {
      if (m.vmarks.some((v) => v.kind === 'today')) vp.nav.toDate(today);
      else notify('info', `오늘(${dot(today)})은 이 일정 기간 밖입니다(${dot(range.start)} ~ ${dot(range.end)}).`);
    },
    onCsv() {
      const texts = cellTexts(stored);
      download(`${stored.name} v${stored.version} 간트.csv`, toCsv(stored, columns, (aid) => texts.get(aid) ?? NO_TEXT));
    },
    onImage: () => void exportImage(m, `${stored.name} v${stored.version} 간트`),
  };
}
