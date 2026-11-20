// 스케줄 시험 전용 도우미: 가상 일정·가짜 서버(shared 시험 도우미) + 스케줄 창과 표 찾기. 화면 코드는 import하지 않는다.
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ScheduleTable from './ScheduleTable';

export * from '../../shared/schedule/testKit';

export async function renderSchedule(params: Record<string, string> = { id: '1' }) {
  const view = render(<ScheduleTable windowId="w1" params={params} />);
  await screen.findByRole('table', { name: '스케줄표' });
  return view;
}

export const table = () => screen.getByRole('table', { name: '스케줄표' });
export const rowOrNull = (key: string) =>
  within(table()).queryAllByRole('row').find((r) => r.getAttribute('data-key') === key) ?? null;
export function row(key: string): HTMLTableRowElement {
  const r = rowOrNull(key);
  if (!r) throw new Error(`행 ${key} 이 없습니다`);
  return r as HTMLTableRowElement;
}
export const headers = () => within(table()).getAllByRole('columnheader').map((h) => h.textContent);
export function cell(aid: string, header: string): HTMLElement {
  const i = headers().indexOf(header);
  if (i < 0) throw new Error(`칸 ${header} 이 없습니다`);
  return row(aid).cells[i];
}

/** 칸을 두 번 눌러 글을 고치고 Enter. */
export async function editCell(aid: string, header: string, value: string) {
  await userEvent.dblClick(cell(aid, header));
  const box = within(cell(aid, header)).getByRole('textbox');
  await userEvent.clear(box);
  await userEvent.type(box, `${value}{Enter}`);
}

export const toggle = (name: string) => screen.getByRole('button', { name });
export const relationsPanel = () => screen.getByRole('region', { name: '관계' });
export const toolbar = () => screen.getByRole('toolbar', { name: '스케줄표 도구' });
