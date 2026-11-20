// 간트 시험 전용 도우미. 화면 코드는 이 파일을 import하지 않는다. 일정·사람은 모두 가상이다.
import { render, screen } from '@testing-library/react';
import type { Activity, ScheduleView } from '../../shared/schedule/scheduleApi';
import { activity, fetchMock, makeView, setup } from '../../shared/schedule/testKit';
import { json } from '../../test-helpers';
import Gantt from './Gantt';

export * from '../../shared/schedule/testKit';

export interface TestCond {
  id: string;
  kind: string;
  params: Record<string, unknown>;
  state?: 'passed' | 'violated' | 'uncheckable' | 'off';
  text?: string;
}

/** 조건·규칙 GET 응답(입력 겹에 conds). */
export function condView(conds: TestCond[]) {
  const full = conds.map((c) => ({
    layer: 'input', text: c.text ?? c.id, source: '프롬프트', enabled: c.state !== 'off', editable: true,
    message: null, overridden_by: null, used_by: null, state: 'passed', ...c,
  }));
  return {
    schedule_id: 1, name: '5층 사무동 신축', version: 1,
    layers: { base: [], domain: [], mine: [], input: full },
    summary: { passed: full.length, violated: 0, uncheckable: 0 }, invalid: [], resources: [],
  };
}

export const FINISH_BY: TestCond = { id: 'in.finish_by', kind: 'finish_by', params: { date: '2027-11-30' }, text: '준공 2027.11.30 이전' };

/** 일정 시험 서버 + 조건 GET(conds, 없으면 빈 목록). */
export function setupGantt(view: ScheduleView = makeView(), conds: TestCond[] = []) {
  setup(view);
  const inner = fetchMock.getMockImplementation()!;
  fetchMock.mockImplementation(async (input, init) =>
    String(input) === '/api/schedules/1/conditions' ? json(200, condView(conds)) : inner(input, init),
  );
}

/** 간트차트 창(w1). */
export async function renderGantt(params: Record<string, string> = { id: '1' }) {
  const r = render(<Gantt windowId="w1" params={params} />);
  await screen.findByRole('toolbar', { name: '간트 도구' });
  return r;
}

const q = (sel: string) => document.querySelector<SVGElement | HTMLElement>(sel);
export const bar = (aid: string) => q(`[data-bar="${aid}"]`);
export const actualBar = (aid: string) => q(`[data-actual="${aid}"]`);
export const ghost = (aid: string) => q(`[data-ghost="${aid}"]`);
export const handle = (aid: string) => q(`[data-resize="${aid}"]`);
export const link = (key: string) => q(`[data-link="${key}"]`);
export const pxPerDay = () => Number(q('[data-px-per-day]')!.getAttribute('data-px-per-day'));
export const chartBody = () => q('.gt-body') as HTMLDivElement;
export const ganttGrid = () => screen.getByRole('treegrid', { name: '간트 표' });
export const leftRow = (key: string) => ganttGrid().querySelector<HTMLElement>(`[data-row="${key}"]`);
export const leftHeaders = () => [...ganttGrid().querySelectorAll('[role="columnheader"]')].map((h) => h.textContent);
export const tool = (name: string | RegExp) => screen.getByRole('button', { name });
export const num = (el: Element | null, attr: string) => Number(el!.getAttribute(attr));

/** n 개 액티비티의 가상 일정(WBS 묶음 10개). 날짜는 차례로 미룬 모양만(계산 아님). */
export function bigView(n = 200): ScheduleView {
  const day = (i: number) => {
    const d = new Date(Date.UTC(2027, 2, 2 + i));
    return d.toISOString().slice(0, 10);
  };
  const acts: Activity[] = Array.from({ length: n }, (_, i) =>
    activity([`B${String(i + 1).padStart(4, '0')}`, `가상 공정 ${i + 1}`, 'task', String((i % 10) + 1), 5, null, day(i), day(i + 6), null, null, 0, 'on_plan', i % 3, 0]),
  );
  return makeView({
    wbs: Array.from({ length: 10 }, (_, i) => ({ code: String(i + 1), name: `구역 ${i + 1}`, parent: null })),
    activities: acts,
    relations: acts.slice(1).map((a, i) => ({ pred: acts[i].id, succ: a.id, type: 'FS' as const, lag: 0 })),
    finish: day(n + 6),
    plan_finish: day(n + 6),
  });
}
