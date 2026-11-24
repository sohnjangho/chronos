// 연락처 — 태블릿·스마트폰 화면(Task 105). 폰: 목록 → 대화 한 화면씩(위 「‹ 이름」 으로 돌아감, 탭 「문자 · 카카오톡 | 통화 n」).
// 태블릿: PC 와 같은 두 칸, 세로로 세우면 사람을 고른 뒤 주소록이 접힌다(머리 띠의 [주소록]으로 펼침). PC 창: 폭 720 아래면 한 화면씩.
// 입력창이 화면 아래에 붙는지는 칸 구조와 CSS 약속으로 보고, 실제 자리(390×844)는 e2e/contacts-mobile.spec.ts 가 잰다.
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { useCurrentSchedule } from '../../os/currentSchedule';
import { useDeviceMode } from '../../os/useIsMobile';
import { useUiContext } from '../../os/uiContext';
import { useWindows } from '../../os/windowStore';
import Contacts from './Contacts';
import css from './contacts.css?raw';
import { stubContacts } from './testKit';
import { contactsLayout } from './useNarrow';

function viewport(w: number, h: number) {
  vi.stubGlobal('innerWidth', w);
  vi.stubGlobal('innerHeight', h);
}

beforeEach(() => {
  localStorage.clear();
  stubContacts();
  useWindows.setState({ open: vi.fn(), setTitle: vi.fn() } as never);
  useCurrentSchedule.setState({ current: { id: 1, name: '5층 사무동 신축' } });
});
afterEach(() => {
  cleanup();
  useCurrentSchedule.setState({ current: null });
  useUiContext.getState().reset();
  useDeviceMode.getState().setMode('auto');
  localStorage.clear();
  vi.unstubAllGlobals();
});

const show = (params: Record<string, string> = {}) => render(<Contacts windowId="mobile" params={params} />);
const book = () => screen.queryByRole('navigation', { name: '주소록' });
const pick = async (name: RegExp) => userEvent.click(within(book()!).getByRole('button', { name }));

test('layout rule: phone → one screen, tablet → two panes (portrait folds the book), PC window → one screen at 720 and below', () => {
  expect(contactsLayout('phone', null, true)).toBe('single');
  expect(contactsLayout('phone', 1400, false)).toBe('single');
  expect(contactsLayout('tablet', 700, false)).toBe('two');
  expect(contactsLayout('tablet', 700, true)).toBe('folded');
  expect(contactsLayout('desktop', null, false)).toBe('two'); // 아직 재지 못함(시험 환경) — PC 와 같게
  expect(contactsLayout('desktop', 721, false)).toBe('two');
  expect(contactsLayout('desktop', 720, false)).toBe('single');
});

describe('phone 390×844', () => {
  beforeEach(() => viewport(390, 844));

  test('the list comes first; picking a person shows only the conversation with 「‹ 이름」 and the two tabs; back returns to the list', async () => {
    const { container } = show();
    expect(await screen.findByRole('button', { name: /박현장/ })).toBeVisible();
    expect(container.querySelector('.ct-root')).toHaveClass('is-single');
    expect(screen.queryByRole('region', { name: '연락처 자세히' })).toBeNull(); // 오른쪽 칸은 숨음

    await pick(/박현장/);
    expect(book()).toBeNull(); // 주소록은 숨음(지우지 않음 — 찾기 글이 남게)
    const pane = screen.getByRole('region', { name: '박현장 대화' });
    const back = within(pane).getByRole('button', { name: '박현장 — 주소록으로 돌아가기' });
    expect(back).toHaveTextContent('‹ 박현장');
    const tabs = within(pane).getByRole('tablist', { name: '대화 종류' });
    expect(within(tabs).getAllByRole('tab').map((t) => t.textContent)).toEqual(['문자 · 카카오톡', '통화 0']);
    expect(within(pane).queryByRole('button', { name: '‹ 목록' })).toBeNull();

    await userEvent.click(back);
    expect(book()).toBeVisible();
    expect(screen.queryByRole('region', { name: '박현장 대화' })).toBeNull();
  });

  test('the address-book search survives going into a conversation and back', async () => {
    show();
    await screen.findByRole('button', { name: /박현장/ });
    await userEvent.type(within(book()!).getByRole('searchbox'), '박');
    await pick(/박현장/);
    await userEvent.click(screen.getByRole('button', { name: '박현장 — 주소록으로 돌아가기' }));
    expect(within(book()!).getByRole('searchbox')).toHaveValue('박');
  });

  test('a form (사람 추가) also takes the whole screen and 「‹ 목록」 returns', async () => {
    show();
    await screen.findByRole('button', { name: /박현장/ });
    await userEvent.click(within(book()!).getAllByRole('button', { name: /사람 추가/ })[0]);
    expect(book()).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: '‹ 목록' }));
    expect(book()).toBeVisible();
  });

  test('params.contact opens straight into that conversation', async () => {
    show({ contact: '3' });
    expect(await screen.findByRole('button', { name: '이전기 — 주소록으로 돌아가기' })).toBeVisible();
    expect(book()).toBeNull();
  });

  test('the composer is the last block of the conversation, outside the scrolling log, so it sits at the bottom (390px)', async () => {
    show();
    await screen.findByRole('button', { name: /박현장/ });
    await pick(/박현장/);
    const pane = screen.getByRole('region', { name: '박현장 대화' });
    const composer = await waitFor(() => {
      const el = pane.querySelector<HTMLElement>('[data-slot="composer"]');
      expect(el).not.toBeNull();
      return el!;
    });
    expect(composer.parentElement!.lastElementChild).toBe(composer);
    expect(within(pane).getByRole('log').contains(composer)).toBe(false);
    // 칸 약속: 오른쪽 칸 = 세로 flex, 대화 자리는 남은 높이를 채우고(min-height 0) 밀리지 않는다.
    expect(css).toMatch(/\.ct-pane\s*\{[^}]*display:\s*flex;[^}]*flex-direction:\s*column/);
    expect(css).toMatch(/\.ct-slot\s*\{[^}]*flex:\s*1;[^}]*min-height:\s*0/);
    expect(css).toMatch(/\.ct-root\.is-single \.ct-head-acts\s*\{[^}]*width:\s*100%/);
    // 숨긴 칸은 display 가 덮어쓰지 않게
    expect(css).toMatch(/\.ct-pane\[hidden\][^{]*\{[^}]*display:\s*none/);
    expect(css).toMatch(/\.ct-book-slot\[hidden\][^{]*\{[^}]*display:\s*none/);
  });

  test('call cards put the summary first on a narrow screen (right after the who/status line)', () => {
    expect(css).toMatch(/\.ct-root\.is-single \.cl-card > \.cl-text\s*\{[^}]*order:\s*-1/);
    expect(css).toMatch(/\.ct-root\.is-single \.cl-card > \.th-meta:first-child\s*\{[^}]*order:\s*-2/);
    expect(css).toMatch(/\.ct-root\.is-single \.cl-card > \.th-meta:first-child \+ \.cl-text\s*\{[^}]*order:\s*0/);
  });
});

describe('tablet', () => {
  beforeEach(() => useDeviceMode.getState().setMode('tablet'));

  test('landscape 1180×820: the same two panes as the PC, no back button', async () => {
    viewport(1180, 820);
    const { container } = show();
    await screen.findByRole('button', { name: /박현장/ });
    await pick(/박현장/);
    expect(book()).toBeVisible();
    expect(screen.getByRole('region', { name: '박현장 대화' })).toBeVisible();
    expect(screen.queryByRole('button', { name: /주소록으로 돌아가기/ })).toBeNull();
    expect(screen.queryByRole('button', { name: '주소록' })).toBeNull();
    expect(container.querySelector('.ct-root')).toHaveClass('is-two');
  });

  test('portrait 820×1180: after picking, the book folds; [주소록] in the strip unfolds it, picking folds it again', async () => {
    viewport(820, 1180);
    show();
    await screen.findByRole('button', { name: /박현장/ });
    expect(screen.queryByRole('button', { name: '주소록' })).toBeNull(); // 아무도 고르지 않았으면 주소록이 보인다
    await pick(/박현장/);
    expect(book()).toBeNull();
    expect(screen.getByRole('region', { name: '박현장 대화' })).toBeVisible();
    const toggle = screen.getByRole('button', { name: '주소록' });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');

    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(book()).toBeVisible();
    expect(screen.getByRole('region', { name: '박현장 대화' })).toBeVisible(); // 두 칸

    await pick(/이전기/);
    expect(book()).toBeNull();
    expect(screen.getByRole('region', { name: '이전기 대화' })).toBeVisible();
  });

  test('turning the tablet upright folds the book without a reload', async () => {
    viewport(1180, 820);
    show();
    await screen.findByRole('button', { name: /박현장/ });
    await pick(/박현장/);
    expect(book()).toBeVisible();
    act(() => {
      viewport(820, 1180);
      window.dispatchEvent(new Event('resize'));
    });
    expect(book()).toBeNull();
    expect(screen.getByRole('button', { name: '주소록' })).toBeVisible();
  });
});

describe('PC window narrower than 720', () => {
  test('a narrow desktop window shows one screen at a time too', async () => {
    let fire: ((w: number) => void) | null = null;
    vi.stubGlobal(
      'ResizeObserver',
      class {
        constructor(cb: (entries: { contentRect: { width: number } }[]) => void) {
          fire = (w) => cb([{ contentRect: { width: w } }]);
        }
        observe() {}
        disconnect() {}
      },
    );
    viewport(1920, 1080);
    const { container } = show();
    await screen.findByRole('button', { name: /박현장/ });
    expect(container.querySelector('.ct-root')).toHaveClass('is-two');
    act(() => fire!(600));
    expect(container.querySelector('.ct-root')).toHaveClass('is-single');
    await pick(/박현장/);
    expect(book()).toBeNull();
    act(() => fire!(1100));
    expect(book()).toBeVisible();
  });
});
