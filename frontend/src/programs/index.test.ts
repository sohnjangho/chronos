import type { ReactElement } from 'react';
import { expect, test } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { getProgram, programs } from '../os/registry';
import { registerPrograms } from './index';

test('every program is registered with its id, name, kind and size', () => {
  registerPrograms();
  const rows = programs('user').map((p) => [p.id, p.name, p.kind, p.defaultSize.w, p.defaultSize.h]);
  expect(rows).toEqual([
    ['chat', '에이전트 대화', 'system', 480, 760],
    ['questionnaire', '질문지', 'system', 1180, 860],
    ['workflow', '워크플로우', 'system', 1400, 860],
    ['approvals', '승인함', 'system', 1200, 760],
    ['explorer', '탐색기', 'system', 1100, 720],
    ['settings', '설정', 'system', 1300, 860],
    ['schedule-table', '스케줄', 'work', 1600, 900],
    ['gantt', '간트차트', 'work', 1600, 900],
    ['cpm', 'CPM', 'work', 1600, 900],
    ['progress', '공정률', 'work', 1400, 860],
    ['compare', '비교판', 'work', 1600, 900],
    ['conditions', '조건·규칙', 'work', 1400, 860],
    ['delays', '지연 기록', 'work', 1400, 860],
  ]);
  expect(programs('user').filter((p) => p.badge === 'approvals').map((p) => p.id)).toEqual(['approvals']);
  expect(programs('user').some((p) => p.adminOnly)).toBe(false);
});

test('the schedule board is gone: its four tool programs each have their own icon and tone', () => {
  registerPrograms();
  expect(getProgram('schedule')).toBeUndefined();
  const tools = ['schedule-table', 'gantt', 'cpm', 'progress'].map((id) => getProgram(id)!);
  expect(new Set(tools.map((p) => p.tone)).size).toBe(4);
  const drawings = tools.map((p) => renderToStaticMarkup(p.icon as ReactElement));
  expect(new Set(drawings).size).toBe(4);
  expect(drawings.every((d) => d.startsWith('<svg'))).toBe(true);
});

test('devconsole is registered after settings and shows for admins only', () => {
  registerPrograms();
  const ids = (role: 'admin' | 'user') => programs(role).map((p) => p.id);
  expect(ids('admin')).toEqual([
    'chat', 'questionnaire', 'workflow', 'approvals', 'explorer', 'settings', 'devconsole',
    'schedule-table', 'gantt', 'cpm', 'progress', 'compare', 'conditions', 'delays',
  ]);
  expect(ids('user')).not.toContain('devconsole');
  const dev = getProgram('devconsole')!;
  expect([dev.name, dev.kind, dev.adminOnly, dev.defaultSize]).toEqual(['개발 콘솔', 'system', true, { w: 1600, h: 900 }]);
});

test('every program has its own tile tone', () => {
  registerPrograms();
  const tones = programs('admin').map((p) => p.tone);
  expect(new Set(tones).size).toBe(tones.length);
});
