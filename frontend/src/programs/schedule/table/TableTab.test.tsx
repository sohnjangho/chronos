import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { useUiContext } from '../../../os/uiContext';
import { useSchedule } from '../scheduleStore';
import {
  cell,
  editCell,
  headers,
  holdNextWrite,
  lastBody,
  loadSpy,
  makeView,
  mockPatch,
  relationsPanel,
  renderSchedule,
  row,
  rowOrNull,
  setup,
  table,
  toggle,
  viewWith,
  writes,
} from '../testKit';

const chatStore = { getState: () => ({ ui: useUiContext.getState().byWindow.w1 }) };

beforeEach(() => {
  localStorage.clear();
  setup();
});
afterEach(() => {
  useSchedule.getState().reset();
  vi.unstubAllGlobals();
});

describe('지시서 시험', () => {
  test('editing OD patches with base_version and re-renders', async () => {
    await renderSchedule();
    mockPatch(viewWith({ version: 2, finish: '2027-11-26' }));
    await editCell('A2020', 'OD', '52');
    expect(lastBody()).toEqual({ od: 52, base_version: 1 });
    expect(await screen.findByText(/2027\.11\.26/)).toBeVisible();
  });

  test('plan dates are read-only', async () => {
    await renderSchedule();
    expect(cell('A2020', 'Plan 시작')).not.toHaveAttribute('contenteditable');
    expect(within(cell('A2020', 'Plan 시작')).queryByRole('textbox')).toBeNull();
    await userEvent.dblClick(cell('A2020', 'Plan 시작'));
    expect(within(cell('A2020', 'Plan 시작')).queryByRole('textbox')).toBeNull();
  });

  test('server rejection shows message and restores the cell', async () => {
    await renderSchedule();
    mockPatch(422, { code: 'schedule_invalid', message: '선후 관계가 고리를 이룹니다.', detail: null });
    await editCell('A2020', '선행', 'A3010');
    expect(await screen.findByText('선후 관계가 고리를 이룹니다.')).toBeVisible();
    expect(cell('A2020', '선행')).toHaveTextContent('A2010');
  });

  test('version conflict reloads', async () => {
    await renderSchedule();
    mockPatch(409, { code: 'version_conflict', message: 'x', detail: { current: 3 } });
    await editCell('A2020', 'OD', '52');
    await waitFor(() => expect(loadSpy).toHaveBeenCalledTimes(2));
    expect(await screen.findByText('그 사이 일정이 바뀌어 다시 불러왔습니다')).toBeVisible();
  });

  test('critical TF is marked', async () => {
    await renderSchedule();
    expect(cell('A2020', 'TF')).toHaveClass('danger');
    expect(cell('A3020', 'TF')).not.toHaveClass('danger');
  });

  test('selecting a row sets chat ui context and fills relations panel', async () => {
    await renderSchedule();
    await userEvent.click(row('A2020'));
    expect(chatStore.getState().ui.selected_activity).toBe('A2020');
    expect(within(relationsPanel()).getByText('지하 1층 골조')).toBeVisible();
  });

  test('wbs row collapses its children', async () => {
    await renderSchedule();
    await userEvent.click(toggle('2 골조'));
    expect(screen.queryByText('A2020')).toBeNull();
    expect(toggle('2 골조')).toHaveAttribute('aria-expanded', 'false');
    await userEvent.click(toggle('2 골조'));
    expect(row('A2020')).toBeVisible();
  });
});

describe('칸 (R2)', () => {
  test('default columns follow design 8-1 in order', async () => {
    await renderSchedule();
    expect(headers()).toEqual([
      'ID', '이름', '유형', 'WBS', '가중치(%)', 'OD', 'RD', 'Plan 시작', 'Plan 종료',
      'Actual 시작', 'Actual 종료', '진도(%)', '상태', 'TF', 'FF', '선행',
    ]);
  });

  test('cells show the activity in Korean and dotted dates', async () => {
    await renderSchedule();
    expect(cell('A2020', '유형')).toHaveTextContent('작업');
    expect(cell('A1010', '유형')).toHaveTextContent('시작 마일스톤');
    expect(cell('A2020', 'WBS')).toHaveTextContent('2 골조');
    expect(cell('A2020', '가중치(%)')).toHaveTextContent('20.2');
    expect(cell('A2020', 'Plan 시작')).toHaveTextContent('2027.05.06');
    expect(cell('A2020', 'Actual 종료')).toHaveTextContent('');
    expect(cell('A2020', '진도(%)')).toHaveTextContent('36');
    expect(cell('A2020', '상태')).toHaveTextContent('지연 +4일');
    expect(cell('A1040', '상태')).toHaveTextContent('선행 -2일');
    expect(cell('A2010', '상태')).toHaveTextContent('완료');
    expect(cell('A3010', '상태')).toHaveTextContent('계획 내');
    expect(cell('A2020', '선행')).toHaveTextContent('A2010, A1040');
    expect(cell('A1040', '선행')).toHaveTextContent('A1030 SS+10');
  });

  test('a long name is cut with the full name as title', async () => {
    const view = makeView();
    view.activities[5] = { ...view.activities[5], name: '지상 1~5층 골조 및 코어월 슬립폼 시공과 각 층 슬래브 타설(가설 포함)' };
    setup(view);
    await renderSchedule();
    expect(cell('A2020', '이름')).toHaveAttribute('title', view.activities[5].name);
  });

  test('WBS rows are bold summaries with weight and plan span', async () => {
    await renderSchedule();
    const group = row('wbs:2');
    expect(group).toHaveClass('sch-group');
    expect(group).toHaveTextContent('2 골조');
    expect(group).toHaveTextContent('27.4');
    expect(group).toHaveTextContent('2027.04.12');
    expect(group).toHaveTextContent('2027.07.14');
  });

  test.each([
    ['이름', '지상 골조', { name: '지상 골조' }],
    ['RD', '30', { rd: 30 }],
    ['RD', '', { rd: null }],
    ['Actual 시작', '2027.05.12', { actual_start: '2027-05-12' }],
    ['Actual 종료', '2027-07-20', { actual_finish: '2027-07-20' }],
    ['진도(%)', '40', { progress: 0.4 }],
    ['진도(%)', '12.5', { progress: 0.125 }],
  ])('editing %s with "%s" patches %o', async (header, text, fields) => {
    await renderSchedule();
    await editCell('A2020', header, text);
    await waitFor(() => expect(lastBody()).toEqual({ ...fields, base_version: 1 }));
  });

  test('editing 선행 puts the parsed predecessors', async () => {
    await renderSchedule();
    await editCell('A2020', '선행', 'A2010, A1040 SS+15');
    await waitFor(() =>
      expect(writes().at(-1)).toEqual([
        'PUT',
        '/api/schedules/1/activities/A2020/predecessors',
        { items: [{ pred: 'A2010', type: 'FS', lag: 0 }, { pred: 'A1040', type: 'SS', lag: 15 }], base_version: 1 },
      ]),
    );
  });

  test('유형 and WBS are chosen from lists', async () => {
    await renderSchedule();
    await userEvent.dblClick(cell('A2020', '유형'));
    await userEvent.selectOptions(within(cell('A2020', '유형')).getByRole('combobox'), '종료 마일스톤');
    await waitFor(() => expect(lastBody()).toEqual({ kind: 'finish_ms', base_version: 1 }));
    await userEvent.dblClick(cell('A2020', 'WBS'));
    await userEvent.selectOptions(within(cell('A2020', 'WBS')).getByRole('combobox'), '3 외장·설비');
    await waitFor(() => expect(lastBody()).toEqual({ wbs: '3', base_version: 2 }));
  });

  test.each([
    ['OD', 'abc', 'OD는 0 이상 정수로 넣어 주세요.'],
    ['진도(%)', '120', '진도는 0~100 사이 숫자로 넣어 주세요.'],
    ['Actual 시작', '5월 12일', '날짜 형식이 맞지 않습니다: 5월 12일 (예 2027.05.12)'],
    ['이름', '   ', '이름을 넣어 주세요.'],
    ['선행', 'A2010 XX+1', '선행 형식이 맞지 않습니다: A2010 XX+1'],
  ])('a bad %s value is not sent', async (header, text, message) => {
    await renderSchedule();
    await editCell('A2020', header, text);
    expect(await screen.findByText(message)).toBeVisible();
    expect(writes()).toEqual([]);
  });

  test.each(['가중치(%)', '상태', 'TF', 'FF', 'Plan 종료', 'ID'])('%s is read-only', async (header) => {
    await renderSchedule();
    await userEvent.dblClick(cell('A2020', header));
    expect(within(cell('A2020', header)).queryByRole('textbox')).toBeNull();
    expect(within(cell('A2020', header)).queryByRole('combobox')).toBeNull();
  });

  test('Escape cancels an edit and an unchanged value sends nothing', async () => {
    await renderSchedule();
    await userEvent.dblClick(cell('A2020', 'OD'));
    await userEvent.type(within(cell('A2020', 'OD')).getByRole('textbox'), '9{Escape}');
    expect(cell('A2020', 'OD')).toHaveTextContent('50');
    await editCell('A2020', 'OD', '50');
    expect(writes()).toEqual([]);
  });

  test('the edited value shows while the request is on its way', async () => {
    await renderSchedule();
    const release = holdNextWrite();
    await editCell('A2020', 'OD', '52');
    expect(cell('A2020', 'OD')).toHaveTextContent('52');
    const next = makeView({ version: 2 });
    next.activities[5] = { ...next.activities[5], od: 52 };
    release(next);
    await waitFor(() => expect(cell('A2020', 'OD')).toHaveTextContent('52'));
  });
});

describe('키보드', () => {
  test('arrows move the selection, Enter edits the active cell', async () => {
    await renderSchedule();
    await userEvent.click(cell('A2010', 'OD'));
    expect(row('A2010')).toHaveFocus();
    await userEvent.keyboard('{ArrowDown}');
    expect(row('A2020')).toHaveFocus();
    expect(useSchedule.getState().selected).toBe('A2020');
    await userEvent.keyboard('{Enter}');
    const box = within(cell('A2020', 'OD')).getByRole('textbox');
    expect(box).toHaveFocus();
    await userEvent.clear(box);
    await userEvent.type(box, '55{Enter}');
    await waitFor(() => expect(lastBody()).toEqual({ od: 55, base_version: 1 }));
    expect(row('A2020')).toHaveFocus();
  });

  test('a WBS row collapses with ArrowLeft and opens with ArrowRight', async () => {
    await renderSchedule();
    await userEvent.click(cell('A2010', 'OD'));
    await userEvent.keyboard('{ArrowUp}');
    expect(row('wbs:2')).toHaveFocus();
    await userEvent.keyboard('{ArrowLeft}');
    expect(rowOrNull('A2010')).toBeNull();
    await userEvent.keyboard('{ArrowRight}');
    expect(row('A2010')).toBeVisible();
  });
});

describe('보내는 차례 (R8)', () => {
  test('edits are sent one at a time on the newest version', async () => {
    await renderSchedule();
    const release = holdNextWrite();
    await editCell('A2020', 'OD', '52');
    await editCell('A3010', 'OD', '36');
    expect(writes()).toHaveLength(1);
    release(makeView({ version: 2 }));
    await waitFor(() => expect(writes()).toHaveLength(2));
    expect(writes()[1][2]).toEqual({ od: 36, base_version: 2 });
  });
});

test('the table shows its row count', async () => {
  await renderSchedule();
  expect(screen.getByText(/15 행 · 액티비티 11개/)).toBeVisible();
  expect(table()).toBeVisible();
});
