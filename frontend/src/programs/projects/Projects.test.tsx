// 프로젝트 관리(11-24): 왼쪽 프로젝트 목록(찾기) · 오른쪽 이름·AI 가 부를 이름·현장 주소·한 줄 소개·발주처·시공사 [취소][저장].
// 저장은 바뀐 칸만 보낸다 · 서버 오류는 그 칸 아래 · 이름을 바꾸면 메뉴바 일정 이름도 · 폰은 목록 → 자세히 한 화면씩.
// 프로젝트·사람 이름은 모두 가상이다.
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { useCurrentSchedule } from '../../os/currentSchedule';
import { programs, register } from '../../os/registry';
import { useDeviceMode } from '../../os/useIsMobile';
import { useUiContext } from '../../os/uiContext';
import { useWindows } from '../../os/windowStore';
import { json, signInAsDemo } from '../../test-helpers';
import manifest from './index';
import Projects from './Projects';
import css from './projects.css?raw';
import type { Project } from './projectsApi';

const project = (over: Partial<Project>): Project => ({
  id: 1, name: '가람 물류센터 신축 2026-11-23', spoken_name: '', spoken: '가람 물류센터 신축', site_address: '', summary: '',
  client_builder: '', updated_at: null, updated_by: '', same_name: false, same_as: null, ...over,
});
const GARAM = project({});
const NARAE = project({ id: 2, name: '나래 아파트 2단지', spoken: '나래 아파트 2단지', summary: '지하 2층 지상 25층' });

let list: Project[];
let patchReply: { status: number; body: unknown } | null;
let sent: { url: string; body: unknown }[];

beforeEach(() => {
  list = [GARAM, NARAE];
  patchReply = null;
  sent = [];
  signInAsDemo('user');
  useWindows.setState({ open: vi.fn(), setTitle: vi.fn() } as never);
  useCurrentSchedule.setState({ current: { id: 1, name: GARAM.name } });
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if ((init?.method ?? 'GET') === 'GET' && url === '/api/projects') return json(200, list);
    if (init?.method === 'PATCH') {
      const body = JSON.parse(String(init.body));
      sent.push({ url, body });
      if (patchReply) return json(patchReply.status, patchReply.body);
      const id = Number(url.split('/').pop());
      const merged = { ...list.find((p) => p.id === id)!, ...body, updated_by: '김하늘', updated_at: '2026-11-24T01:00:00Z' };
      merged.spoken = merged.spoken_name || merged.spoken;
      list = list.map((p) => (p.id === id ? merged : p)); // 다시 읽는 목록에도(서버처럼)
      return json(200, merged);
    }
    return json(404, { code: 'not_found', message: '찾을 수 없습니다.' });
  }));
});
afterEach(() => {
  cleanup();
  useCurrentSchedule.setState({ current: null });
  useUiContext.getState().reset();
  useDeviceMode.getState().setMode('auto');
  vi.unstubAllGlobals();
});

const show = () => render(<Projects windowId="w1" />);
const nav = () => screen.getByRole('navigation', { name: '프로젝트 목록' });
/** 목록을 읽어 그린 뒤의 목록 단추들. */
const rows = async () => within(await screen.findByRole('navigation', { name: '프로젝트 목록' })).findAllByRole('button');
const form = () => screen.getByRole('form', { name: '프로젝트 정보' });
const box = (label: string) => within(form()).getByLabelText(label, { exact: false }) as HTMLInputElement;

test('the manifest is 프로젝트 관리, a work program hidden from field managers', () => {
  expect(manifest).toMatchObject({ id: 'projects', name: '프로젝트 관리', kind: 'work', noField: true });
  register(manifest);
  expect(programs('field').map((p) => p.id)).not.toContain('projects');
  expect(programs('user').map((p) => p.id)).toContain('projects');
});

test('the list shows every project with the name the AI says, and opens the current project', async () => {
  show();
  const found = await rows();
  expect(found.map((r) => r.textContent)).toEqual([
    expect.stringContaining('가람 물류센터 신축 2026-11-23'), expect.stringContaining('나래 아파트 2단지'),
  ]);
  expect(within(found[0]).getByText('AI: 가람 물류센터 신축')).toBeVisible();
  expect(found[0]).toHaveAttribute('aria-current', 'true');
  expect(box('프로젝트 이름').value).toBe(GARAM.name);
  expect(box('AI 가 부를 이름').placeholder).toBe('가람 물류센터 신축');
  expect(useUiContext.getState().byWindow.w1).toEqual({ program: 'projects', schedule_id: 1 });
});

test('search matches the name, the spoken name and the summary', async () => {
  list = [GARAM, NARAE, project({ id: 3, name: '다온 현장', spoken: '다온 현장', spoken_name: '다온 물류' })];
  show();
  await rows();
  const search = screen.getByRole('searchbox', { name: '프로젝트 찾기' });
  await userEvent.type(search, '25층');
  expect(within(nav()).getAllByRole('button').map((r) => r.textContent)).toEqual([expect.stringContaining('나래')]);
  await userEvent.clear(search);
  await userEvent.type(search, '다온 물류');
  expect(within(nav()).getAllByRole('button').map((r) => r.textContent)).toEqual([expect.stringContaining('다온 현장')]);
  await userEvent.type(search, '없는말');
  expect(within(nav()).getByText('찾는 프로젝트가 없습니다.')).toBeVisible();
});

test('save sends only the changed fields, then shows the saved state and renames the menubar project', async () => {
  const reloads = useCurrentSchedule.getState().reloadToken;
  show();
  await rows();
  const save = within(form()).getByRole('button', { name: '저장' });
  expect(save).toBeDisabled();
  await userEvent.clear(box('프로젝트 이름'));
  await userEvent.type(box('프로젝트 이름'), '가람 물류센터 신축');
  await userEvent.type(box('AI 가 부를 이름'), '가람 물류센터');
  await userEvent.type(box('한 줄 소개'), '지상 4층 물류센터');
  await userEvent.click(save);

  await screen.findByText('저장했습니다.');
  expect(sent).toEqual([{ url: '/api/projects/1', body: { name: '가람 물류센터 신축', spoken_name: '가람 물류센터', summary: '지상 4층 물류센터' } }]);
  expect(within(nav()).getAllByRole('button')[0]).toHaveTextContent('AI: 가람 물류센터');
  expect(useCurrentSchedule.getState().current).toEqual({ id: 1, name: '가람 물류센터 신축' });
  expect(useCurrentSchedule.getState().reloadToken).toBe(reloads + 1);
  expect(save).toBeDisabled();
});

test('cancel puts the saved values back', async () => {
  show();
  await rows();
  await userEvent.type(box('현장 주소'), '경기도 가상시');
  await userEvent.click(within(form()).getByRole('button', { name: '취소' }));
  expect(box('현장 주소').value).toBe('');
  expect(sent).toEqual([]);
});

test('a server refusal (phone number) is shown under that field', async () => {
  patchReply = { status: 422, body: { code: 'phone_in_text', message: '한 줄 소개에 전화번호는 적을 수 없습니다(에이전트가 통화·문자에서 읽는 글입니다).', detail: { field: 'summary' } } };
  show();
  await rows();
  await userEvent.type(box('한 줄 소개'), '문의 010-0000-0000');
  await userEvent.click(within(form()).getByRole('button', { name: '저장' }));

  expect(await within(form()).findByText(/전화번호는 적을 수 없습니다/)).toBeVisible();
  expect(box('한 줄 소개').value).toBe('문의 010-0000-0000');
});

test('inputs carry the server limits', async () => {
  show();
  await rows();
  expect([box('프로젝트 이름').maxLength, box('AI 가 부를 이름').maxLength, box('현장 주소').maxLength, box('한 줄 소개').maxLength,
    box('발주처·시공사').maxLength]).toEqual([120, 40, 120, 200, 80]);
});

test('picking another project shows its values', async () => {
  show();
  await userEvent.click((await rows()).find((r) => r.textContent?.includes('나래 아파트'))!);
  expect(box('프로젝트 이름').value).toBe('나래 아파트 2단지');
  expect(box('한 줄 소개').value).toBe('지하 2층 지상 25층');
});

test('a phone shows the list, then the form alone with a way back', async () => {
  useDeviceMode.getState().setMode('phone');
  useCurrentSchedule.setState({ current: null });
  show();
  await userEvent.click((await rows()).find((r) => r.textContent?.includes('나래 아파트'))!);
  expect(screen.queryByRole('navigation', { name: '프로젝트 목록' })).toBeNull();
  expect(box('프로젝트 이름').value).toBe('나래 아파트 2단지');
  await userEvent.click(screen.getByRole('button', { name: '‹ 프로젝트 목록' }));
  expect(nav()).toBeVisible();
  expect(screen.queryByRole('form', { name: '프로젝트 정보' })).toBeNull();
});

test('a failed list read says so', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => json(500, { code: 'http_error', message: '요청을 처리할 수 없습니다.' })));
  show();
  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('요청을 처리할 수 없습니다.'));
});

test('no overflow: list and form shrink, long names wrap or cut', () => {
  expect(css).toMatch(/\.pj-root\s*\{[^}]*min-width:\s*0/);
  expect(css).toMatch(/\.pj-list\s*\{[^}]*overflow-y:\s*auto/);
  expect(css).toMatch(/\.pj-form\s*\{[^}]*overflow-y:\s*auto/);
  expect(css).toMatch(/\.pj-item-name\s*\{[^}]*text-overflow:\s*ellipsis/);
});

test('a spoken name longer than 40 characters asks for a short one until one is typed', async () => {
  const long = '아주아주 긴 이름을 가진 가상 복합 업무시설 및 판매시설 신축공사 1공구 및 부대 토목공사';
  list = [project({ name: `${long} 2026-12-01`, spoken: long })];
  show();
  await rows();
  const warn = '부를 이름을 적어 주세요 — AI 가 이 긴 이름을 그대로 부릅니다';
  expect(within(form()).getByText(warn)).toBeVisible();
  await userEvent.type(box('AI 가 부를 이름'), '가상 업무시설');
  expect(within(form()).queryByText(warn)).toBeNull();
});


test('projects whose names collide carry a chip in the list and a line in the form', async () => {
  list = [project({ same_name: true, same_as: '가람 물류센터 신축 (v2)' }),
    project({ id: 3, name: '가람 물류센터 신축 (v2)', same_name: true, same_as: GARAM.name }), NARAE];
  show();
  const found = await rows();
  const chip = '이름이 같은 프로젝트 — 부를 이름을 적어 주세요';
  expect(found.map((r) => within(r).queryByText(chip) !== null)).toEqual([true, true, false]);
  expect(within(form()).getByText(/통화에서 「가람 물류센터 신축 \(v2\)」와 구별할 수 없습니다/)).toBeVisible();
  expect(within(form()).getByText(/구별할 수 없습니다.*날짜·판 표시를 뗀 이름과도/)).toBeVisible();
  expect(within(found[0]).getByText(chip)).toHaveAttribute('title', '「가람 물류센터 신축 (v2)」와 이름이 같습니다');
  await userEvent.click(found[2]);
  expect(box('프로젝트 이름').value).toBe('나래 아파트 2단지');
  expect(within(form()).queryByText(/구별할 수 없습니다/)).toBeNull();
});


test('after a save the list is read again so other projects\' same-name marks refresh', async () => {
  list = [project({ same_name: true, same_as: '가람 물류센터 신축 (v2)' }),
    project({ id: 3, name: '가람 물류센터 신축 (v2)', same_name: true, same_as: GARAM.name })];
  show();
  await rows();
  const chip = '이름이 같은 프로젝트 — 부를 이름을 적어 주세요';
  list = [project({ spoken_name: '가람 1단지', spoken: '가람 1단지' }), project({ id: 3, name: '가람 물류센터 신축 (v2)' })];
  await userEvent.type(box('AI 가 부를 이름'), '가람 1단지');
  await userEvent.click(within(form()).getByRole('button', { name: '저장' }));
  await screen.findByText('저장했습니다.');
  await waitFor(() => expect(within(nav()).queryAllByText(chip)).toHaveLength(0));
});
