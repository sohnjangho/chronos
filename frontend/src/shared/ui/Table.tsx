import type { KeyboardEvent, ReactNode } from 'react';
import './ui.css';

export interface Column<T> {
  key: string;
  header: string;
  width?: number;
  align?: 'left' | 'right' | 'center';
  /** 없으면 row[key] 를 글로 보인다. */
  render?: (row: T) => ReactNode;
}

export interface TableProps<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  label?: string;
  onRowClick?: (row: T) => void;
  selectedKey?: string;
  empty?: ReactNode;
}

export default function Table<T>({ columns, rows, rowKey, label, onRowClick, selectedKey, empty }: TableProps<T>) {
  const cell = (row: T, c: Column<T>) =>
    c.render ? c.render(row) : String((row as Record<string, unknown>)[c.key] ?? '');
  const onRowKey = (e: KeyboardEvent, row: T) => {
    // 행 안의 단추·입력 칸에서 누른 Enter·Space 는 그 칸의 몫이다.
    if (!onRowClick || e.target !== e.currentTarget || (e.key !== 'Enter' && e.key !== ' ')) return;
    e.preventDefault();
    onRowClick(row);
  };
  return (
    <table className="ui-table" aria-label={label}>
      <thead>
        <tr>
          {columns.map((c) => (
            <th key={c.key} style={{ width: c.width, textAlign: c.align }}>
              {c.header}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.length === 0 && (
          <tr>
            <td className="ui-table-empty" colSpan={columns.length}>
              {empty ?? '자료가 없습니다.'}
            </td>
          </tr>
        )}
        {rows.map((row) => {
          const key = rowKey(row);
          return (
            <tr
              key={key}
              className={onRowClick ? 'ui-row-click' : undefined}
              aria-current={key === selectedKey ? 'true' : undefined}
              tabIndex={onRowClick ? 0 : undefined}
              onClick={onRowClick && (() => onRowClick(row))}
              onKeyDown={(e) => onRowKey(e, row)}
            >
              {columns.map((c) => (
                <td key={c.key} style={{ textAlign: c.align }}>
                  {cell(row, c)}
                </td>
              ))}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
