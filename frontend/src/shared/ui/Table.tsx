import type { ReactNode } from 'react';
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
              aria-selected={selectedKey === undefined ? undefined : key === selectedKey}
              onClick={onRowClick && (() => onRowClick(row))}
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
