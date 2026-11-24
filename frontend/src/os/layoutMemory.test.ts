// 열어 둔 창·탭의 모양: 거르기(권한·params·번호)와 화면 형태별 읽기.
import { beforeAll, expect, test } from 'vitest';
import { registerPrograms } from '../programs';
import { desktopLayout, focusOf, keptParams, phoneFor, readDesktop, readPhone, readTablet, tabletFor, type PhoneLayout } from './layoutMemory';

beforeAll(() => registerPrograms());

const PHONE_LIKE = /\d(?:[\s.-]?\d){7,}/;

test('contacts keeps only schedule id, contact id and tab — never the draft text or the call step', () => {
  expect(keptParams('contacts', { id: '3', contact: '12', tab: 'calls', compose: '내일 오전 타설 확인 부탁드립니다', call: '1', activity: 'A2020' })).toEqual({
    id: '3',
    contact: '12',
    tab: 'calls',
  });
  expect(keptParams('contacts', { tab: 'compose' })).toBeUndefined();
});

test('chat never keeps a question to ask, a draft, an attachment or a resume step', () => {
  expect(keptParams('chat', { session: '7', ask: '지연 원인 알려줘', compose: '초안', attach: '4', resume_approval: '2', resume_questionnaire: '5' })).toEqual({ session: '7' });
});

test('delays never keeps an unsent new-record form', () => {
  expect(keptParams('delays', { id: '3', activity: 'A2020', days: '2', before: '5', event: '9' })).toEqual({ id: '3' });
});

test('phone-like or free-text values never pass as ids or names', () => {
  for (const v of ['01000000000', '010-0000-0000', '15880000', '12345678', '0', '-1', '1.5', '3 ']) {
    expect(keptParams('contacts', { contact: v })).toBeUndefined();
  }
  expect(keptParams('settings', { section: 'Hello World' })).toBeUndefined();
  expect(keptParams('settings', { section: 'notify' })).toEqual({ section: 'notify' });
  expect(keptParams('explorer', { id: '1' })).toBeUndefined();
});

const desktop = (wins: unknown[], deactivated = false) => ({ v: 1, wins, deactivated });
const win = (program: string, extra: object = {}) => ({ program, x: 10, y: 60, w: 600, h: 400, min: false, max: false, ...extra });

test('desktop: wrong shape is null (→ home)', () => {
  for (const raw of [null, 'x', [], { v: 2, wins: [], deactivated: false }, { v: 1, wins: {}, deactivated: false }, desktop([{ program: 'gantt' }]), desktop([win('gantt', { x: 'a' })])]) {
    expect(readDesktop(raw, 'admin')).toBeNull();
  }
});

test('desktop: access is checked again — admin-only and field-hidden programs, unknown and duplicate ids are dropped; old ids map to new', () => {
  const raw = desktop([win('devconsole'), win('contacts'), win('nope'), win('gantt'), win('gantt'), win('schedule')]);
  expect(readDesktop(raw, 'admin')!.wins.map((w) => w.programId)).toEqual(['devconsole', 'contacts', 'gantt', 'schedule-table']);
  expect(readDesktop(raw, 'user')!.wins.map((w) => w.programId)).toEqual(['contacts', 'gantt', 'schedule-table']);
  expect(readDesktop(raw, 'field')!.wins.map((w) => w.programId)).toEqual(['gantt', 'schedule-table']);
});

test('tablet: only rail ids this person can open', () => {
  expect(readTablet({ v: 1, active: 'contacts', params: { contact: '12', compose: 'x' } }, 'user')).toEqual({ v: 1, active: 'contacts', params: { contact: '12' } });
  expect(readTablet({ v: 1, active: 'contacts' }, 'field')).toBeNull();
  expect(readTablet({ v: 1, active: 'devconsole' }, 'user')).toBeNull();
  expect(readTablet({ v: 1, active: 'field' }, 'field')).toEqual({ v: 1, active: 'field' });
  expect(readTablet({ v: 1, active: 'settings' }, 'field')).toEqual({ v: 1, active: 'settings' });
  expect(readTablet({ v: 1, active: 'schedule' }, 'user')).toBeNull();
});

test('phone: tabs by role; the old library tab is gone (→ home)', () => {
  expect(readPhone({ v: 1, tab: 'contacts', sub: 'gantt', params: { contact: '12', tab: 'calls' } }, 'user')).toEqual({
    v: 1,
    tab: 'contacts',
    sub: 'gantt',
    params: { contact: '12', tab: 'calls' },
  });
  expect(readPhone({ v: 1, tab: 'library', sub: 'gantt' }, 'user')).toBeNull();
  expect(readPhone({ v: 1, tab: 'contacts', sub: 'gantt' }, 'field')).toBeNull();
  expect(readPhone({ v: 1, tab: 'schedule', sub: 'progress' }, 'field')).toBeNull();
  expect(readPhone({ v: 1, tab: 'schedule', sub: 'field' }, 'field')).toEqual({ v: 1, tab: 'schedule', sub: 'field' });
  expect(readPhone({ v: 1, tab: 'more', sub: 'gantt', more: 'devconsole' }, 'user')).toBeNull();
  expect(readPhone({ v: 1, tab: 'more', sub: 'gantt', more: 'library' }, 'user')).toEqual({ v: 1, tab: 'more', sub: 'gantt', more: 'library' });
});

test('focus of each mode, and where it opens on the other modes', () => {
  const d = desktop([win('gantt', { params: { id: '3' } }), win('contacts', { params: { id: '3', contact: '12', tab: 'calls' } }), win('chat', { min: true })]);
  const f = focusOf('desktop', d, 'user')!;
  expect(f).toEqual({ program: 'contacts', params: { id: '3', contact: '12', tab: 'calls' } });
  const here: PhoneLayout = { v: 1, tab: 'chat', sub: 'schedule-table' };
  expect(phoneFor(f, 'user', here)).toEqual({ v: 1, tab: 'contacts', sub: 'schedule-table', params: { id: '3', contact: '12', tab: 'calls' } });
  expect(phoneFor(f, 'field', here)).toBeNull();
  expect(tabletFor(f, 'user')).toEqual({ v: 1, active: 'contacts', params: { id: '3', contact: '12', tab: 'calls' } });
  expect(focusOf('phone', { v: 1, tab: 'schedule', sub: 'field' }, 'field')).toEqual({ program: 'progress', params: { view: 'field' } });
  expect(tabletFor({ program: 'progress', params: { view: 'field' } }, 'field')).toEqual({ v: 1, active: 'field' });
  expect(focusOf('tablet', { v: 1, active: 'nope' }, 'user')).toBeNull();
});

test('nothing phone-like survives into any layout', () => {
  const p = { id: '3', contact: '010-0000-0000', tab: 'calls', compose: '010-0000-0000 으로 연락 바랍니다' };
  const all = [
    readDesktop(desktop([win('contacts', { params: p })]), 'user'),
    readTablet({ v: 1, active: 'contacts', params: p }, 'user'),
    readPhone({ v: 1, tab: 'contacts', sub: 'gantt', params: p }, 'user'),
  ];
  for (const l of all) expect(JSON.stringify(l)).not.toMatch(PHONE_LIKE);
});

test('desktop: a window with a broken (NaN / infinite) place is left out instead of saving a state the server rejects', () => {
  const w = (programId: string, x: number) => ({ id: programId, programId, title: programId, x, y: 60, w: 600, h: 400, z: 1, minimized: false, maximized: false });
  const l = desktopLayout({ wins: [w('gantt', Number.NaN), w('cpm', 10), w('delays', Number.POSITIVE_INFINITY)], deactivated: false });
  expect(l.wins.map((x) => x.program)).toEqual(['cpm']);
});
