import { beforeEach, expect, test, vi } from 'vitest';
import { register } from '../../os/registry';
import { useWindows } from '../../os/windowStore';
import manifest from './index';

beforeEach(() => {
  vi.stubGlobal('innerWidth', 1920);
  vi.stubGlobal('innerHeight', 1080);
  useWindows.getState().reset();
  register(manifest);
});

test('the chat program opens small (480×760)', () => {
  expect(manifest.defaultSize).toEqual({ w: 480, h: 760 });
  const id = useWindows.getState().open('chat');
  expect(useWindows.getState().wins.find((w) => w.id === id)).toMatchObject({ w: 480, h: 760 });
});

test('보기 switches between the small (480×760) and the large (1560×900) layout, also from a maximized window', () => {
  const id = useWindows.getState().open('chat');
  const items = manifest.menus!.find((m) => m.label === '보기')!.items;
  const pick = (label: string) => items.find((i) => i.label === label)!.action(id);
  const win = () => useWindows.getState().wins.find((w) => w.id === id)!;
  pick('큰 화면');
  expect(win()).toMatchObject({ w: 1560, h: 900, maximized: false });
  useWindows.getState().toggleMaximize(id);
  pick('작은 화면');
  expect(win()).toMatchObject({ w: 480, h: 760, maximized: false });
});

test('the 대화 menu starts a new conversation and says that answers keep running when the window closes', async () => {
  const menu = manifest.menus!.find((m) => m.label === '대화')!;
  const help = menu.items.find((i) => i.label.includes('창을 닫아도'))!;
  expect(help.disabled).toBe(true);
  const id = useWindows.getState().open('chat');
  const { useChat } = await import('./chatStore');
  useChat.setState({ currentId: 4 });
  await menu.items.find((i) => i.label === '새 대화')!.action(id);
  await vi.waitFor(() => expect(useChat.getState().currentId).toBeNull());
});
