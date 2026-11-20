import { memo, useState } from 'react';
import { dot, percent } from '../format';
import type { Activity } from '../scheduleApi';
import CellEditor from './CellEditor';
import { pinClass, type CellCtx, type ColKey, type ColumnDef } from './columns';
import type { GridRow } from './rows';

const indent = (depth: number) => ({ paddingLeft: 10 + depth * 16 });

/** 누른 칸(없으면 지금 칸, 그것도 없으면 이름). */
const colOf = (target: EventTarget, fallback: ColKey | null): ColKey =>
  ((target as HTMLElement).closest?.('td')?.dataset.col as ColKey | undefined) ?? fallback ?? 'name';

export interface RowProps {
  activity: Activity;
  preds: string;
  wbsLabel: string;
  resources: string;
  depth: number;
  columns: ColumnDef[];
  selected: boolean;
  /** 고른 줄에서만: 키보드로 옮겨 다니는 칸. */
  activeCol: ColKey | null;
  tabbable: boolean;
  /** 고치는 중인 칸(이 줄이 아니면 null). */
  editingCol: ColKey | null;
  onPick(aid: string, col: ColKey): void;
  onEdit(aid: string, col: ColKey): void;
  onEditEnd(aid: string, refocus: boolean): void;
  /** 보내고 끝나면 true/false. 바뀐 것이 없거나 틀린 글이면 보내지 않는다. */
  onCommit(a: Activity, col: ColumnDef, text: string): Promise<unknown>;
}

/**
 * 액티비티 한 줄. memo — 이 줄의 글·고름·고침이 바뀔 때만 다시 그린다(R7).
 * 보낸 값은 답이 올 때까지 그 칸에 보이고, 서버가 거절하면 원래 값으로 돌아간다.
 */
function Row(p: RowProps) {
  const [pending, setPending] = useState<Partial<Record<ColKey, string>>>({});
  const ctx: CellCtx = { a: p.activity, preds: p.preds, wbsLabel: p.wbsLabel, resources: p.resources };

  async function commit(col: ColumnDef, text: string, initial: string, refocus: boolean) {
    p.onEditEnd(p.activity.id, refocus);
    if (text.trim() === initial.trim()) return;
    const shown = col.edit === 'kind' || col.edit === 'wbs' ? undefined : text.trim();
    if (shown !== undefined) setPending((s) => ({ ...s, [col.key]: shown }));
    await p.onCommit(p.activity, col, text);
    if (shown !== undefined) setPending(({ [col.key]: _gone, ...rest }) => (void _gone, rest));
  }

  return (
    <tr
      data-key={p.activity.id}
      tabIndex={p.tabbable ? 0 : -1}
      aria-current={p.selected ? 'true' : undefined}
      className="sch-row"
      onClick={(e) => p.onPick(p.activity.id, colOf(e.target, p.activeCol))}
      onDoubleClick={(e) => p.onEdit(p.activity.id, colOf(e.target, p.activeCol))}
    >
      {p.columns.map((col) => {
        const editing = p.editingCol === col.key;
        const text = col.text(ctx);
        const initial = col.edit === 'kind' ? p.activity.kind : col.edit === 'wbs' ? p.activity.wbs : text;
        const classes = [pinClass(col.key), col.align === 'right' && 'num', col.edit && 'editable', p.activeCol === col.key && 'active', col.className?.(ctx)];
        return (
          <td
            key={col.key}
            className={classes.filter(Boolean).join(' ') || undefined}
            style={col.key === 'id' ? indent(p.depth) : undefined}
            data-col={col.key}
            title={!editing && text ? text : undefined}
          >
            {editing ? (
              <CellEditor
                col={col}
                label={`${p.activity.id} ${col.header}`}
                initial={initial}
                onCommit={(value, refocus) => void commit(col, value, initial, refocus)}
                onCancel={(refocus) => p.onEditEnd(p.activity.id, refocus)}
              />
            ) : (
              pending[col.key] ?? (col.render ? col.render(ctx) : text)
            )}
          </td>
        );
      })}
    </tr>
  );
}

export default memo(Row);

interface GroupRowProps {
  row: Extract<GridRow, { kind: 'group' }>;
  columns: ColumnDef[];
  tabbable: boolean;
  onToggle(code: string): void;
  onFocusRow(key: string): void;
}

const GROUP_TEXT: Partial<Record<ColKey, (s: Extract<GridRow, { kind: 'group' }>['sum']) => string>> = {
  weight: (s) => percent(s.weight),
  plan_start: (s) => dot(s.planStart),
  plan_finish: (s) => dot(s.planFinish),
  actual_start: (s) => dot(s.actualStart),
  actual_finish: (s) => dot(s.actualFinish),
  progress: (s) => (s.progress === null ? '' : percent(s.progress)),
};

/** WBS 묶음 줄(굵게). 이름은 ID·이름 두 칸에 걸친다. 앞의 단추로 접고 편다. */
export const GroupRow = memo(function GroupRow({ row, columns, tabbable, onToggle, onFocusRow }: GroupRowProps) {
  const rest = columns.filter((c) => c.key !== 'id' && c.key !== 'name');
  return (
    <tr data-key={row.key} tabIndex={tabbable ? 0 : -1} className="sch-group" onClick={() => onFocusRow(row.key)}>
      <td colSpan={2} className="sch-group-label pin1" style={indent(row.depth)} title={row.label}>
        <button
          type="button"
          className="sch-toggle"
          tabIndex={-1}
          aria-label={row.label}
          aria-expanded={row.open}
          onClick={() => onToggle(row.wbs.code)}
        >
          <span aria-hidden="true">{row.open ? '▾' : '▸'}</span>
        </button>
        <span className="sch-group-name">{row.label}</span>
      </td>
      {rest.map((c) => (
        <td key={c.key} className={c.align === 'right' ? 'num' : undefined}>
          {GROUP_TEXT[c.key]?.(row.sum) ?? ''}
        </td>
      ))}
    </tr>
  );
});
