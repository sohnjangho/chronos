import type { KeyboardEvent, RefObject } from 'react';
import type { Activity } from '../scheduleApi';
import { pinClass, type ColKey, type ColumnDef } from './columns';
import Row, { GroupRow } from './Row';
import type { GridRow } from './rows';

export interface GridProps {
  rows: GridRow[];
  columns: ColumnDef[];
  /** 액티비티 id → 선행 글·WBS 이름·주요 자원 이름. */
  texts: Map<string, { preds: string; wbsLabel: string; resources: string }>;
  selected: string | null;
  activeCol: ColKey;
  focusKey: string | null;
  editing: { aid: string; col: ColKey } | null;
  bodyRef: RefObject<HTMLTableSectionElement | null>;
  onPick(aid: string, col: ColKey): void;
  onEdit(aid: string, col: ColKey): void;
  onEditEnd(aid: string, refocus: boolean): void;
  onCommit(a: Activity, col: ColumnDef, text: string): Promise<unknown>;
  onToggle(code: string, open?: boolean): void;
  onFocusRow(key: string): void;
  onActiveCol(col: ColKey): void;
}

const EMPTY = { preds: '', wbsLabel: '', resources: '' };

/** 키보드: ↑↓ 줄 옮김, ←→ 칸 옮김(묶음 줄은 접기·펴기), Enter·F2 고치기(묶음 줄은 접기·펴기). */
function useRowKeys(p: GridProps) {
  return (e: KeyboardEvent<HTMLTableSectionElement>) => {
    const tr = e.target as HTMLElement;
    if (tr.tagName !== 'TR') return;
    const i = p.rows.findIndex((r) => r.key === tr.dataset.key);
    const row = p.rows[i];
    if (!row) return;
    const step = (d: number) => {
      const next = p.rows[i + d];
      if (next) p.onFocusRow(next.key);
    };
    const cols = p.columns.map((c) => c.key);
    const at = cols.indexOf(p.activeCol);
    const keys: Record<string, () => void> = {
      ArrowDown: () => step(1),
      ArrowUp: () => step(-1),
      ArrowLeft: () => (row.kind === 'group' ? p.onToggle(row.wbs.code, false) : p.onActiveCol(cols[Math.max(0, at - 1)])),
      ArrowRight: () => (row.kind === 'group' ? p.onToggle(row.wbs.code, true) : p.onActiveCol(cols[Math.min(cols.length - 1, at + 1)])),
      Enter: () => (row.kind === 'group' ? p.onToggle(row.wbs.code) : p.onEdit(row.key, p.activeCol)),
      F2: () => row.kind === 'activity' && p.onEdit(row.key, p.activeCol),
      ' ': () => row.kind === 'group' && p.onToggle(row.wbs.code),
    };
    const run = keys[e.key];
    if (!run) return;
    e.preventDefault();
    run();
  };
}

/** 스케줄표 본체. 머리줄은 위에, ID·이름 칸은 왼쪽에 붙어 있다. */
export default function Grid(p: GridProps) {
  const onKeyDown = useRowKeys(p);
  const minWidth = p.columns.reduce((n, c) => n + c.width, 0);
  const tabKey = p.rows.some((r) => r.key === p.focusKey) ? p.focusKey : p.rows[0]?.key;
  return (
    <table className="sch-grid" aria-label="스케줄표" style={{ minWidth }}>
      <colgroup>
        {p.columns.map((c) => (
          <col key={c.key} style={c.flex ? undefined : { width: c.width }} />
        ))}
      </colgroup>
      <thead>
        <tr>
          {p.columns.map((c) => (
            <th key={c.key} scope="col" className={[c.align === 'right' && 'num', pinClass(c.key)].filter(Boolean).join(' ') || undefined}>
              {c.header}
            </th>
          ))}
        </tr>
      </thead>
      <tbody ref={p.bodyRef} onKeyDown={onKeyDown}>
        {p.rows.map((r) =>
          r.kind === 'group' ? (
            <GroupRow key={r.key} row={r} columns={p.columns} tabbable={r.key === tabKey} onToggle={p.onToggle} onFocusRow={p.onFocusRow} />
          ) : (
            <Row
              key={r.key}
              activity={r.activity}
              {...(p.texts.get(r.key) ?? EMPTY)}
              depth={r.depth}
              columns={p.columns}
              selected={r.key === p.selected}
              activeCol={r.key === p.selected ? p.activeCol : null}
              tabbable={r.key === tabKey}
              editingCol={p.editing?.aid === r.key ? p.editing.col : null}
              onPick={p.onPick}
              onEdit={p.onEdit}
              onEditEnd={p.onEditEnd}
              onCommit={p.onCommit}
            />
          ),
        )}
      </tbody>
    </table>
  );
}
