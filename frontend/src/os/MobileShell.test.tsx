// 스마트폰 전용 MobileShell(폭 <= 768px 자동 전환) 단위 시험.
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeAll, beforeEach, expect, test, vi } from 'vitest';
import { registerPrograms } from '../programs';
import { signInAsDemo, stubFetch } from '../test-helpers';
import { useAgentView } from './agentView';
import App from './App';
import { useApprovals } from './approvals';
import { useSession } from './session';
import { resetShellState } from './shellReset';
import { useTabletRail } from './tabletRailStore';
import { detectClientDevice, useDeviceMode } from './useIsMobile';
import { useWindows } from './windowStore';

beforeAll(() => registerPrograms());

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal('innerWidth', 390);
  vi.stubGlobal('innerHeight', 844);
  signInAsDemo('user', '김현장', 'field-user', 2);
  stubFetch({
    '/api/approvals/count': { pending: 3 },
    '/api/schedules': [],
    '/api/chat/sessions': [],
  });
});

afterEach(() => {
  cleanup();
  resetShellState();
  vi.unstubAllGlobals();
  useWindows.getState().reset();
  useApprovals.setState({ pending: 0 });
  useTabletRail.getState().load(null);
  useSession.getState().logout();
});

test('renders MobileShell on <=768px and switches tabs, schedule sub-tabs, and more grid by role', async () => {
  render(<App />);
  expect(screen.getByTestId('mobile-shell')).toBeVisible();
  expect(screen.queryByTestId('desktop-surface')).toBeNull();

  const nav = screen.getByRole('navigation', { name: '모바일 탐색' });
  expect(within(nav).getByRole('button', { name: /대화/ })).toBeVisible();
  expect(within(nav).getByRole('button', { name: /일정/ })).toBeVisible();
  expect(within(nav).getByRole('button', { name: /승인/ })).toBeVisible();
  expect(within(nav).getByRole('button', { name: /자료함/ })).toBeVisible();
  expect(within(nav).getByRole('button', { name: /전체/ })).toBeVisible();

  // 일정 탭 → 5개 세그먼트(스케줄·간트·공정률·지연·현장 점검)
  await userEvent.click(within(nav).getByRole('button', { name: /일정/ }));
  const sub = screen.getByRole('tablist', { name: '일정 보기 전환' });
  expect(within(sub).getByRole('tab', { name: '스케줄' })).toHaveAttribute('aria-selected', 'true');
  await userEvent.click(within(sub).getByRole('tab', { name: '공정률' }));
  expect(within(sub).getByRole('tab', { name: '공정률' })).toHaveAttribute('aria-selected', 'true');
  expect(within(sub).getByRole('tab', { name: '현장 점검' })).toBeVisible();

  // 전체 탭 → 일반 사용자는 개발 콘솔이 보이지 않는다
  await userEvent.click(within(nav).getByRole('button', { name: /전체/ }));
  const main = screen.getByRole('main');
  expect(within(main).getByRole('button', { name: '자료함' })).toBeVisible();
  expect(within(main).queryByRole('button', { name: '개발 콘솔' })).toBeNull();

  // useWindows.open('library') 호출 시 자료함 탭으로 자동 이동
  act(() => {
    useWindows.getState().open('library');
  });
  expect(within(nav).getByRole('button', { name: /자료함/ })).toHaveAttribute('aria-current', 'page');

  // 화면 형태 전환(스마트폰 → 태블릿 전용 셸 → PC 창)
  await userEvent.selectOptions(screen.getByRole('combobox', { name: '화면 형태' }), 'tablet');
  const tablet = screen.getByTestId('tablet-shell');
  expect(tablet).toBeVisible();
  expect(tablet).toHaveAttribute('data-device', 'tablet');
  const rail = screen.getByRole('navigation', { name: '태블릿 탐색' });
  await userEvent.click(within(rail).getByRole('button', { name: '현장 점검' }));
  expect(within(rail).getByRole('button', { name: '현장 점검' })).toHaveAttribute('aria-current', 'page');

  // 태블릿 좌우 분할 전환 및 전체 앱 서랍 권한 필터 확인
  const splitBtn = screen.getByRole('button', { name: '좌우 분할' });
  await userEvent.click(splitBtn);
  expect(screen.getByRole('complementary', { name: '보조 분할 화면' })).toBeVisible();
  await userEvent.click(within(rail).getByRole('button', { name: '전체 앱' }));
  const apps = screen.getByLabelText('전체 프로그램');
  expect(within(apps).getByRole('button', { name: '자료함' })).toBeVisible();
  expect(within(apps).queryByRole('button', { name: '개발 콘솔' })).toBeNull();

  await userEvent.click(screen.getByRole('button', { name: 'PC 창' }));
  expect(screen.getByTestId('desktop-surface')).toBeVisible();
});

test('phone header condenses the device switch into one 화면 형태 menu so 나가기 fits (B1)', async () => {
  useDeviceMode.getState().setMode('auto');
  render(<App />);
  const head = screen.getByTestId('mobile-shell').querySelector('header') as HTMLElement;
  expect(within(head).queryByRole('button', { name: '태블릿' })).toBeNull();
  expect(within(head).getByRole('button', { name: '나가기' })).toBeVisible();
  const pick = within(head).getByRole('combobox', { name: '화면 형태' });
  await userEvent.selectOptions(pick, 'tablet');
  expect(screen.getByTestId('tablet-shell')).toBeVisible();
});

test('auto device detection classifies phone, tablet, and desktop by User-Agent, touch, and viewport', () => {
  expect(detectClientDevice(390, 844)).toBe('phone');
  expect(detectClientDevice(820, 1180)).toBe('tablet');
  expect(detectClientDevice(1024, 1366)).toBe('tablet');
  expect(detectClientDevice(1440, 900)).toBe('desktop');

  const origUa = navigator.userAgent;
  const origTouch = navigator.maxTouchPoints;
  Object.defineProperty(navigator, 'userAgent', { value: 'Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X)', configurable: true });
  expect(detectClientDevice(1280, 900)).toBe('tablet');

  Object.defineProperty(navigator, 'userAgent', { value: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)', configurable: true });
  expect(detectClientDevice(1280, 900)).toBe('phone');

  Object.defineProperty(navigator, 'userAgent', { value: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)', configurable: true });
  Object.defineProperty(navigator, 'maxTouchPoints', { value: 5, configurable: true });
  expect(detectClientDevice(1180, 820)).toBe('tablet');

  Object.defineProperty(navigator, 'userAgent', { value: origUa, configurable: true });
  Object.defineProperty(navigator, 'maxTouchPoints', { value: origTouch, configurable: true });
  useDeviceMode.getState().setMode('auto');
});

test('field role boots into dedicated simplified mobile navigation without approvals/library/more tabs', () => {
  signInAsDemo('field', '박현장', 'site1', 3);
  render(<App />);
  expect(screen.getByTestId('mobile-shell')).toBeVisible();
  expect(screen.getByText('현장 전용')).toBeVisible();
  expect(screen.getByText('현장 모바일 점검')).toBeVisible();

  const fieldNav = screen.getByRole('navigation', { name: '모바일 현장 탐색' });
  expect(within(fieldNav).getByRole('button', { name: '현장 점검' })).toBeVisible();
  expect(within(fieldNav).getByRole('button', { name: '일정·간트' })).toBeVisible();
  expect(within(fieldNav).getByRole('button', { name: '현장 AI' })).toBeVisible();
  expect(within(fieldNav).queryByRole('button', { name: /승인|자료함|전체/ })).toBeNull();
});

test('tablet shell shows AI 대화 only side panel with collapse/expand and top WorkflowRibbon', async () => {
  vi.stubGlobal('innerWidth', 1024);
  vi.stubGlobal('innerHeight', 1366);
  signInAsDemo('admin', '관리자', 'admin', 1);
  render(<App />);
  const tablet = screen.getByTestId('tablet-shell');
  expect(tablet).toBeVisible();

  const side = screen.getByRole('complementary', { name: '보조 분할 화면' });
  expect(side).toBeVisible();
  expect(within(side).queryByRole('tab', { name: '승인함' })).toBeNull();
  expect(within(side).queryByRole('tab', { name: '현장 점검' })).toBeNull();

  await userEvent.click(within(side).getByRole('button', { name: '오른쪽 보조 패널 접기' }));
  expect(screen.queryByRole('complementary', { name: '보조 분할 화면' })).toBeNull();
  const expandBtn = screen.getByRole('button', { name: '오른쪽 보조 패널 펼치기' });
  expect(expandBtn).toBeVisible();
  await userEvent.click(expandBtn);
  expect(screen.getByRole('complementary', { name: '보조 분할 화면' })).toBeVisible();

  act(() => {
    useAgentView.getState().onToolStart({
      run_id: 33,
      n: 1,
      call_id: 'c1',
      tool: 'calc.cpm',
      program: 'cpm',
      arguments: '{"schedule_id":1}',
    });
  });
  expect(screen.getByRole('region', { name: '워크플로우 진행 상황' })).toHaveTextContent('워크플로우 #33');
  act(() => {
    useAgentView.getState().reset();
  });
});

test('tablet rail customization adds, removes, reorders via buttons and drag, persists per user, and resets', async () => {
  vi.stubGlobal('innerWidth', 1024);
  vi.stubGlobal('innerHeight', 1366);
  signInAsDemo('admin', '관리자', 'admin', 1);
  const first = render(<App />);

  const rail = () => screen.getByRole('navigation', { name: '태블릿 탐색' });
  const editIds = () =>
    Array.from(rail().querySelectorAll<HTMLElement>('[data-rail-id]')).map((el) => el.dataset.railId!);

  await userEvent.click(within(rail()).getByRole('button', { name: '메뉴 편집' }));
  expect(screen.getByLabelText('전체 프로그램')).toBeVisible();
  expect(editIds()).not.toContain('compare');
  expect(editIds()).toContain('library');

  await userEvent.click(screen.getByRole('button', { name: '비교판 메뉴에 추가' }));
  expect(editIds().at(-1)).toBe('compare');

  await userEvent.click(screen.getByRole('button', { name: '자료함 메뉴에서 빼기' }));
  expect(editIds()).not.toContain('library');

  await userEvent.click(within(rail()).getByRole('button', { name: '비교판 위로 이동' }));
  expect(editIds().indexOf('compare')).toBe(editIds().length - 2);

  const compareItem = rail().querySelector<HTMLElement>('[data-rail-id="compare"]')!;
  const chatItem = rail().querySelector<HTMLElement>('[data-rail-id="chat"]')!;
  fireEvent.dragStart(compareItem);
  fireEvent.dragOver(chatItem);
  fireEvent.drop(chatItem);
  expect(editIds()[0]).toBe('compare');
  expect(JSON.parse(localStorage.getItem('chronos.tabletRail.1')!)[0]).toBe('compare');
  expect(JSON.parse(localStorage.getItem('chronos.tabletRail.1')!)).not.toContain('library');

  await userEvent.click(within(rail()).getByRole('button', { name: '편집 완료' }));
  await userEvent.click(within(rail()).getByRole('button', { name: '비교판' }));
  expect(within(rail()).getByRole('button', { name: '비교판' })).toHaveAttribute('aria-current', 'page');

  first.unmount();
  render(<App />);
  const buttons = within(rail()).getAllByRole('button').map((b) => b.textContent);
  expect(buttons[0]).toBe('비교판');
  expect(buttons).not.toContain('자료함');

  await userEvent.click(within(rail()).getByRole('button', { name: '메뉴 편집' }));
  await userEvent.click(screen.getByRole('button', { name: '기본 메뉴 복원' }));
  expect(editIds()).toContain('library');
  expect(editIds()).not.toContain('compare');
  expect(localStorage.getItem('chronos.tabletRail.1')).toBeNull();
});

test('tablet opens primary Chat in PC-style 3-pane wide layout with collapsible side panels', async () => {
  vi.stubGlobal('innerWidth', 1024);
  vi.stubGlobal('innerHeight', 1366);
  signInAsDemo('admin', '관리자', 'admin', 1);
  const { container } = render(<App />);

  const rail = screen.getByRole('navigation', { name: '태블릿 탐색' });
  await userEvent.click(within(rail).getByRole('button', { name: '대화' }));

  const threadsToggle = await screen.findByRole('button', { name: '대화 목록' });
  expect(threadsToggle).toBeVisible();
  expect(container.querySelector('.tab-primary .ch-root.is-wide')).not.toBeNull();
  expect(container.querySelector('.tab-primary .ch-side')).not.toBeNull();
  expect(container.querySelector('.tab-primary .ch-main')).not.toBeNull();
  expect(container.querySelector('.tab-primary .ch-ctx')).not.toBeNull();
  expect(container.querySelector('.tab-side')).toBeNull();

  await userEvent.click(threadsToggle);
  expect(container.querySelector('.tab-primary .ch-side')).toBeNull();

  await userEvent.click(screen.getByRole('button', { name: '컨텍스트' }));
  expect(container.querySelector('.tab-primary .ch-ctx')).toBeNull();
});
