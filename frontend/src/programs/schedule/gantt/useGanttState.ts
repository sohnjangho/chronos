// 간트 탭 안의 상태: 층·묶는 기준·접기 · 왼쪽 표 칸 · 칸 고치기·키보드 초점 · 보이게 하기(reveal).
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { loadPref, savePref } from '../../../os/prefs';
import { useSession } from '../../../os/session';
import type { ScheduleView } from '../scheduleApi';
import { useSchedule } from '../scheduleStore';
import type { EditEnd } from '../table/CellEditor';
import { COLUMNS, type ColKey, type ColumnDef } from '../table/columns';
import { parse, ParseError } from '../table/predecessors';
import { ancestors, wbsTree } from '../table/rows';
import { commitCell } from '../table/useCursor';
import { groupKeys, rowsFor, type GanttRow, type GroupBy } from './grouping';
import type { Editing } from './LeftGrid';
import type { Layers } from './model';
import type { Viewport } from './useViewport';

export function useLayersAndRows(view: ScheduleView) {
  const [layers, setLayers] = useState<Layers>({ plan: true, actual: true, cpm: true });
  const [groupBy, setGroupBy] = useState<GroupBy>('wbs');
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set());
  const rows = useMemo(() => rowsFor(view, groupBy, collapsed), [view, groupBy, collapsed]);
  const toggle = useCallback((key: string, open?: boolean) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (open ?? prev.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);
  return {
    layers, groupBy, rows, toggle, setCollapsed,
    flipLayer: (k: keyof Layers) => setLayers((l) => ({ ...l, [k]: !l[k] })),
    groupByWith: (by: GroupBy) => {
      setGroupBy(by);
      setCollapsed(new Set());
    },
    expandAll: () => setCollapsed(new Set()),
    collapseAll: () => setCollapsed(new Set(groupKeys(view, groupBy))),
  };
}

const PREF = 'schedule.gantt.columns';
const DEFAULT_COLS: ColKey[] = ['od', 'rd', 'tf'];

/** 왼쪽 표 칸(WBS/ID·이름은 늘, 나머지는 열 고르기). 사용자별로 기억한다. */
export function useGanttColumns() {
  const userId = useSession((s) => s.session?.user.id ?? null);
  const [visible, setVisible] = useState<ColKey[]>(() => {
    const saved = loadPref(PREF, userId);
    const known = new Set(COLUMNS.map((c) => c.key));
    return Array.isArray(saved) && saved.every((k) => known.has(k)) ? (saved as ColKey[]) : DEFAULT_COLS;
  });
  const change = (keys: ColKey[]) => {
    setVisible(keys);
    savePref(PREF, userId, keys);
  };
  const columns = useMemo(() => COLUMNS.filter((c) => c.key === 'id' || c.key === 'name' || visible.includes(c.key)), [visible]);
  return { visible, change, columns };
}

/** 선행 칸은 스케줄표처럼 지금 일정의 액티비티 ID 와 맞춰 본다. 틀리면 그 부분을 짚어 알리고 보내지 않는다. */
function predsKnown(col: ColumnDef, text: string): boolean {
  if (col.key !== 'preds') return true;
  try {
    parse(text, new Set(useSchedule.getState().view?.activities.map((x) => x.id)));
    return true;
  } catch (e) {
    if (!(e instanceof ParseError)) throw e;
    useSchedule.getState().setNotice({ tone: 'error', text: e.message });
    return false;
  }
}

/** 칸 고치기(표와 같은 편집기·같은 요청)와 키보드 초점. locked(미리 보기 중)이면 열지 않는다. */
export function useEditing(rows: GanttRow[], columns: ColumnDef[], locked: boolean, vp: Viewport, toggle: (key: string, open?: boolean) => void) {
  const [editing, setEditing] = useState<Editing | null>(null);
  const [focus, setFocus] = useState<{ key: string; n: number } | null>(null);
  const focusRow = (key: string) => setFocus((f) => ({ key, n: (f?.n ?? 0) + 1 }));
  useEffect(() => {
    if (!focus) return;
    const els = vp.leftRef.current?.querySelectorAll<HTMLElement>('[data-row]') ?? [];
    [...els].find((el) => el.dataset.row === focus.key)?.focus();
  }, [focus, vp.leftRef]);
  const onEdit = (key: string, col: ColKey) => {
    const row = rows.find((r) => r.key === key);
    if (locked || !row?.activity || !columns.find((c) => c.key === col)?.edit) return;
    useSchedule.getState().select(row.activity.id);
    setEditing({ key, col });
  };
  const onCommit = (row: GanttRow, col: ColumnDef, text: string, initial: string, how: EditEnd) => {
    setEditing(null);
    if (how !== 'leave') focusRow(row.key);
    if (row.activity && text.trim() !== initial.trim() && predsKnown(col, text)) void commitCell(row.activity, col, text);
  };
  const onCancel = (row: GanttRow, how: EditEnd) => {
    setEditing(null);
    if (how !== 'leave') focusRow(row.key);
  };
  const go = (i: number) => {
    const r = rows[i];
    if (!r) return;
    if (r.activity) useSchedule.getState().select(r.activity.id);
    vp.nav.toRow(i);
    focusRow(r.key);
  };
  const onRowKey = (e: KeyboardEvent<HTMLDivElement>, row: GanttRow, i: number) => {
    if (e.target !== e.currentTarget) return;
    const group = row.kind === 'group';
    const keys: Record<string, () => void> = {
      ArrowDown: () => go(i + 1),
      ArrowUp: () => go(i - 1),
      ArrowLeft: () => group && toggle(row.key, false),
      ArrowRight: () => group && toggle(row.key, true),
      Enter: () => (group ? toggle(row.key) : onEdit(row.key, 'name')),
      F2: () => !group && onEdit(row.key, 'name'),
      ' ': () => group && toggle(row.key),
    };
    if (!keys[e.key]) return;
    e.preventDefault();
    keys[e.key]();
  };
  return { editing, onEdit, onCommit, onCancel, onRowKey };
}

/**
 * 보이게 하기: 탭이 열릴 때 고른 줄로, 그 뒤 reveal 요청(params.activity·행 추가)마다 가린 묶음을 풀고 그 줄로.
 * 열릴 때 이미 있던 reveal 은 다시 하지 않는다(다른 탭에서 돌아와도 접기를 건드리지 않게).
 */
export function useReveal(view: ScheduleView, rows: GanttRow[], groupBy: GroupBy, setCollapsed: (f: (s: ReadonlySet<string>) => ReadonlySet<string>) => void, vp: Viewport) {
  const reveal = useSchedule((s) => s.reveal);
  const seen = useRef(useSchedule.getState().reveal);
  const target = useRef<string | null>(useSchedule.getState().selected);
  useEffect(() => {
    if (reveal === seen.current) return;
    seen.current = reveal;
    const a = reveal && view.activities.find((x) => x.id === reveal.aid);
    if (!a) return;
    const open = groupBy === 'wbs' ? new Set(ancestors(wbsTree(view).parentOf, a.wbs)) : null;
    setCollapsed((prev) => (open ? new Set([...prev].filter((c) => !open.has(c))) : new Set()));
    target.current = a.id;
  }, [reveal, view, groupBy, setCollapsed]);
  useLayoutEffect(() => {
    if (!target.current) return;
    const i = rows.findIndex((r) => r.activity?.id === target.current);
    if (i < 0) return;
    target.current = null;
    vp.nav.toRow(i);
  });
}
