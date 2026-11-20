import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { useSchedule } from '../scheduleStore';
import { relationsPanel, renderSchedule, row, setup, writes } from '../testKit';

beforeEach(() => {
  localStorage.clear();
  setup();
});
afterEach(() => {
  useSchedule.getState().reset();
  vi.unstubAllGlobals();
});

const preds = () => within(relationsPanel()).getByRole('table', { name: '선행' });
const succs = () => within(relationsPanel()).getByRole('table', { name: '후행' });
const bodyRows = (t: HTMLElement) => within(t).getAllByRole('row').slice(1);

test('without a selection the panel asks to pick an activity', async () => {
  await renderSchedule();
  expect(within(relationsPanel()).getByText('액티비티를 선택하세요')).toBeVisible();
  expect(within(relationsPanel()).queryByRole('button', { name: '+ 선행 추가' })).toBeNull();
});

test('the selected activity shows its predecessors and successors with type and lag', async () => {
  await renderSchedule();
  await userEvent.click(row('A2020'));
  expect(within(relationsPanel()).getByText('A2020 지상 1~5층 골조')).toBeVisible();
  expect(bodyRows(preds()).map((r) => r.textContent)).toEqual([
    expect.stringContaining('선행A2010지하 1층 골조'),
    expect.stringContaining('선행A1040타워크레인 설치'),
  ]);
  const rows = bodyRows(succs());
  expect(rows).toHaveLength(3);
  expect(within(rows[1]).getByRole('combobox', { name: 'A2020 → A3020 관계' })).toHaveValue('SS');
  expect(within(rows[1]).getByRole('spinbutton', { name: 'A2020 → A3020 간격(일)' })).toHaveValue(30);
});

test('changing a predecessor type puts the whole list of that activity', async () => {
  await renderSchedule();
  await userEvent.click(row('A2020'));
  await userEvent.selectOptions(within(preds()).getByRole('combobox', { name: 'A1040 → A2020 관계' }), 'SS');
  await waitFor(() =>
    expect(writes().at(-1)).toEqual([
      'PUT',
      '/api/schedules/1/activities/A2020/predecessors',
      { items: [{ pred: 'A2010', type: 'FS', lag: 0 }, { pred: 'A1040', type: 'SS', lag: 0 }], base_version: 1 },
    ]),
  );
});

test('changing a successor lag puts the list of the successor', async () => {
  await renderSchedule();
  await userEvent.click(row('A2020'));
  const lag = within(succs()).getByRole('spinbutton', { name: 'A2020 → A3020 간격(일)' });
  await userEvent.clear(lag);
  await userEvent.type(lag, '25{Enter}');
  await waitFor(() =>
    expect(writes().at(-1)).toEqual([
      'PUT',
      '/api/schedules/1/activities/A3020/predecessors',
      { items: [{ pred: 'A2020', type: 'SS', lag: 25 }], base_version: 1 },
    ]),
  );
});

test('a relation can be removed', async () => {
  await renderSchedule();
  await userEvent.click(row('A2020'));
  await userEvent.click(within(preds()).getByRole('button', { name: 'A2010 → A2020 관계 지우기' }));
  await waitFor(() => expect(writes().at(-1)?.[2]).toEqual({ items: [{ pred: 'A1040', type: 'FS', lag: 0 }], base_version: 1 }));
});

test('+ 선행 추가 picks an activity from a searchable list grouped by WBS', async () => {
  await renderSchedule();
  await userEvent.click(row('A2020'));
  await userEvent.click(within(relationsPanel()).getByRole('button', { name: '+ 선행 추가' }));
  const list = screen.getByRole('listbox', { name: '선행으로 넣을 액티비티' });
  expect(within(list).getByRole('group', { name: '1 기초' })).toBeVisible();
  expect(within(list).queryByRole('option', { name: /A2020/ })).toBeNull(); // 자기 자신
  expect(within(list).queryByRole('option', { name: /A2010/ })).toBeNull(); // 이미 선행
  await userEvent.type(screen.getByRole('combobox', { name: '선행으로 넣을 액티비티' }), '착공');
  await userEvent.click(within(list).getByRole('option', { name: /착공/ }));
  await waitFor(() =>
    expect(writes().at(-1)?.[2]).toEqual({
      items: [
        { pred: 'A2010', type: 'FS', lag: 0 },
        { pred: 'A1040', type: 'FS', lag: 0 },
        { pred: 'A1010', type: 'FS', lag: 0 },
      ],
      base_version: 1,
    }),
  );
});

test('+ 후행 추가 adds the selected activity to the chosen successor', async () => {
  await renderSchedule();
  await userEvent.click(row('A3030'));
  await userEvent.click(within(relationsPanel()).getByRole('button', { name: '+ 후행 추가' }));
  await userEvent.click(within(screen.getByRole('listbox', { name: '후행으로 넣을 액티비티' })).getByRole('option', { name: /준공/ }));
  await waitFor(() =>
    expect(writes().at(-1)).toEqual([
      'PUT',
      '/api/schedules/1/activities/A4030/predecessors',
      { items: [{ pred: 'A4010', type: 'FS', lag: 0 }, { pred: 'A3030', type: 'FS', lag: 0 }], base_version: 1 },
    ]),
  );
});

test('a bad lag is not sent', async () => {
  await renderSchedule();
  await userEvent.click(row('A2020'));
  const lag = within(succs()).getByRole('spinbutton', { name: 'A2020 → A3020 간격(일)' });
  await userEvent.clear(lag);
  await userEvent.tab();
  expect(await screen.findByText('간격은 정수(일)로 넣어 주세요.')).toBeVisible();
  expect(writes()).toEqual([]);
  expect(lag).toHaveValue(30);
});
