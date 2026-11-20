// 왼쪽 표: WBS/ID 나무 + 고른 칸(스케줄표 칸 정의를 그대로 쓴다). 보이는 줄만 그리고, 세로 자리는 차트 본문을 따른다.
// 고치기는 스케줄표와 같은 칸 편집기·같은 요청(commitCell)이다.
import { memo, useRef, type KeyboardEvent } from 'react';
import { HEADER_H } from '../../../shared/gantt/Header';
import { ROW_H } from '../../../shared/gantt/Bars';
import CellEditor, { type EditEnd } from '../table/CellEditor';
import type { CellCtx, ColKey, ColumnDef } from '../table/columns';
import type { GanttRow } from './grouping';
import type { Viewport } from './useViewport';

export interface Editing {
  key: string;
  col: ColKey;
}

interface GridProps {
  rows: GanttRow[];
  vp: Viewport;
  width: number;
  columns: ColumnDef[];
  texts: Map<string, Omit<CellCtx, 'a'>>;
  selected: string | null;
  editing: Editing | null;
  onRowKey(e: KeyboardEvent<HTMLDivElement>, row: GanttRow, index: number): void;
  onPick(row: GanttRow): void;
  onToggle(key: string): void;
  onEdit(key: string, col: ColKey): void;
  onCommit(row: GanttRow, col: ColumnDef, text: string, initial: string, how: EditEnd): void;
  onCancel(row: GanttRow, how: EditEnd): void;
}

const NO_TEXT = { preds: '', wbsLabel: '', resources: '' };
/** 편집기 첫 값: 글 칸은 보이는 글, 고르는 칸은 지금 값(유형 코드·WBS 코드). 스케줄표와 같다. */
const initialOf = (c: ColumnDef, ctx: CellCtx) => (c.edit === 'kind' ? ctx.a.kind : c.edit === 'wbs' ? ctx.a.wbs : c.text(ctx));
const NAME_MIN = 140;
/** ID·이름 칸은 왼쪽 표를 옆으로 밀어도 붙어 있다(이름은 ID 폭만큼 오른쪽에). */
const cellStyle = (c: ColumnDef, idW: number) =>
  c.key === 'name' ? { flex: `1 0 ${NAME_MIN}px`, minWidth: NAME_MIN, left: idW } : { flex: `0 0 ${c.width}px`, ...(c.key === 'id' ? { left: 0 } : null) };
const pin = (c: ColumnDef) => (c.key === 'id' || c.key === 'name' ? ' pin' : '');
const idWidth = (columns: ColumnDef[]) => columns.find((c) => c.key === 'id')?.width ?? 0;

interface RowProps extends Omit<GridProps, 'rows' | 'vp' | 'width' | 'columns' | 'texts' | 'selected' | 'editing'> {
  row: GanttRow;
  index: number;
  columns: ColumnDef[];
  ctx: Omit<CellCtx, 'a'>;
  selected: boolean;
  tabbable: boolean;
  editingCol: ColKey | null;
}

function GroupCells({ row, columns, onToggle }: Pick<RowProps, 'row' | 'columns' | 'onToggle'>) {
  const w = idWidth(columns) + NAME_MIN;
  return (
    <div role="gridcell" className="gt-cell gt-group-cell pin" style={{ flex: `0 0 ${w}px`, left: 0, paddingLeft: 6 + row.depth * 14 }} title={row.label}>
      <button type="button" className="gt-toggle" tabIndex={-1} aria-label={row.label} aria-expanded={row.open} onClick={() => onToggle(row.key)}>
        <span aria-hidden="true">{row.open ? '▾' : '▸'}</span>
      </button>
      <span className="gt-group-name">{row.label}</span>
      <span className="gt-count">{`(${row.count ?? 0}개)`}</span>
    </div>
  );
}

/** 액티비티 줄의 칸 하나(고치는 중이면 스케줄표와 같은 칸 편집기). */
function ActivityCell({ p, c, ctx }: { p: RowProps; c: ColumnDef; ctx: CellCtx }) {
  const text = c.text(ctx);
  const editing = p.editingCol === c.key;
  const classes = ['gt-cell', c.align === 'right' && 'num', c.edit && 'editable', c.className?.(ctx)].filter(Boolean).join(' ') + pin(c);
  return (
    <div
      role="gridcell"
      data-col={c.key}
      className={classes}
      style={{ ...cellStyle(c, idWidth(p.columns)), ...(c.key === 'id' ? { paddingLeft: 6 + p.row.depth * 14 } : null) }}
      title={!editing && text ? text : undefined}
      onDoubleClick={() => p.onEdit(p.row.key, c.key)}
    >
      {editing ? (
        <CellEditor
          col={c}
          label={`${ctx.a.id} ${c.header}`}
          initial={initialOf(c, ctx)}
          onCommit={(value, how) => p.onCommit(p.row, c, value, initialOf(c, ctx), how)}
          onCancel={(how) => p.onCancel(p.row, how)}
        />
      ) : (
        (c.render?.(ctx) ?? text)
      )}
    </div>
  );
}

const LeftRow = memo(function LeftRow(p: RowProps) {
  const a = p.row.activity;
  const ctx = a ? { a, ...p.ctx } : null;
  return (
    <div
      role="row"
      data-row={p.row.key}
      aria-rowindex={p.index + 1}
      aria-selected={a ? p.selected : undefined}
      aria-expanded={p.row.kind === 'group' ? p.row.open : undefined}
      tabIndex={p.tabbable ? 0 : -1}
      className={`gt-row${p.row.kind === 'group' ? ' is-group' : ''}${p.selected ? ' is-selected' : ''}`}
      style={{ top: p.index * ROW_H }}
      onClick={() => p.onPick(p.row)}
      onKeyDown={(e) => p.onRowKey(e, p.row, p.index)}
    >
      {!ctx ? (
        <GroupCells row={p.row} columns={p.columns} onToggle={p.onToggle} />
      ) : (
        p.columns.map((c) => <ActivityCell key={c.key} p={p} c={c} ctx={ctx} />)
      )}
    </div>
  );
});

/** 간트 왼쪽 표(treegrid). 넓으면 표 본문 안에서만 옆으로 밀리고(머리가 따라옴) ID·이름 칸은 붙어 있다. */
export default function LeftGrid(p: GridProps) {
  const headRef = useRef<HTMLDivElement>(null);
  const minW = p.columns.reduce((n, c) => n + (c.key === 'name' ? NAME_MIN : c.width), 0);
  const idW = idWidth(p.columns);
  const shown = p.rows.slice(p.vp.first, p.vp.last + 1);
  const isSel = (row: GanttRow) => !!row.activity && row.activity.id === p.selected;
  const anySel = shown.some(isSel);
  return (
    <div className="gt-left" style={{ width: p.width }}>
      <div role="treegrid" aria-label="간트 표" aria-rowcount={p.rows.length} className="gt-tree">
        <div className="gt-left-head" ref={headRef} style={{ height: HEADER_H }}>
          <div role="row" className="gt-head-row" style={{ minWidth: minW }}>
            {p.columns.map((c) => (
              <div key={c.key} role="columnheader" className={`gt-cell${c.align === 'right' ? ' num' : ''}${pin(c)}`} style={cellStyle(c, idW)}>
                {c.key === 'id' ? 'WBS / ID' : c.header}
              </div>
            ))}
          </div>
        </div>
        <div
          className="gt-left-body"
          ref={p.vp.leftRef}
          onWheel={(e) => p.vp.nav.wheel(e.deltaY)}
          onScroll={(e) => headRef.current && (headRef.current.scrollLeft = e.currentTarget.scrollLeft)}
        >
          <div className="gt-left-spacer" style={{ height: p.rows.length * ROW_H + p.vp.scrollbarH, minWidth: minW }}>
            {shown.map((row, i) => (
              <LeftRow
                key={row.key}
                row={row}
                index={p.vp.first + i}
                columns={p.columns}
                ctx={(row.activity && p.texts.get(row.activity.id)) || NO_TEXT}
                selected={isSel(row)}
                tabbable={isSel(row) || (!anySel && i === 0)}
                editingCol={p.editing?.key === row.key ? p.editing.col : null}
                onRowKey={p.onRowKey}
                onPick={p.onPick}
                onToggle={p.onToggle}
                onEdit={p.onEdit}
                onCommit={p.onCommit}
                onCancel={p.onCancel}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
