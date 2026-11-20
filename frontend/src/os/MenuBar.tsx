import Badge from '../shared/ui/Badge';
import { useApprovals } from './approvals';
import Clock from './Clock';
import MenuGroup, { type MenuSpec } from './MenuGroup';
import { getProgram } from './registry';
import ScheduleSelector from './ScheduleSelector';
import { useSession } from './session';
import { topWindow, useWindows } from './windowStore';

const ROLE_NAMES = { admin: '관리자', user: '사용자' } as const;

/** ChronOS 메뉴(정보·설정·잠금·로그아웃) 뒤에 맨 앞 프로그램의 이름과 펼침 메뉴. */
function AppMenus({ onAbout }: { onAbout(): void }) {
  const active = useWindows((s) => topWindow(s.wins));
  const open = useWindows((s) => s.open);
  const program = active ? getProgram(active.programId) : undefined;
  const system: MenuSpec = {
    key: 'chronos',
    label: 'ChronOS',
    ariaLabel: 'ChronOS 메뉴',
    className: 'os-mb-brand',
    items: [
      { label: '정보', run: onAbout },
      { label: '설정', run: () => open('settings') },
      { label: '잠금', run: () => useSession.getState().lock() },
      { label: '로그아웃', run: () => useSession.getState().logout() },
    ],
    after: active && <span className="os-mb-app">{program?.name ?? active.programId}</span>,
  };
  const programMenus: MenuSpec[] = (active && program?.menus ? program.menus : []).map((menu) => ({
    key: `menu-${menu.label}`,
    label: menu.label,
    items: menu.items.map((item) => ({
      label: item.label,
      shortcut: item.shortcut,
      disabled: item.disabled,
      run: () => active && item.action(active.id),
    })),
  }));
  return <MenuGroup menus={[system, ...programMenus]} />;
}

export default function MenuBar({ onAbout }: { onAbout(): void }) {
  const user = useSession((s) => s.session?.user);
  const open = useWindows((s) => s.open);
  const pending = useApprovals((s) => s.pending);
  return (
    <header className="os-menubar">
      <AppMenus onAbout={onAbout} />
      <div className="os-mb-gap" />
      <ScheduleSelector />
      <button type="button" className="os-mb-btn" onClick={() => open('approvals')}>
        승인
        {pending > 0 && (
          <>
            {' '}
            <Badge tone="danger" solid>
              {pending}
            </Badge>
          </>
        )}
      </button>
      {/* 알림 배지는 묶음 3에서 연결한다(지금은 0 이라 숨김). */}
      <span className="os-mb-item">알림</span>
      {user && (
        <span className="os-mb-item">
          {user.name} · {ROLE_NAMES[user.role]}
        </span>
      )}
      <Clock />
    </header>
  );
}
