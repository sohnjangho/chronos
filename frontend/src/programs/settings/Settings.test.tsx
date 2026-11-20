import { act, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test } from 'vitest';
import { useWindows } from '../../os/windowStore';
import { signInAs } from '../../test-helpers';
import manifest from './index';
import Settings from './Settings';
import { renderAs, resetAll, sent } from './testKit';

const nav = () => screen.getByRole('navigation', { name: '설정 구역' });
const heading = () => screen.getByRole('heading', { level: 2 });

afterEach(resetAll);

test('user role sees no admin sections', () => {
  renderAs('user');
  expect(screen.queryByText('LLM 연결')).toBeNull();
  expect(within(nav()).getAllByRole('button').map((b) => b.textContent)).toEqual(['내 정보']);
});

test('admin sees the mockup sections and opens LLM 연결 first', () => {
  renderAs('admin');
  expect(within(nav()).getAllByRole('button').map((b) => b.textContent)).toEqual([
    '내 정보',
    'LLM 연결',
    '정보 API 연결',
    '작업별 모델 배정',
    '계정 (관리자·사용자)',
    '승인 수준',
  ]);
  expect(heading()).toHaveTextContent('LLM 연결');
  expect(within(nav()).getByRole('button', { name: 'LLM 연결' })).toHaveAttribute('aria-current', 'page');
});

test('내 정보 shows name, role and login id; a user sees the approval level read-only', async () => {
  renderAs('user');
  expect(heading()).toHaveTextContent('내 정보');
  for (const text of ['손장호', '사용자', 'jhsohn']) expect(screen.getByText(text)).toBeVisible();
  expect(await screen.findByText('중요한 것만')).toBeVisible();
  expect(screen.getByText('관리자가 정합니다.')).toBeVisible();
  expect(screen.queryByRole('radio')).toBeNull();
});

test('admin saves the approval level', async () => {
  const { fetchMock } = renderAs('admin', { section: 'approval' }, { 'PUT /api/settings/approval': { mode: 'auto' } });
  expect(heading()).toHaveTextContent('승인 수준');
  expect(await screen.findByRole('radio', { name: /^중요한 것만/ })).toBeChecked();
  expect(screen.getAllByRole('radio').map((r) => r.getAttribute('value'))).toEqual(['all', 'important', 'auto']);
  const save = screen.getByRole('button', { name: '저장' });
  expect(save).toBeDisabled();
  await userEvent.click(screen.getByRole('radio', { name: /^자동/ }));
  await userEvent.click(save);
  expect(await screen.findByText('저장했습니다.')).toBeVisible();
  expect(sent(fetchMock, 'PUT /api/settings/approval')).toEqual([{ mode: 'auto' }]);
  expect(save).toBeDisabled();
});

test('section param opens that section and an admin-only one falls back to 내 정보 for a user', () => {
  const first = renderAs('user', { section: 'approval' });
  expect(heading()).toHaveTextContent('내 정보');
  first.unmount();
  renderAs('admin', { section: 'assign' });
  expect(heading()).toHaveTextContent('작업별 모델 배정');
});

test('a new section param on the open window switches the section', async () => {
  const { rerender } = renderAs('admin', { section: 'me' });
  await userEvent.click(within(nav()).getByRole('button', { name: '승인 수준' }));
  expect(heading()).toHaveTextContent('승인 수준');
  rerender(<Settings windowId="w1" params={{ section: 'me' }} />);
  expect(heading()).toHaveTextContent('내 정보');
  rerender(<Settings windowId="w1" params={{ section: 'llm' }} />);
  expect(heading()).toHaveTextContent('LLM 연결');
});

test('program menus list the sections for the role and open them in the settings window', () => {
  signInAs('user');
  expect(manifest.menus?.map((m) => m.label)).toEqual(['보기']);
  expect(manifest.menus?.[0].items.map((i) => i.label)).toEqual(['내 정보']);
  signInAs('admin');
  const items = manifest.menus?.[0].items ?? [];
  expect(items.map((i) => i.label)).toEqual(['내 정보', 'LLM 연결', '정보 API 연결', '작업별 모델 배정', '계정 (관리자·사용자)', '승인 수준']);
  act(() => void useWindows.getState().open('settings'));
  const id = useWindows.getState().wins[0].id;
  act(() => items[3].action(id));
  expect(useWindows.getState().wins).toHaveLength(1);
  expect(useWindows.getState().wins[0].params).toEqual({ section: 'assign' });
});
