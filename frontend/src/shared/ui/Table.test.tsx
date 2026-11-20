import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test, vi } from 'vitest';
import Table, { type Column } from './Table';

interface Row {
  id: string;
  name: string;
  od: number;
}
const rows: Row[] = [
  { id: 'A1020', name: '터파기·흙막이', od: 15 },
  { id: 'A1030', name: '기초 철근·타설', od: 15 },
];
const columns: Column<Row>[] = [
  { key: 'id', header: 'ID', width: 110 },
  { key: 'name', header: '이름' },
  { key: 'od', header: 'OD', align: 'right', render: (r) => `${r.od}일` },
];

test('table renders headers and cells', () => {
  render(<Table columns={columns} rows={rows} rowKey={(r) => r.id} label="액티비티" />);
  const table = screen.getByRole('table', { name: '액티비티' });
  expect(within(table).getAllByRole('columnheader').map((h) => h.textContent)).toEqual(['ID', '이름', 'OD']);
  expect(within(table).getByText('터파기·흙막이')).toBeInTheDocument();
  expect(within(table).getAllByText('15일')).toHaveLength(2);
});

test('row click and selection', async () => {
  const onRowClick = vi.fn();
  render(<Table columns={columns} rows={rows} rowKey={(r) => r.id} onRowClick={onRowClick} selectedKey="A1030" />);
  const row = screen.getByText('기초 철근·타설').closest('tr')!;
  expect(row).toHaveAttribute('aria-selected', 'true');
  await userEvent.click(screen.getByText('터파기·흙막이'));
  expect(onRowClick).toHaveBeenCalledWith(rows[0]);
});

test('empty table shows a message', () => {
  render(<Table columns={columns} rows={[]} rowKey={(r) => r.id} />);
  expect(screen.getByText('자료가 없습니다.')).toBeInTheDocument();
});
