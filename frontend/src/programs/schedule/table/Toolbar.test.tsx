import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { useSchedule } from '../scheduleStore';
import {
  cell,
  editCell,
  headers,
  makeView,
  mockPatch,
  renderSchedule,
  row,
  rowOrNull,
  server,
  setup,
  toolbar,
  writes,
} from '../testKit';

beforeEach(() => {
  localStorage.clear();
  setup();
});
afterEach(() => {
  useSchedule.getState().reset();
  vi.unstubAllGlobals();
});

const button = (name: string | RegExp) => within(toolbar()).getByRole('button', { name });

describe('행 추가·삭제', () => {
  test('+ 행 추가 inserts after the selected activity in its WBS and selects the new row', async () => {
    await renderSchedule();
    await userEvent.click(row('A2020'));
    const next = makeView({ version: 2 });
    next.activities.splice(6, 0, { ...next.activities[5], id: 'A4040', name: '새 액티비티', od: 5, rd: null, progress: 0, actual_start: null });
    mockPatch(next);
    await userEvent.click(button('+ 행 추가'));
    expect(writes().at(-1)).toEqual([
      'POST',
      '/api/schedules/1/activities',
      { name: '새 액티비티', kind: 'task', wbs: '2', od: 5, after: 'A2020', base_version: 1 },
    ]);
    await waitFor(() => expect(useSchedule.getState().selected).toBe('A4040'));
    expect(within(cell('A4040', '이름')).getByRole('textbox')).toHaveFocus();
  });

  test('+ 행 추가 without a selection goes into the first WBS without a predecessor', async () => {
    await renderSchedule();
    await userEvent.click(button('+ 행 추가'));
    expect(writes().at(-1)?.[2]).toEqual({ name: '새 액티비티', kind: 'task', wbs: '1', od: 5, base_version: 1 });
  });

  test('삭제 deletes the selected activity and is off without a selection', async () => {
    await renderSchedule();
    expect(button('삭제')).toBeDisabled();
    await userEvent.click(row('A3030'));
    const next = makeView({ version: 2 });
    next.activities = next.activities.filter((a) => a.id !== 'A3030');
    mockPatch(next);
    await userEvent.click(button('삭제'));
    // fix 1 m8: 창 안에서 지울 줄을 이름으로 묻는다
    const ask = screen.getByRole('alertdialog', { name: '삭제 확인' });
    expect(ask).toHaveTextContent('A3030 승강기 설치');
    expect(writes()).toEqual([]);
    await userEvent.click(within(ask).getByRole('button', { name: '지우기' }));
    expect(writes().at(-1)?.slice(0, 2)).toEqual(['DELETE', '/api/schedules/1/activities/A3030?base_version=1']);
    await waitFor(() => expect(rowOrNull('A3030')).toBeNull());
    expect(useSchedule.getState().selected).toBeNull();
    expect(screen.getByText('A3030 을(를) 지웠습니다. 되돌리기로 살릴 수 있습니다.')).toBeVisible();
  });
});

test('삭제 can be cancelled', async () => {
  await renderSchedule();
  await userEvent.click(row('A3030'));
  await userEvent.click(button('삭제'));
  await userEvent.click(within(screen.getByRole('alertdialog', { name: '삭제 확인' })).getByRole('button', { name: '취소' }));
  expect(screen.queryByRole('alertdialog')).toBeNull();
  expect(writes()).toEqual([]);
  expect(button('삭제')).toHaveFocus();
});

// fix 2 N3: 고른 줄이 바뀌면 삭제 확인을 닫는다(같은 줄로 돌아와도 다시 뜨지 않는다).
test('the delete confirmation closes when the selection changes', async () => {
  await renderSchedule();
  await userEvent.click(row('A3030'));
  await userEvent.click(button('삭제'));
  expect(screen.getByRole('alertdialog', { name: '삭제 확인' })).toBeVisible();
  await userEvent.click(row('A3010'));
  expect(screen.queryByRole('alertdialog')).toBeNull();
  await userEvent.click(row('A3030'));
  expect(screen.queryByRole('alertdialog')).toBeNull();
  expect(writes()).toEqual([]);
});

describe('찾기·거르기', () => {
  test('search keeps matching ids or names and their WBS rows', async () => {
    await renderSchedule();
    await userEvent.type(within(toolbar()).getByRole('searchbox', { name: '코드·이름 검색' }), '골조');
    expect(row('A2010')).toBeVisible();
    expect(row('A2020')).toBeVisible();
    expect(row('wbs:2')).toBeVisible();
    expect(rowOrNull('A3010')).toBeNull();
    expect(rowOrNull('wbs:3')).toBeNull();
    await userEvent.clear(within(toolbar()).getByRole('searchbox', { name: '코드·이름 검색' }));
    await userEvent.type(within(toolbar()).getByRole('searchbox', { name: '코드·이름 검색' }), 'a30');
    expect(row('A3010')).toBeVisible();
    expect(rowOrNull('A2020')).toBeNull();
  });

  test('filter by status, critical and WBS', async () => {
    await renderSchedule();
    await userEvent.click(button('필터'));
    const panel = screen.getByRole('dialog', { name: '필터' });
    await userEvent.click(within(panel).getByRole('checkbox', { name: '지연' }));
    expect(row('A2020')).toBeVisible();
    expect(rowOrNull('A3010')).toBeNull();
    expect(button('필터 1')).toBeVisible();
    await userEvent.click(within(panel).getByRole('checkbox', { name: '지연' }));
    await userEvent.click(within(panel).getByRole('checkbox', { name: '크리티컬만' }));
    expect(rowOrNull('A3020')).toBeNull();
    expect(row('A3010')).toBeVisible();
    await userEvent.selectOptions(within(panel).getByRole('combobox', { name: 'WBS' }), '4 마감');
    expect(row('A4010')).toBeVisible();
    expect(rowOrNull('A3010')).toBeNull();
    await userEvent.click(within(panel).getByRole('button', { name: '필터 지우기' }));
    expect(row('A3020')).toBeVisible();
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('dialog', { name: '필터' })).toBeNull();
  });
});

describe('열 고르기', () => {
  test('columns can be hidden and the optional columns the API provides can be shown', async () => {
    await renderSchedule();
    await userEvent.click(button('열'));
    const panel = screen.getByRole('dialog', { name: '열' });
    await userEvent.click(within(panel).getByRole('checkbox', { name: '가중치(%)' }));
    expect(headers()).not.toContain('가중치(%)');
    for (const name of ['제약', 'ES', 'EF', '주요 자원']) await userEvent.click(within(panel).getByRole('checkbox', { name }));
    expect(headers()).toEqual(expect.arrayContaining(['제약', 'ES', 'EF', '주요 자원']));
    expect(cell('A2020', '주요 자원')).toHaveTextContent('타워크레인');
    expect(cell('A2020', 'ES')).toHaveTextContent('2027.05.06');
    // API 가 주지 않는 칸은 고를 수 없다(지어내지 않는다)
    for (const name of ['LS', 'LF', '납기', '메모', '담당']) expect(within(panel).queryByRole('checkbox', { name })).toBeNull();
  });

  test('the chosen columns are remembered for the user', async () => {
    const view = await renderSchedule();
    await userEvent.click(button('열'));
    await userEvent.click(within(screen.getByRole('dialog', { name: '열' })).getByRole('checkbox', { name: 'RD' }));
    view.unmount();
    useSchedule.getState().reset();
    await renderSchedule();
    expect(headers()).not.toContain('RD');
  });

  test('the constraint column is edited as "SNET 2027.03.08" and cleared when empty', async () => {
    await renderSchedule();
    await userEvent.click(button('열'));
    await userEvent.click(within(screen.getByRole('dialog', { name: '열' })).getByRole('checkbox', { name: '제약' }));
    await userEvent.keyboard('{Escape}');
    await editCell('A2020', '제약', 'snet 2027.05.10');
    await waitFor(() => expect(writes().at(-1)?.[2]).toEqual({ constraint: { type: 'SNET', date: '2027-05-10' }, base_version: 1 }));
    await editCell('A2020', '제약', 'SNETX');
    expect(await screen.findByText('제약 형식이 맞지 않습니다: SNETX (예 SNET 2027.03.08)')).toBeVisible();
  });
});

describe('되돌리기·다시 하기 (버전 API)', () => {
  test('undo restores the version before my change, redo restores the undone one', async () => {
    await renderSchedule();
    expect(button('되돌리기')).toBeDisabled();
    expect(button('다시 하기')).toBeDisabled();
    server.versions = [{ n: 2, note: 'A2020 기간 50 → 52', by_kind: 'user', by_name: '김하늘', is_plan: false, created_at: '2026-11-20T01:00:00Z' }];
    await editCell('A2020', 'OD', '52');
    await waitFor(() => expect(button('되돌리기')).toBeEnabled());
    await waitFor(() => expect(button('되돌리기')).toHaveAttribute('title', '되돌리기: A2020 기간 50 → 52'));
    await userEvent.click(button('되돌리기'));
    expect(writes().at(-1)).toEqual(['POST', '/api/schedules/1/versions/1/restore', { base_version: 2 }]);
    expect(await screen.findByText('되돌렸습니다: A2020 기간 50 → 52')).toBeVisible();
    await waitFor(() => expect(button('다시 하기')).toBeEnabled());
    expect(button('되돌리기')).toBeDisabled();
    await userEvent.click(button('다시 하기'));
    expect(writes().at(-1)).toEqual(['POST', '/api/schedules/1/versions/2/restore', { base_version: 3 }]);
    await waitFor(() => expect(button('되돌리기')).toBeEnabled());
  });

  test('after a conflict reload there is nothing to undo', async () => {
    await renderSchedule();
    await editCell('A2020', 'OD', '52');
    await waitFor(() => expect(button('되돌리기')).toBeEnabled());
    mockPatch(409, { code: 'version_conflict', message: 'x', detail: { current: 5 } });
    server.view = makeView({ version: 5 });
    await editCell('A3010', 'OD', '36');
    await screen.findByText('그 사이 일정이 바뀌어 다시 불러왔습니다');
    expect(button('되돌리기')).toBeDisabled();
  });
});

describe('그 밖의 도구', () => {
  test('CSV export writes the visible columns of every activity', async () => {
    const blobs: Blob[] = [];
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: (b: Blob) => (blobs.push(b), 'blob:x'), revokeObjectURL: () => {} }));
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    await renderSchedule();
    await userEvent.click(button('CSV 내보내기'));
    expect(click).toHaveBeenCalled();
    const text = await blobs[0].text();
    const lines = text.replace(/^\uFEFF/, '').trim().split('\r\n');
    expect(lines[0]).toBe('ID,이름,유형,WBS,가중치(%),OD,RD,Plan 시작,Plan 종료,Actual 시작,Actual 종료,진도(%),상태,TF,FF,선행');
    expect(lines).toHaveLength(12);
    expect(lines).toContain('A2020,지상 1~5층 골조,작업,2 골조,20.2,50,32,2027.05.06,2027.07.14,2027.05.11,,36,지연 +4일,0,0,"A2010, A1040"');
  });

  test('the weighted progress of the whole schedule is shown', async () => {
    await renderSchedule();
    expect(within(toolbar()).getByText('전체 가중 진척도 28.6%')).toBeVisible();
    expect(within(toolbar()).getByText('가중치 방식 기간 비례')).toBeVisible();
  });

  test('features the server cannot do yet have no buttons', async () => {
    await renderSchedule();
    expect(within(toolbar()).queryByRole('button', { name: /CSV 가져오기/ })).toBeNull();
    expect(within(toolbar()).queryByRole('button', { name: /가중치 방식/ })).toBeNull();
  });
});
