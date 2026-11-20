import { lazy } from 'react';
import { expect, test } from 'vitest';
import { getProgram, programs, register, type ProgramManifest } from './registry';

const m = (id: string, over: Partial<ProgramManifest> = {}): ProgramManifest => ({
  id,
  name: id,
  icon: null,
  kind: 'system',
  defaultSize: { w: 600, h: 400 },
  component: lazy(() => import('./Placeholder')),
  ...over,
});

test('admin-only programs are hidden from users', () => {
  register(m('dev', { adminOnly: true }));
  expect(programs('user').map((p) => p.id)).not.toContain('dev');
  expect(programs('admin').map((p) => p.id)).toContain('dev');
});

test('registering the same id again replaces the entry and keeps order', () => {
  register(m('one'));
  register(m('two'));
  register(m('one', { name: '하나' }));
  const ids = programs('admin').map((p) => p.id);
  expect(ids.indexOf('one')).toBeLessThan(ids.indexOf('two'));
  expect(getProgram('one')?.name).toBe('하나');
  expect(getProgram('none')).toBeUndefined();
});
