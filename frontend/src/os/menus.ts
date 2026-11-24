// 메뉴바 메뉴 만들기: 로고 · 앱 이름 · 프로그램 메뉴(+ 보기 배율) · 윈도우 · 도움말 · 사용자.
import { signOut } from './auth';
import { arrangeWindows, closeAllWindows, minimizeAllWindows } from './commands';
import { AppsIcon } from './icons';
import { SEPARATOR, type MenuAction, type MenuEntry, type MenuSpec } from './MenuGroup';
import type { ProgramManifest, ProgramMenuItem } from './registry';
import { useSession, type User } from './session';
import { useShell } from './shell';
import { activeWindow, useWindows, type Win } from './windowStore';
import { useZoom, ZOOM_STEPS, zoomOf } from './zoom';

const noop = () => {};
const windows = () => useWindows.getState();
const shell = () => useShell.getState();
export const ROLE_NAMES = { admin: '관리자', user: '사용자', field: '현장 관리자' } as const;

export function logoMenu(): MenuSpec {
  return {
    key: 'logo',
    label: null,
    ariaLabel: 'ChronOS 메뉴',
    className: 'os-mb-logo',
    items: [
      { label: 'ChronOS 정보', run: () => shell().setDialog({ kind: 'about' }) },
      { label: '설정…', run: () => windows().open('settings') },
      { label: '앱 목록', icon: AppsIcon({ size: 16 }), run: () => shell().setDrawer('open') },
      SEPARATOR,
      { label: '화면 잠금', run: () => useSession.getState().lock() },
      { label: '로그아웃', run: signOut },
    ],
  };
}

/** 굵은 앱 이름 메뉴. 활성 창이 없으면 제품 이름. */
export function appNameMenu(active: Win | null, program: ProgramManifest | undefined): MenuSpec {
  const name = active ? (program?.name ?? active.programId) : 'ChronOS';
  return {
    key: 'app',
    label: name,
    className: 'os-mb-app',
    items: [
      {
        label: `${name} 정보`,
        run: () => shell().setDialog(active ? { kind: 'program', programId: active.programId } : { kind: 'about' }),
      },
      SEPARATOR,
      { label: '설정…', run: () => windows().open('settings') },
      SEPARATOR,
      { label: '숨기기', disabled: !active, run: () => active && windows().minimize(active.id) },
      { label: '닫기', disabled: !active, run: () => active && windows().close(active.id) },
    ],
  };
}

function zoomItems(programId: string, level: number): MenuEntry[] {
  const z = useZoom.getState();
  return [
    { label: `배율 ${level}%`, disabled: true, run: noop },
    SEPARATOR,
    { label: '확대', shortcut: 'Ctrl+Alt+=', disabled: level >= ZOOM_STEPS[ZOOM_STEPS.length - 1], run: () => z.zoomIn(programId) },
    { label: '축소', shortcut: 'Ctrl+Alt+-', disabled: level <= ZOOM_STEPS[0], run: () => z.zoomOut(programId) },
    { label: '실제 크기 100%', shortcut: 'Ctrl+Alt+0', run: () => z.reset(programId) },
  ];
}

/** 프로그램 메뉴 항목을 셸 메뉴 줄로. group 이 바뀌면 구분선 + 묶음 제목, separatorBefore 면 구분선. */
function fromProgram(items: ProgramMenuItem[], windowId: string): MenuEntry[] {
  const out: MenuEntry[] = [];
  let group: string | undefined;
  for (const it of items) {
    if (it.group !== group) {
      if (out.length) out.push(SEPARATOR);
      if (it.group) out.push({ type: 'title', label: it.group });
      group = it.group;
    } else if (it.separatorBefore && out.length) out.push(SEPARATOR);
    const { label, shortcut, disabled, checked } = it;
    out.push({ label, shortcut, disabled, checked, run: () => it.action(windowId) });
  }
  return out;
}

/** 활성 프로그램의 메뉴. 「보기」가 있으면 그 끝에, 없으면 새 「보기」에 배율 항목을 붙인다. */
export function programMenus(active: Win, program: ProgramManifest | undefined, levels: Record<string, number>): MenuSpec[] {
  const zoom = zoomItems(active.programId, zoomOf(levels, active.programId));
  const menus = (program?.menus ?? []).map((m) => ({
    key: `menu-${m.label}`,
    label: m.label,
    items: fromProgram(m.items, active.id),
  }));
  const view = menus.find((m) => m.label === '보기');
  if (view) view.items = [...view.items, SEPARATOR, ...zoom];
  else menus.push({ key: 'menu-보기', label: '보기', items: zoom });
  return menus;
}

export function windowMenu(state: { wins: Win[]; deactivated: boolean }): MenuSpec {
  const w = windows();
  const active = activeWindow(state);
  const shown = state.wins.filter((x) => !x.minimized);
  const list: MenuEntry[] = state.wins.map((x) => ({
    label: x.minimized ? `${x.title} (최소화)` : x.title,
    current: x === active,
    run: () => w.focus(x.id),
  }));
  const items: MenuEntry[] = [
    { label: '최소화', disabled: !active, run: () => active && w.minimize(active.id) },
    { label: '확대/축소', disabled: !active, run: () => active && w.toggleMaximize(active.id) },
    SEPARATOR,
    { label: '좌우 분할', shortcut: 'Ctrl+Alt+S', disabled: !shown.length, run: () => arrangeWindows('split') },
    { label: '격자 정렬', shortcut: 'Ctrl+Alt+G', disabled: !shown.length, run: () => arrangeWindows('grid') },
    { label: '계단식 정렬', shortcut: 'Ctrl+Alt+C', disabled: !shown.length, run: () => arrangeWindows('cascade') },
    SEPARATOR,
    { label: '모두 최소화', shortcut: 'Ctrl+Alt+M', disabled: !shown.length, run: minimizeAllWindows },
    { label: '모두 닫기', shortcut: 'Ctrl+Alt+Q', disabled: !state.wins.length, run: closeAllWindows },
    { label: '창 닫기', shortcut: 'Ctrl+Alt+W', disabled: !active, run: () => w.closeActive() },
    SEPARATOR,
    { label: '다음 창', shortcut: 'Ctrl+`', disabled: shown.length < 2, run: () => w.nextWindow() },
    ...(list.length ? [SEPARATOR, ...list] : []),
  ];
  return { key: 'window', label: '윈도우', items };
}

export function helpMenu(): MenuSpec {
  return {
    key: 'help',
    label: '도움말',
    items: [
      { label: '키보드 단축키', run: () => shell().setDialog({ kind: 'shortcuts' }) },
      { label: 'ChronOS 정보', run: () => shell().setDialog({ kind: 'about' }) },
    ],
  };
}

/** 사용자 메뉴: 이름(둘째 줄 아이디) ─ 등급 ─ 설정…·로그아웃. 단추 오른쪽 끝에 맞춰 연다. */
export function userMenuItems(user: User, loginId: string): MenuEntry[] {
  const info: MenuAction = { label: user.name, detail: loginId, disabled: true, run: noop };
  return [
    info,
    SEPARATOR,
    { type: 'title', label: '등급' },
    { label: ROLE_NAMES[user.role], disabled: true, run: noop },
    SEPARATOR,
    { label: '설정…', run: () => windows().open('settings') },
    { label: '로그아웃', run: signOut },
  ];
}
