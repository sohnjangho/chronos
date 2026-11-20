import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { expect, test, vi } from 'vitest';
import Tabs from './Tabs';

const items = [
  { id: 'table', label: '스케줄표' },
  { id: 'gantt', label: '간트' },
  { id: 'cpm', label: 'CPM' },
];

test('tabs mark the selected tab and report clicks', async () => {
  const onChange = vi.fn();
  render(<Tabs items={items} value="gantt" onChange={onChange} label="일정 보기" />);
  expect(screen.getByRole('tablist', { name: '일정 보기' })).toBeInTheDocument();
  expect(screen.getByRole('tab', { name: '간트' })).toHaveAttribute('aria-selected', 'true');
  expect(screen.getByRole('tab', { name: '스케줄표' })).toHaveAttribute('aria-selected', 'false');
  await userEvent.click(screen.getByRole('tab', { name: 'CPM' }));
  expect(onChange).toHaveBeenCalledWith('cpm');
});

test('arrow keys move between tabs', async () => {
  function Host() {
    const [v, setV] = useState('table');
    return <Tabs items={items} value={v} onChange={setV} label="일정 보기" />;
  }
  render(<Host />);
  screen.getByRole('tab', { name: '스케줄표' }).focus();
  await userEvent.keyboard('{ArrowRight}');
  expect(screen.getByRole('tab', { name: '간트' })).toHaveAttribute('aria-selected', 'true');
  expect(screen.getByRole('tab', { name: '간트' })).toHaveFocus();
  await userEvent.keyboard('{ArrowLeft}{ArrowLeft}');
  expect(screen.getByRole('tab', { name: 'CPM' })).toHaveAttribute('aria-selected', 'true');
});
