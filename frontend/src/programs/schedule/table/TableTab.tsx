import { useCallback, useEffect, useMemo, useRef, useState, type RefObject } from 'react';
import { loadPref, savePref } from '../../../os/prefs';
import { useSession } from '../../../os/session';
import type { Activity, PredItem, ScheduleView } from '../scheduleApi';
import { useSchedule } from '../scheduleStore';
import { COLUMNS, DEFAULT_VISIBLE, FIXED, type ColKey } from './columns';
import { download, toCsv } from './csv';
import Grid from './Grid';
import { format } from './predecessors';
import RelationsPanel from './RelationsPanel';
import { ancestors, buildRows, NO_FILTER, wbsLabel, wbsTree, weightedProgress, type RowFilter } from './rows';
import Toolbar, { DeleteConfirm } from './Toolbar';
import { commitCell, useCursor } from './useCursor';

const PREF = 'schedule.columns';
const NEW_ACTIVITY = { name: '새 액티비티', kind: 'task' as const, od: 5 };
const NO_TEXT = { preds: '', wbsLabel: '', resources: '' };

/** 사용자별로 기억하는 보이는 칸(모르는 값이면 기본). */
function useVisibleColumns() {
  const userId = useSession((s) => s.session?.user.id ?? null);
  const [visible, setVisible] = useState<ColKey[]>(() => {
    const saved = loadPref(PREF, userId);
    const known = new Set(COLUMNS.map((c) => c.key));
    return Array.isArray(saved) && saved.every((k) => known.has(k)) ? (saved as ColKey[]) : DEFAULT_VISIBLE;
  });
  const change = (keys: ColKey[]) => {
    setVisible(keys);
    savePref(PREF, userId, keys);
  };
  const columns = useMemo(() => COLUMNS.filter((c) => FIXED.includes(c.key) || visible.includes(c.key)), [visible]);
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

/** 찾기·거르기·접기. show(a) 는 a 를 가린 것을 모두 푼다(reveal 요청이 쓴다). */
function useRowState(view: ScheduleView, bodyRef: RefObject<HTMLTableSectionElement | null>) {
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
  const show = useCallback((a: Activity) => {
    const open = new Set(ancestors(wbsTree(useSchedule.getState().view!).parentOf, a.wbs));
    setCollapsed((prev) => new Set([...prev].filter((c) => !open.has(c))));
    setQuery('');
    setFilter(NO_FILTER);
  }, []);
  useReveal(show, bodyRef);
  return { query, setQuery, filter, setFilter, rows, onToggle };
}

/**
 * 스토어의 reveal 요청: 가린 것을 풀고 그 줄로 스크롤한다(행 추가·params.activity).
 * 이 탭이 열릴 때 이미 있던 요청은 다시 하지 않는다(다른 탭에서 돌아와도 찾기·스크롤을 건드리지 않게).
 */
function useReveal(show: (a: Activity) => void, bodyRef: RefObject<HTMLTableSectionElement | null>) {
  const reveal = useSchedule((s) => s.reveal);
  const seen = useRef(useSchedule.getState().reveal);
  const target = useRef<string | null>(null);
  useEffect(() => {
    if (reveal === seen.current) return;
    seen.current = reveal;
    const a = reveal && useSchedule.getState().view?.activities.find((x) => x.id === reveal.aid);
    if (!a) return;
    show(a);
    target.current = a.id;
  }, [reveal, show]);
  useEffect(() => {
    if (!target.current) return;
    const tr = [...(bodyRef.current?.rows ?? [])].find((r) => r.dataset.key === target.current);
    if (!tr) return;
    target.current = null;
    tr.scrollIntoView?.({ block: 'center' });
  });
}

/** 고른 액티비티 바로 뒤(같은 WBS, FS 0)에, 고른 것이 없으면 첫 WBS 에 새 액티비티. 새 id 를 돌려준다. */
async function addAfter(sel: Activity | undefined, view: ScheduleView): Promise<string | null> {
  const wbs = sel?.wbs ?? view.wbs[0]?.code;
  return wbs ? useSchedule.getState().addActivity({ ...NEW_ACTIVITY, wbs, ...(sel && { after: sel.id }) }) : null;
}

function Foot({ rows, total }: { rows: number; total: number }) {
  const pending = useSchedule((s) => s.pending);
  return (
    <div className="sch-foot">
      <span>{`${rows} 행 · 액티비티 ${total}개`}</span>
      {pending > 0 && <span className="sch-saving">저장 중…</span>}
      <span className="sch-gap" />
      <span className="sch-muted">두 번 누르거나 Enter 로 고칩니다 · Esc 취소 · ↑↓ 줄 옮김</span>
    </div>
  );
}

/** 스케줄표 탭: 도구줄 · 표 · 줄 수 · 관계 패널. */
export default function TableTab() {
  const view = useSchedule((s) => s.view)!;
  const selected = useSchedule((s) => s.selected);
  const { visible, change, columns } = useVisibleColumns();
  const texts = useTexts(view);
  const bodyRef = useRef<HTMLTableSectionElement>(null);
  const rs = useRowState(view, bodyRef);
  const cursor = useCursor(bodyRef, columns);

  const sel = view.activities.find((a) => a.id === selected);
  const [asking, setAsking] = useState<string | null>(null);
  const add = async () => {
    const aid = await addAfter(sel, view);
    if (aid) cursor.setEditing({ aid, col: 'name' });
  };

  return (
    <div className="sch-table-tab">
      <Toolbar
        query={rs.query}
        onQuery={rs.setQuery}
        filter={rs.filter}
        onFilter={rs.setFilter}
        visible={visible}
        onVisible={change}
        wbs={view.wbs}
        canAdd={view.wbs.length > 0}
        canDelete={!!sel}
        progress={weightedProgress(view.activities)}
        onAdd={add}
        onDelete={() => setAsking(sel?.id ?? null)}
        onExport={() => download(`${view.name} v${view.version}.csv`, toCsv(view, columns, (aid) => texts.get(aid) ?? NO_TEXT))}
      />
      {sel && asking === sel.id && <DeleteConfirm activity={sel} onDone={() => setAsking(null)} />}
      <div className="sch-grid-wrap">
        <Grid
          rows={rs.rows}
          columns={columns}
          texts={texts}
          selected={selected}
          bodyRef={bodyRef}
          {...cursor}
          onCommit={commitCell}
          onToggle={rs.onToggle}
          onActiveCol={cursor.setActiveCol}
        />
      </div>
      <Foot rows={rs.rows.length} total={view.activities.length} />
      <RelationsPanel />
    </div>
  );
}
