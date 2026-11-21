// 간트차트 창 안의 상태: 층·묶는 기준·접기 · 왼쪽 표 칸 · 칸 고치기·키보드 초점 · 보이게 하기(reveal·다른 창에서 고른 줄).
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { loadPref, savePref } from '../../os/prefs';
import { useSession } from '../../os/session';
import type { EditEnd } from '../../shared/schedule/CellEditor';
import { COLUMNS, type ColKey, type ColumnDef } from '../../shared/schedule/columns';
import { commitCell } from '../../shared/schedule/edits';
import { parse, ParseError } from '../../shared/schedule/predecessors';
import { ancestors, NO_FILTER, wbsTree, type RowFilter } from '../../shared/schedule/rows';
import type { ScheduleView } from '../../shared/schedule/scheduleApi';
import type { ScheduleState } from '../../shared/schedule/scheduleStore';
import { useSchedule, useScheduleStore, useSelect, useWindowId } from '../../shared/schedule/scope';
import { groupKeys, rowsFor, type GanttRow, type GroupBy } from './grouping';
import type { Editing } from './LeftGrid';
import type { Layers } from './model';
import type { Viewport } from './useViewport';

/** 층·묶는 기준·접기·찾기·거르기. 처음 묶는 기준은 그 분야의 표시 설정(없으면 WBS), 사용자가 바꾸면 그대로 둔다. */
export function useLayersAndRows(view: ScheduleView) {
  const [layers, setLayers] = useState<Layers>({ plan: true, actual: true, cpm: true });
  const [groupBy, setGroupBy] = useState<GroupBy>(() => view.display?.gantt_group_by ?? 'wbs');
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set());
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState<RowFilter>(NO_FILTER);
  const rows = useMemo(() => rowsFor(view, groupBy, collapsed, { ...filter, query }), [view, groupBy, collapsed, filter, query]);
  const toggle = useCallback((key: string, open?: boolean) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (open ?? prev.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);
  return {
    layers, groupBy, rows, toggle, setCollapsed, query, setQuery, filter, setFilter,
    flipLayer: (k: keyof Layers) => setLayers((l) => ({ ...l, [k]: !l[k] })),
    groupByWith: (by: GroupBy) => {
      setGroupBy(by);
      setCollapsed(new Set());
    },
    expandAll: () => setCollapsed(new Set()),
    collapseAll: () => setCollapsed(new Set(groupKeys(view, groupBy))),
  };
}

const LEFT_W_PREF = 'schedule.gantt.leftWidth';

/** 간트 왼쪽 표 폭(로그인 사용자별로 기억). */
export function useGanttLeftWidth(fallback = 470) {
  const userId = useSession((s) => s.session?.user.id ?? null);
  const [leftW, setLeftWState] = useState<number>(() => {
    const saved = loadPref(LEFT_W_PREF, userId);
    return typeof saved === 'number' && Number.isFinite(saved) && saved >= 220 && saved <= 1200 ? Math.round(saved) : fallback;
  });
  const setLeftW = useCallback(
    (w: number) => {
      const rounded = Math.round(w);
      setLeftWState(rounded);
      savePref(LEFT_W_PREF, userId, rounded);
    },
    [userId],
  );
  return [leftW, setLeftW] as const;
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

/** 선행 칸은 스케줄처럼 지금 일정의 액티비티 ID 와 맞춰 본다. 틀리면 그 부분을 짚어 알리고 보내지 않는다. */
function predsKnown(store: ScheduleState, windowId: string, col: ColumnDef, text: string): boolean {
  if (col.key !== 'preds') return true;
  try {
    parse(text, new Set(store.view?.activities.map((x) => x.id)));
    return true;
  } catch (e) {
    if (!(e instanceof ParseError)) throw e;
    store.setNotice({ tone: 'error', text: e.message, windowId });
    return false;
  }
}

/** 바뀐 글이면(선행 칸은 ID 를 맞춰 본 뒤) 일정 저장소로 보낸다. 틀린 글 안내는 이 창에만. */
function commitIfChanged(store: ScheduleState, windowId: string, row: GanttRow, col: ColumnDef, text: string, initial: string) {
  if (row.activity && text.trim() !== initial.trim() && predsKnown(store, windowId, col, text)) void commitCell(store, windowId, row.activity, col, text);
}

/** 왼쪽 표의 그 줄로 키보드 초점을 옮긴다(그린 뒤에). */
function useFocusRow(vp: Viewport) {
  const [focus, setFocus] = useState<{ key: string; n: number } | null>(null);
  useEffect(() => {
    if (!focus) return;
    const els = vp.leftRef.current?.querySelectorAll<HTMLElement>('[data-row]') ?? [];
    [...els].find((el) => el.dataset.row === focus.key)?.focus();
  }, [focus, vp.leftRef]);
  return (key: string) => setFocus((f) => ({ key, n: (f?.n ?? 0) + 1 }));
}

/** 칸 고치기(표와 같은 편집기·같은 요청)와 키보드 초점. locked(미리 보기 중)이면 열지 않는다. */
export function useEditing(rows: GanttRow[], columns: ColumnDef[], locked: boolean, vp: Viewport, toggle: (key: string, open?: boolean) => void) {
  const store = useScheduleStore();
  const windowId = useWindowId();
  const select = useSelect();
  const [editing, setEditing] = useState<Editing | null>(null);
  const focusRow = useFocusRow(vp);
  const onEdit = (key: string, col: ColKey) => {
    const row = rows.find((r) => r.key === key);
    if (locked || !row?.activity || !columns.find((c) => c.key === col)?.edit) return;
    select(row.activity.id);
    setEditing({ key, col });
  };
  const onCommit = (row: GanttRow, col: ColumnDef, text: string, initial: string, how: EditEnd) => {
    setEditing(null);
    if (how !== 'leave') focusRow(row.key);
    commitIfChanged(store.getState(), windowId, row, col, text, initial);
  };
  const onCancel = (row: GanttRow, how: EditEnd) => {
    setEditing(null);
    if (how !== 'leave') focusRow(row.key);
  };
  const go = (i: number) => {
    const r = rows[i];
    if (!r) return;
    if (r.activity) select(r.activity.id);
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
 * 보이게 하기(초점은 옮기지 않는다): 창이 열릴 때 고른 줄로, 그 뒤 reveal 요청(params.activity·행 추가)과
 * 같은 일정을 보는 다른 창에서 고른 줄마다 가린 묶음을 풀고 그 줄로. 열릴 때 이미 있던 reveal 은 다시 하지 않는다.
 */
export function useReveal(view: ScheduleView, rows: GanttRow[], groupBy: GroupBy, setCollapsed: (f: (s: ReadonlySet<string>) => ReadonlySet<string>) => void, vp: Viewport) {
  const store = useScheduleStore();
  const windowId = useWindowId();
  const reveal = useSchedule((s) => s.reveal);
  const selectedN = useSchedule((s) => s.selectedN);
  const seen = useRef(store.getState().reveal);
  const target = useRef<string | null>(store.getState().selected);
  const show = useCallback(
    (aid: string) => {
      const a = view.activities.find((x) => x.id === aid);
      if (!a) return;
      const open = groupBy === 'wbs' ? new Set(ancestors(wbsTree(view).parentOf, a.wbs)) : null;
      setCollapsed((prev) => (open ? new Set([...prev].filter((c) => !open.has(c))) : new Set()));
      target.current = a.id;
    },
    [view, groupBy, setCollapsed],
  );
  // 고침으로 view 가 바뀔 때마다 다시 하지 않도록, 요청·고른 것이 바뀔 때만 그때의 show 를 부른다.
  const showRef = useRef(show);
  showRef.current = show;
  useEffect(() => {
    if (reveal === seen.current) return;
    seen.current = reveal;
    if (reveal) showRef.current(reveal.aid);
  }, [reveal]);
  useEffect(() => {
    const { selected, selectedBy } = store.getState();
    if (selected && selectedBy !== windowId) showRef.current(selected);
  }, [selectedN, store, windowId]);
  useLayoutEffect(() => {
    if (!target.current) return;
    const i = rows.findIndex((r) => r.activity?.id === target.current);
    if (i < 0) return;
    target.current = null;
    vp.nav.toRow(i);
  });
}
