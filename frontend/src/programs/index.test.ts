import { expect, test } from 'vitest';
import { programs } from '../os/registry';
import { registerPrograms } from './index';

test('every plan-1 program is registered with its id, name, kind and size', () => {
  registerPrograms();
  const rows = programs('user').map((p) => [p.id, p.name, p.kind, p.defaultSize.w, p.defaultSize.h]);
  expect(rows).toEqual([
    ['chat', '에이전트 대화', 'system', 480, 760],
    ['questionnaire', '질문지', 'system', 1180, 860],
    ['workflow', '워크플로우', 'system', 1400, 860],
    ['approvals', '승인함', 'system', 1200, 760],
    ['explorer', '탐색기', 'system', 1100, 720],
    ['settings', '설정', 'system', 1300, 860],
    ['schedule', '일정판', 'work', 1600, 900],
    ['conditions', '조건·규칙', 'work', 1400, 860],
  ]);
  expect(programs('user').filter((p) => p.badge === 'approvals').map((p) => p.id)).toEqual(['approvals']);
  expect(programs('user').some((p) => p.adminOnly)).toBe(false);
});
