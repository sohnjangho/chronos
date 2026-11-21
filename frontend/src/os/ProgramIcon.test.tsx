import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeAll, expect, test, vi } from 'vitest';
import { registerPrograms } from '../programs';
import { signInAsDemo, stubFetch } from '../test-helpers';
import { setCustomIconOverrides } from './customIcons';
import { ChronosMark } from './icons';
import MobileShell from './MobileShell';
import ProgramIcon, { SystemIcon } from './ProgramIcon';
import { getProgram } from './registry';
import { useSession } from './session';
import { resetShellState } from './shellReset';

beforeAll(() => registerPrograms());

afterEach(() => {
  cleanup();
  setCustomIconOverrides({});
  resetShellState();
  vi.unstubAllGlobals();
  useSession.getState().logout();
});

test('renders built-in SVG vector tile with data-icon-id when no custom file exists', () => {
  const chat = getProgram('chat')!;
  const { container } = render(
    <div>
      <ProgramIcon program={chat} size={48} />
      <SystemIcon id="apps" size={48} />
      <ChronosMark size={24} />
    </div>,
  );
  const chatTile = container.querySelector('[data-icon-id="chat"]')!;
  const appsTile = container.querySelector('[data-icon-id="apps"]')!;
  const chronosTile = container.querySelector('[data-icon-id="chronos"]')!;
  expect(chatTile.querySelector('svg')).not.toBeNull();
  expect(appsTile.querySelector('svg')).not.toBeNull();
  expect(chronosTile.querySelector('svg')).not.toBeNull();
});

test('uses custom image icon identically everywhere when overridden and falls back to SVG on image error', () => {
  setCustomIconOverrides({
    chat: '/custom/chat.png',
    apps: '/custom/apps.png',
    chronos: '/custom/chronos.png',
  });
  const chat = getProgram('chat')!;
  const { container } = render(
    <div>
      <ProgramIcon program={chat} size={48} />
      <SystemIcon id="apps" size={32} />
      <ChronosMark size={24} />
    </div>,
  );

  const chatImg = container.querySelector('[data-icon-id="chat"] img.os-icon-img') as HTMLImageElement;
  const appsImg = container.querySelector('[data-icon-id="apps"] img.os-icon-img') as HTMLImageElement;
  const chronosImg = container.querySelector('[data-icon-id="chronos"] img.os-icon-img') as HTMLImageElement;

  expect(chatImg.getAttribute('src')).toBe('/custom/chat.png');
  expect(appsImg.getAttribute('src')).toBe('/custom/apps.png');
  expect(chronosImg.getAttribute('src')).toBe('/custom/chronos.png');

  fireEvent.error(chatImg);
  expect(container.querySelector('[data-icon-id="chat"] img')).toBeNull();
  expect(container.querySelector('[data-icon-id="chat"] svg')).not.toBeNull();
});

test('MobileShell replaces raw emojis with unified cross-device icons matching Desktop and Tablet', async () => {
  vi.stubGlobal('innerWidth', 390);
  vi.stubGlobal('innerHeight', 844);
  setCustomIconOverrides({
    chat: '/custom/chat.png',
    'schedule-table': '/custom/schedule-table.png',
    approvals: '/custom/approvals.png',
    library: '/custom/library.png',
    apps: '/custom/apps.png',
  });
  signInAsDemo('user', '김현장', 'field-user', 2);
  stubFetch({
    '/api/approvals/count': { pending: 2 },
    '/api/schedules': [],
    '/api/chat/sessions': [],
  });

  render(<MobileShell />);
  const nav = screen.getByRole('navigation', { name: '모바일 탐색' });

  expect(nav.textContent).not.toMatch(/💬|📅|📁|☰/);
  for (const id of ['chat', 'schedule-table', 'approvals', 'library', 'apps']) {
    const img = nav.querySelector(`[data-icon-id="${id}"] img.os-icon-img`) as HTMLImageElement | null;
    expect(img, `bottom tab icon ${id}`).not.toBeNull();
    expect(img!.getAttribute('src')).toBe(`/custom/${id}.png`);
  }

  await userEvent.click(within(nav).getByRole('button', { name: /전체/ }));
  const more = screen.getByLabelText('전체 프로그램');
  const moreChatImg = more.querySelector('[data-icon-id="chat"] img.os-icon-img') as HTMLImageElement | null;
  expect(moreChatImg?.getAttribute('src')).toBe('/custom/chat.png');
});
