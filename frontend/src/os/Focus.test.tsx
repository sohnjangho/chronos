import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { StrictMode } from 'react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeAll, beforeEach, expect, test, vi } from 'vitest';
import { registerPrograms } from '../programs';
import { signInAsDemo, stubFetch } from '../test-helpers';
import Desktop from './Desktop';
import { useSession } from './session';
import { useContextPanel } from './contextStore';
import { useShell } from './shell';
import { useWindows } from './windowStore';
import { resetShellState } from './shellReset';

const dockButton = (name: string) =>
  within(screen.getByRole('toolbar', { name: '프로그램 막대' })).getByRole('button', { name: new RegExp(`^${name}(,|$)`) });
const ctrlAlt = (code: string) => fireEvent.keyDown(document.body, { code, key: code, ctrlKey: true, altKey: true });

beforeAll(() => registerPrograms());
beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal('innerWidth', 1920);
  vi.stubGlobal('innerHeight', 1080);
  signInAsDemo('admin');
  stubFetch({ '/api/approvals/count': { pending: 0 }, '/api/schedules': [] });
});
afterEach(() => {
  resetShellState();
  vi.unstubAllGlobals();
  useWindows.getState().reset();
  useShell.setState({ drawer: 'closed', palette: false, dialog: null });
  useSession.getState().logout();
});

test('the app drawer returns focus to its opener and keeps Tab inside', async () => {
  render(<Desktop />);
  dockButton('앱 목록').focus();
  await userEvent.keyboard('{Enter}');
  const drawer = screen.getByRole('dialog', { name: '앱 목록' });
  const search = within(drawer).getByRole('searchbox', { name: '프로그램 찾기' });
  expect(search).toHaveFocus();
  await userEvent.tab({ shift: true });
  expect(drawer.contains(document.activeElement)).toBe(true);
  within(drawer).getByRole('button', { name: '조건·규칙 열기' }).focus();
  await userEvent.tab();
  expect(search).toHaveFocus();
  await userEvent.keyboard('{Escape}');
  expect(dockButton('앱 목록')).toHaveFocus();
});

test('the search palette returns focus to the button that opened it', async () => {
  render(<Desktop />);
  await userEvent.click(screen.getByRole('button', { name: '검색 (Ctrl+K)' }));
  expect(screen.getByRole('combobox', { name: '검색어' })).toHaveFocus();
  await userEvent.keyboard('{Escape}');
  expect(screen.getByRole('button', { name: '검색 (Ctrl+K)' })).toHaveFocus();
});

test('an info dialog returns focus to the menu that opened it and keeps Tab inside', async () => {
  render(<Desktop />);
  await userEvent.click(screen.getByRole('button', { name: 'ChronOS 메뉴' }));
  await userEvent.click(screen.getByRole('menuitem', { name: 'ChronOS 정보' }));
  const dialog = screen.getByRole('dialog', { name: 'ChronOS 정보' });
  await userEvent.tab();
  await userEvent.tab();
  expect(dialog.contains(document.activeElement)).toBe(true);
  await userEvent.keyboard('{Escape}');
  expect(screen.getByRole('button', { name: 'ChronOS 메뉴' })).toHaveFocus();
});

test('/ opens the palette from the desktop but not from inside a window', () => {
  render(<Desktop />);
  act(() => void useWindows.getState().open('schedule'));
  const win = screen.getByRole('dialog', { name: '일정판' });
  fireEvent.keyDown(win, { key: '/', code: 'Slash' });
  expect(useShell.getState().palette).toBe(false);
  fireEvent.keyDown(document.body, { key: '/', code: 'Slash' });
  expect(useShell.getState().palette).toBe(true);
});

test('window shortcuts are ignored while the drawer, palette or a dialog is open', () => {
  render(<Desktop />);
  act(() => {
    useWindows.getState().open('schedule');
    useWindows.getState().open('chat');
  });
  const shown = () => useWindows.getState().wins.filter((w) => !w.minimized).length;
  for (const open of [
    () => useShell.getState().setDrawer('open'),
    () => useShell.getState().setPalette(true),
    () => useShell.getState().setDialog({ kind: 'about' }),
  ]) {
    act(open);
    ctrlAlt('KeyM');
    expect(shown()).toBe(2);
    act(() => useShell.setState({ drawer: 'closed', palette: false, dialog: null }));
  }
  ctrlAlt('KeyM');
  expect(shown()).toBe(0);
});

test('under StrictMode the drawer keeps focus on its search box (no refocus on the simulated unmount)', async () => {
  render(
    <StrictMode>
      <Desktop />
    </StrictMode>,
  );
  dockButton('앱 목록').focus();
  await userEvent.keyboard('{Enter}');
  expect(within(screen.getByRole('dialog', { name: '앱 목록' })).getByRole('searchbox', { name: '프로그램 찾기' })).toHaveFocus();
  await userEvent.keyboard('{Escape}');
  expect(dockButton('앱 목록')).toHaveFocus();
});

test('closing the panel while its button is hidden focuses the maximized window', () => {
  render(<Desktop />);
  act(() => void useWindows.getState().open('schedule'));
  act(() => useWindows.getState().toggleMaximize(useWindows.getState().wins[0].id));
  act(() => useContextPanel.getState().toggle());
  act(() => void useWindows.getState().open('chat'));
  act(() => useWindows.getState().close(useWindows.getState().wins.find((w) => w.programId === 'chat')!.id));
  // 포커스를 패널 안에 둔 채 닫는다(닫히면 그 자리가 사라진다).
  act(() => within(screen.getByRole('complementary', { name: 'Context 패널' })).getByRole('button', { name: 'Context 패널 닫기' }).focus());
  ctrlAlt('Period');
  expect(useContextPanel.getState().open).toBe(false);
  expect(screen.getByRole('dialog', { name: '일정판' })).toHaveFocus();
});
