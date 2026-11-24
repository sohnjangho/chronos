import { act, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test } from 'vitest';
import { useAgentView } from '../../os/agentView';
import { useDeviceMode } from '../../os/useIsMobile';
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
  expect(within(nav()).getAllByRole('button').map((b) => b.textContent)).toEqual([
    '내 정보',
    '화면 · 테마',
    '차트 · 표 기본값',
  ]);
});

test('admin sees the expanded sections and opens LLM 연결 first', () => {
  renderAs('admin');
  expect(within(nav()).getAllByRole('button').map((b) => b.textContent)).toEqual([
    '내 정보',
    '화면 · 테마',
    '차트 · 표 기본값',
    'LLM 연결',
    '정보 API 연결',
    '알림 연결',
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
  for (const text of ['홍길동', '사용자', 'jhsohn']) expect(screen.getByText(text)).toBeVisible();
  expect(await screen.findByText('중요한 것만')).toBeVisible();
  expect(screen.getByText('관리자가 정합니다.')).toBeVisible();
  expect(screen.queryByRole('radio')).toBeNull();
});

test('admin saves the approval level', async () => {
  const { fetchMock } = renderAs('admin', { section: 'approval' }, { 'PUT /api/settings/approval': { mode: 'auto' } });
  expect(heading()).toHaveTextContent('승인 수준');
  expect(await screen.findByRole('radio', { name: /^중요한 것만/ })).toBeChecked();
  const level = screen.getByRole('group', { name: '승인 수준' });
  expect(within(level).getAllByRole('radio').map((r) => r.getAttribute('value'))).toEqual(['all', 'important', 'auto']);
  const save = screen.getAllByRole('button', { name: '저장' })[0];
  expect(save).toBeDisabled();
  await userEvent.click(screen.getByRole('radio', { name: /^자동/ }));
  await userEvent.click(save);
  expect(await screen.findByText('저장했습니다.')).toBeVisible();
  expect(sent(fetchMock, 'PUT /api/settings/approval')).toEqual([{ mode: 'auto' }]);
  expect(save).toBeDisabled();
});

// PM 11-24: 사진 사람 판독을 누가 할지(기본 관리자만, 넓히면 사용자까지). 현장 관리자는 고를 수 없다.
test('admin widens photo human reading to users', async () => {
  const { fetchMock } = renderAs('admin', { section: 'approval' }, { 'PUT /api/settings/human-read': { role: 'user' } });
  const card = await screen.findByRole('region', { name: '사진 사람 판독' });
  expect(await within(card).findByRole('radio', { name: /^관리자만/ })).toBeChecked();
  expect(within(card).getAllByRole('radio').map((r) => r.getAttribute('value'))).toEqual(['admin', 'user']);
  await userEvent.click(within(card).getByRole('radio', { name: /^관리자와 사용자/ }));
  await userEvent.click(within(card).getByRole('button', { name: '저장' }));
  expect(await within(card).findByText('저장했습니다.')).toBeVisible();
  expect(sent(fetchMock, 'PUT /api/settings/human-read')).toEqual([{ role: 'user' }]);
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
  expect(manifest.menus?.[0].items.map((i) => i.label)).toEqual(['내 정보', '화면 · 테마', '차트 · 표 기본값']);
  signInAs('admin');
  const items = manifest.menus?.[0].items ?? [];
  expect(items.map((i) => i.label)).toEqual([
    '내 정보',
    '화면 · 테마',
    '차트 · 표 기본값',
    'LLM 연결',
    '정보 API 연결',
    '알림 연결',
    '작업별 모델 배정',
    '계정 (관리자·사용자)',
    '승인 수준',
  ]);
  act(() => void useWindows.getState().open('settings'));
  const id = useWindows.getState().wins[0].id;
  act(() => items.find((i) => i.label === '작업별 모델 배정')!.action(id));
  expect(useWindows.getState().wins).toHaveLength(1);
  expect(useWindows.getState().wins[0].params).toEqual({ section: 'assign' });
});

test('user updates own profile name and password in 내 정보', async () => {
  const { fetchMock } = renderAs('user', { section: 'me' }, {
    'PATCH /api/auth/me': { id: 1, name: '임꺽정', role: 'user' },
  });
  await userEvent.clear(screen.getByLabelText('표시 이름'));
  await userEvent.type(screen.getByLabelText('표시 이름'), '임꺽정');
  await userEvent.type(screen.getByLabelText('새 비밀번호'), 'new-secret-9');
  await userEvent.click(screen.getByRole('button', { name: '변경 저장' }));
  expect(await screen.findByText('내 정보를 저장했습니다.')).toBeVisible();
  expect(sent(fetchMock, 'PATCH /api/auth/me')).toEqual([{ name: '임꺽정', password: 'new-secret-9' }]);
});

test('화면 · 테마 toggles theme and 차트 · 표 기본값 renders gantt palette swatches', async () => {
  renderAs('user', { section: 'appearance' });
  expect(heading()).toHaveTextContent('화면 · 테마');
  await userEvent.click(screen.getByRole('button', { name: /야간 모드/ }));
  expect(document.documentElement.dataset.theme).toBe('dark');
  await userEvent.click(screen.getByRole('button', { name: /주간 모드/ }));
  expect(document.documentElement.dataset.theme).toBe('light');

  await userEvent.click(screen.getByRole('button', { name: /^워크플로우 창만 포커스/ }));
  expect(useAgentView.getState().mode).toBe('workflow');
  await userEvent.click(screen.getByRole('button', { name: /^끄기/ }));
  expect(useAgentView.getState().mode).toBe('off');
  await userEvent.click(screen.getByRole('button', { name: /^스마트폰/ }));
  expect(useDeviceMode.getState().mode).toBe('phone');
  useDeviceMode.getState().setMode('auto');

  await userEvent.click(within(nav()).getByRole('button', { name: '차트 · 표 기본값' }));
  expect(heading()).toHaveTextContent('차트 · 표 기본값');
  expect(screen.getByRole('group', { name: 'Plan (기준 계획) 색상' })).toBeVisible();
  expect(screen.getByRole('slider', { name: '크리티컬 연결선 투명도' })).toBeVisible();
});

test('승인 수준 has button to open DevConsole agent settings tab', async () => {
  renderAs('admin', { section: 'approval' });
  await userEvent.click(screen.getByRole('button', { name: '개발 콘솔에서 에이전트 설정 열기' }));
  const wins = useWindows.getState().wins;
  expect(wins.some((w) => w.programId === 'devconsole' && w.params?.tab === 'harness')).toBe(true);
});
