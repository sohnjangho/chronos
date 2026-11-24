import { useCallback, useEffect, useMemo, useRef, useState, type RefObject } from 'react';
import { loadPref, savePref } from '../../os/prefs';
import { useSession } from '../../os/session';
import { COLUMNS, DEFAULT_VISIBLE, FIXED, MANUAL_WEIGHT, type ColKey, type ColumnDef } from '../../shared/schedule/columns';
import { download, toCsv } from '../../shared/schedule/csv';
import { commitCell } from '../../shared/schedule/edits';
import { format, parse, ParseError } from '../../shared/schedule/predecessors';
import { ancestors, buildRows, NO_FILTER, wbsLabel, wbsTree, weightedProgress, type RowFilter } from '../../shared/schedule/rows';
import type { Activity, PredItem, ScheduleView } from '../../shared/schedule/scheduleApi';
import type { ScheduleState } from '../../shared/schedule/scheduleStore';
import { useSchedule, useScheduleStore, useWindowId } from '../../shared/schedule/scope';
import { useColWidths, useRowHeight } from '../../shared/schedule/useColWidths';
import DelayNotice from './DelayNotice';
import Grid from './Grid';
import RelationsPanel from './RelationsPanel';
import Toolbar, { DeleteConfirm } from './Toolbar';
import { useCursor } from './useCursor';

const PREF = 'schedule.columns';
const NEW_ACTIVITY = { name: '새 액티비티', kind: 'task' as const, od: 5 };
const NO_TEXT = { preds: '', wbsLabel: '', resources: '' };

/** 분야 표시 설정의 덧붙일 칸 → 표 칸(늦은 날짜 ls_lf 는 표 칸이 없어 건너뛴다). */
const EXTRA: Record<string, ColKey[]> = { resources: ['resources'], constraint: ['constraint'], es_ef: ['es', 'ef'] };

/**
 * 사용자별로 기억하는 보이는 칸. 저장된 것이 없거나 모르는 값이면 기본 칸 + 그 분야의 덧붙일 칸(extra).
 * 가중치 직접 입력 방식이면 가중치 칸을 고칠 수 있다.
 */
function useVisibleColumns(manual: boolean, extra: string[]) {
  const userId = useSession((s) => s.session?.user.id ?? null);
  const [visible, setVisible] = useState<ColKey[]>(() => {
    const saved = loadPref(PREF, userId);
    const known = new Set(COLUMNS.map((c) => c.key));
    if (Array.isArray(saved) && saved.every((k) => known.has(k))) return saved as ColKey[];
    return [...DEFAULT_VISIBLE, ...extra.flatMap((e) => EXTRA[e] ?? [])];
  });
  const change = (keys: ColKey[]) => {
    setVisible(keys);
    savePref(PREF, userId, keys);
  };
  const columns = useMemo(
    () => COLUMNS.filter((c) => FIXED.includes(c.key) || visible.includes(c.key)).map((c) => (manual && c.key === 'weight' ? MANUAL_WEIGHT : c)),
    [visible, manual],
  );
  return { visible, change, columns };
}

/** 액티비티마다 선행 글·WBS 이름·주요 자원 이름(글이 같으면 그 줄은 다시 그리지 않는다). */
function useTexts(view: ScheduleView) {
  return useMemo(() => {
    const preds = new Map<string, PredItem[]>();
    for (const r of view.relations) preds.set(r.succ, [...(preds.get(r.succ) ?? []), { pred: r.pred, type: r.type, lag: r.lag }]);
    const wbs = new Map(view.wbs.map((w) => [w.code, wbsLabel(w)]));
    const res = new Map(view.resources.map((r) => [r.id, r.name]));
    return new Map(
      view.activities.map((a) => [
        a.id,
        { preds: format(preds.get(a.id) ?? []), wbsLabel: wbs.get(a.wbs) ?? a.wbs, resources: a.resources.map((id) => res.get(id) ?? id).join(', ') },
      ]),
    );
  }, [view.relations, view.wbs, view.resources, view.activities]);
}

/** 찾기·거르기·접기. show(a, all) 은 a 를 가린 접힌 묶음을 풀고, all 이면 찾기·거르기도 지운다(보이게 하기가 쓴다). */
function useRowState(view: ScheduleView, bodyRef: RefObject<HTMLTableSectionElement | null>) {
  const store = useScheduleStore();
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState<RowFilter>(NO_FILTER);
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set());
  const rows = useMemo(() => buildRows(view, { ...filter, query }, collapsed), [view, filter, query, collapsed]);
  const onToggle = useCallback((code: string, open?: boolean) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (open ?? prev.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  }, []);
  const show = useCallback(
    (a: Activity, all: boolean) => {
      const open = new Set(ancestors(wbsTree(store.getState().view!).parentOf, a.wbs));
      setCollapsed((prev) => new Set([...prev].filter((c) => !open.has(c))));
      if (!all) return;
      setQuery('');
      setFilter(NO_FILTER);
    },
    [store],
  );
  useReveal(show, bodyRef);
  return { query, setQuery, filter, setFilter, rows, onToggle };
}

/**
 * 그 줄을 보이게 하고 스크롤한다(초점은 옮기지 않는다).
 * - 이 창이나 모든 창에 온 reveal 요청(행 추가·params.activity): 가린 것(접기·찾기·거르기)을 모두 푼다.
 * - 같은 일정을 보는 다른 창에서 고른 줄: 접힌 묶음만 푼다(사용자가 건 찾기·거르기는 그대로 둔다).
 * 창이 열릴 때 이미 있던 reveal 요청은 다시 하지 않는다.
 */
function useReveal(show: (a: Activity, all: boolean) => void, bodyRef: RefObject<HTMLTableSectionElement | null>) {
  const store = useScheduleStore();
  const windowId = useWindowId();
  const reveal = useSchedule((s) => s.reveal);
  const selectedN = useSchedule((s) => s.selectedN);
  const seen = useRef(store.getState().reveal);
  const target = useRef<string | null>(null);
  const go = useCallback(
    (aid: string, all: boolean) => {
      const a = store.getState().view?.activities.find((x) => x.id === aid);
      if (!a) return;
      show(a, all);
      target.current = a.id;
    },
    [store, show],
  );
  useEffect(() => {
    if (reveal === seen.current) return;
    seen.current = reveal;
    if (reveal && (reveal.by === null || reveal.by === windowId)) go(reveal.aid, true);
  }, [reveal, windowId, go]);
  useEffect(() => {
    const { selected, selectedBy } = store.getState();
    if (selected && selectedBy !== windowId) go(selected, false);
  }, [selectedN, store, windowId, go]);
  useEffect(() => {
    if (!target.current) return;
    const tr = [...(bodyRef.current?.rows ?? [])].find((r) => r.dataset.key === target.current);
    if (!tr) return;
    target.current = null;
    tr.scrollIntoView?.({ block: 'center' });
  });
}

/** 고른 액티비티 바로 뒤(같은 WBS, FS 0)에, 고른 것이 없으면 첫 WBS 에 새 액티비티. 새 id 를 돌려준다. */
async function addAfter(store: ScheduleState, sel: Activity | undefined, view: ScheduleView): Promise<string | null> {
  const wbs = sel?.wbs ?? view.wbs[0]?.code;
  return wbs ? store.addActivity({ ...NEW_ACTIVITY, wbs, ...(sel && { after: sel.id }) }) : null;
}

/**
 * 칸에 적은 글을 보낸다. 선행 칸은 먼저 지금 일정의 액티비티 ID 와 정확히 맞춰 본다(서버 ID 는 자유 글이라
 * 꼴만으로 거르지 않는다). 없는 ID·종류 빠진 간격은 보내지 않고 이름을 짚어 알린다.
 */
async function commitChecked(store: ScheduleState, windowId: string, a: Activity, col: ColumnDef, text: string): Promise<unknown> {
  if (col.key === 'preds') {
    const ids = new Set(store.view?.activities.map((x) => x.id));
    try {
      parse(text, ids);
    } catch (e) {
      if (!(e instanceof ParseError)) throw e;
      return store.setNotice({ tone: 'error', text: e.message, windowId });
    }
  }
  return commitCell(store, windowId, a, col, text);
}

/** 칸 고치기 보내기(줄이 다시 그려지지 않게 함수가 바뀌지 않는다)와 [+ 행 추가](새 줄의 이름 칸을 바로 연다). */
function useActions(sel: Activity | undefined, view: ScheduleView, edit: (e: { aid: string; col: ColKey }) => void) {
  const store = useScheduleStore();
  const windowId = useWindowId();
  const onCommit = useCallback((a: Activity, col: ColumnDef, text: string) => commitChecked(store.getState(), windowId, a, col, text), [store, windowId]);
  const add = async () => {
    const aid = await addAfter(store.getState(), sel, view);
    if (aid) edit({ aid, col: 'name' });
  };
  return { onCommit, add };
}

/** 삭제 확인을 띄운 액티비티. 고른 줄이 바뀌면 닫는다(같은 줄로 돌아와도 다시 뜨지 않는다). */
function useAsking(selected: string | null) {
  const [asking, setAsking] = useState<string | null>(null);
  useEffect(() => setAsking(null), [selected]);
  return [asking, setAsking] as const;
}

const noEdit = () => {};

const PRED_HINT = '선행: A2010, A1040 SS+15 처럼 적습니다 · 띄어쓰기·쉼표가 든 ID 는 아래 관계 패널의 [+ 선행 추가]로 넣습니다';

function Foot({ rows, total, editingPreds, canEdit }: { rows: number; total: number; editingPreds: boolean; canEdit: boolean }) {
  const pending = useSchedule((s) => s.pending);
  return (
    <div className="sch-foot">
      <span>{`${rows} 행 · 액티비티 ${total}개`}</span>
      {pending > 0 && <span className="sch-saving">저장 중…</span>}
      <span className="sch-gap" />
      {editingPreds ? (
        <span className="sch-muted" title={PRED_HINT}>
          {PRED_HINT}
        </span>
      ) : (
        <span className="sch-muted">{canEdit ? '두 번 누르거나 Enter 로 고칩니다 · Esc 취소 · ↑↓ 줄 옮김' : '현장 관리자는 일정을 고칠 수 없습니다 · ↑↓ 줄 옮김'}</span>
      )}
    </div>
  );
}

/** 스케줄 화면: 도구줄 · 표 · 줄 수 · 관계 패널. */
export default function TableTab() {
  const view = useSchedule((s) => s.view)!;
  const selected = useSchedule((s) => s.selected);
  const weightMode = view.weight_mode ?? 'duration';
  const { visible, change, columns } = useVisibleColumns(weightMode === 'manual', view.display?.extra_columns ?? []);
  const colW = useColWidths('schedule.table.colWidths');
  const rowH = useRowHeight('schedule.table.rowHeight', 32);
  const store = useScheduleStore();
  const texts = useTexts(view);
  const bodyRef = useRef<HTMLTableSectionElement>(null);
  const rs = useRowState(view, bodyRef);
  const cursor = useCursor(bodyRef, columns);
  // 현장 관리자는 일정을 고칠 수 없다(서버도 403) — 칸 고치기를 열지 않고 관계 패널을 그리지 않는다(F4).
  const canEdit = useSession((s) => s.session?.user.role !== 'field');

  const sel = view.activities.find((a) => a.id === selected);
  const [asking, setAsking] = useAsking(selected);
  const { onCommit, add } = useActions(sel, view, cursor.setEditing);

  return (
    <div className="sch-table-tab">
      <Toolbar
        visible={visible}
        onVisible={change}
        canAdd={view.wbs.length > 0}
        canDelete={!!sel}
        progress={weightedProgress(view.activities)}
        weightMode={weightMode}
        onWeightMode={(mode) => void store.getState().setWeightMode(mode)}
        onAdd={add}
        onDelete={() => setAsking(sel?.id ?? null)}
        onExport={() => download(`${view.name} v${view.version}.csv`, toCsv(view, columns, (aid) => texts.get(aid) ?? NO_TEXT))}
        scheduleId={view.id}
        selected={sel}
      />
      {sel && asking === sel.id && <DeleteConfirm activity={sel} onDone={() => setAsking(null)} />}
      <DelayNotice />
      <div className="sch-grid-wrap">
        <Grid
          rows={rs.rows}
          columns={columns}
          widthOf={colW.widthOf}
          onResizeCol={colW.resize}
          rowHeight={rowH.rowHeight}
          onResizeRow={rowH.resizeRow}
          query={rs.query}
          onQuery={rs.setQuery}
          filter={rs.filter}
          onFilter={rs.setFilter}
          wbs={view.wbs}
          texts={texts}
          selected={selected}
          bodyRef={bodyRef}
          {...cursor}
          onEdit={canEdit ? cursor.onEdit : noEdit}
          onCommit={onCommit}
          onToggle={rs.onToggle}
          onActiveCol={cursor.setActiveCol}
        />
      </div>
      <Foot rows={rs.rows.length} total={view.activities.length} editingPreds={cursor.editing?.col === 'preds'} canEdit={canEdit} />
      {canEdit && <RelationsPanel />}
    </div>
  );
}
