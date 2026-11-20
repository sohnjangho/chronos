import Badge from '../shared/ui/Badge';
import { useApprovals } from './approvals';
import Clock from './Clock';
import MenuButton from './MenuButton';
import { getProgram } from './registry';
import ScheduleSelector from './ScheduleSelector';
import { useSession } from './session';
import { topWindow, useWindows } from './windowStore';

const ROLE_NAMES = { admin: '관리자', user: '사용자' } as const;

/** ChronOS 메뉴: 정보·설정·잠금·로그아웃. */
function SystemMenu({ onAbout }: { onAbout(): void }) {
  const open = useWindows((s) => s.open);
  const items = [
    { label: '정보', run: onAbout },
    { label: '설정', run: () => open('settings') },
    { label: '잠금', run: () => useSession.getState().lock() },
    { label: '로그아웃', run: () => useSession.getState().logout() },
  ];
  return (
    <MenuButton label="ChronOS" ariaLabel="ChronOS 메뉴" className="os-mb-brand">
      {(close) =>
        items.map((item) => (
          <button
            key={item.label}
            type="button"
            role="menuitem"
            className="os-menu-item"
            onClick={() => {
              close();
              item.run();
            }}
          >
            {item.label}
          </button>
        ))
      }
    </MenuButton>
  );
}

/** 맨 앞 프로그램의 이름과 메뉴. */
function ActiveProgram() {
  const active = useWindows((s) => topWindow(s.wins));
  if (!active) return null;
  const menus = getProgram(active.programId)?.menus ?? [];
  return (
    <>
      <span className="os-mb-app">{active.title}</span>
      {menus.map((m) => (
        <button key={m.label} type="button" className="os-mb-btn" onClick={() => m.action(active.id)}>
          {m.label}
        </button>
      ))}
    </>
  );
}

export default function MenuBar({ onAbout }: { onAbout(): void }) {
  const user = useSession((s) => s.session?.user);
  const open = useWindows((s) => s.open);
  const pending = useApprovals((s) => s.pending);
  return (
    <header className="os-menubar">
      <SystemMenu onAbout={onAbout} />
      <ActiveProgram />
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
