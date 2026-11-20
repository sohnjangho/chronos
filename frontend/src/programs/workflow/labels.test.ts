import { lazy } from 'react';
import { beforeAll, expect, test } from 'vitest';
import { register } from '../../os/registry';
import { programLabel } from './labels';

// 프로그램끼리 import 하지 않으므로 이름을 볼 프로그램은 등록부에 같은 이름으로 둔다.
beforeAll(() => {
  for (const [id, name] of [['schedule-table', '스케줄'], ['cpm', 'CPM']]) {
    register({ id, name, icon: null, kind: 'work', defaultSize: { w: 800, h: 600 }, component: lazy(() => import('../../os/Placeholder')) });
  }
});

// Task 16b 리뷰 I1: 옛 작업 흐름 단계의 program 'schedule'(일정판)이 영어 id 로 보이던 것.
test('a step of the old schedule board is named with the program it became', () => {
  expect(programLabel('schedule')).toBe('스케줄');
  expect(programLabel('schedule-table')).toBe('스케줄');
  expect(programLabel('cpm')).toBe('CPM');
  expect(programLabel(null)).toBe('뒷단 도구');
  expect(programLabel('모르는것')).toBe('모르는것');
});
