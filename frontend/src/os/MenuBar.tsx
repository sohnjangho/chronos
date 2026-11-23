import { useAgentView } from './agentView';
import { useApprovals } from './approvals';
import Clock from './Clock';
import { BellIcon, ChronosMark, InboxIcon, MobileFieldIcon, MoonIcon, PersonIcon, SearchIcon, SunIcon } from './icons';
import MenuGroup from './MenuGroup';
import { appNameMenu, helpMenu, logoMenu, programMenus, ROLE_NAMES, userMenuItems, windowMenu } from './menus';
import { getProgram } from './registry';
import ScheduleSelector from './ScheduleSelector';
import { useSession } from './session';
import { useShell } from './shell';
import { useTheme } from './theme';
import { useDeviceMode } from './useIsMobile';
import { activeWindow, useWindows } from './windowStore';
import { useZoom } from './zoom';
import './menubar.css';

/** 앱 이름 · 활성 프로그램 메뉴(+ 보기) · 윈도우 · 도움말. ←→ 로 돌고, 열린 동안 가리키면 바뀐다. */
function AppMenus() {
  const wins = useWindows((s) => s.wins);
  const deactivated = useWindows((s) => s.deactivated);
  const levels = useZoom((s) => s.levels);
  const active = activeWindow({ wins, deactivated });
  const program = active ? getProgram(active.programId) : undefined;
  const menus = [
    appNameMenu(active, program),
    ...(active ? programMenus(active, program, levels) : []),
    windowMenu({ wins, deactivated }),
    helpMenu(),
  ];
  return <MenuGroup menus={menus} className="os-mb-apps" />;
}

const badgeText = (n: number) => (n > 99 ? '99+' : String(n));

/** 검색 · 승인함 · 알림 · 테마: 32×32 아이콘 단추. 승인함·알림은 오른쪽 위 빨간 배지. */
function TopButtons() {
  const pending = useApprovals((s) => s.pending);
  const open = useWindows((s) => s.open);
  const theme = useTheme((s) => s.theme);
  const notices = 0; // 알림은 묶음 3에서 연결한다.
  return (
    <>
      <button
        type="button"
        className="os-tb"
        aria-label="모바일·태블릿 현장 뷰"
        data-tip="모바일·태블릿 현장 뷰"
        onClick={() => {
          open('progress', { view: 'field' });
          useDeviceMode.getState().setMode('tablet');
        }}
      >
        <MobileFieldIcon />
      </button>
      <button type="button" className="os-tb" aria-label="검색 (Ctrl+K)" data-tip="검색 (Ctrl+K)" onClick={() => useShell.getState().setPalette(true)}>
        <SearchIcon />
      </button>
      <button
        type="button"
        className="os-tb"
        aria-label={`승인함 — 대기 ${pending}건`}
        data-tip={`승인 대기 ${pending}건`}
        onClick={() => open('approvals')}
      >
        <InboxIcon />
        {pending > 0 && <span className="os-tb-badge is-strong">{badgeText(pending)}</span>}
      </button>
      <button type="button" className="os-tb" aria-label={`알림 ${notices}건`} data-tip={`알림 ${notices}건`}>
        <BellIcon />
        {notices > 0 && <span className="os-tb-badge">{badgeText(notices)}</span>}
      </button>
      <button
        type="button"
        className="os-tb"
        aria-label={theme === 'dark' ? '밝은 테마로' : '어두운 테마로'}
        data-tip={theme === 'dark' ? '밝은 테마로' : '어두운 테마로'}
        onClick={() => useTheme.getState().toggle()}
      >
        {theme === 'dark' ? <SunIcon /> : <MoonIcon />}
      </button>
    </>
  );
}

function UserMenu() {
  const session = useSession((s) => s.session);
  if (!session) return null;
  const { user, loginId } = session;
  const name = `${user.name} ${ROLE_NAMES[user.role]}`;
  const label = (
    <>
      <PersonIcon />
      <span className="os-user-name">{user.name}</span>
      <span className="os-user-role">{ROLE_NAMES[user.role]}</span>
      <span className="os-user-caret" aria-hidden="true">
        ▾
      </span>
    </>
  );
  return <MenuGroup menus={[{ key: 'user', label, ariaLabel: name, className: 'os-user', alignRight: true, items: userMenuItems(user, loginId) }]} />;
}

function ComputerUseBadge() {
  const focus = useAgentView((s) => s.focus);
  const ribbon = useAgentView((s) => s.ribbon);
  const lastRunId = useAgentView((s) => s.lastRunId);
  const toggleRibbon = useAgentView((s) => s.toggleRibbon);

  if (focus.active || ribbon.status === 'running') {
    const total = Math.max(1, focus.stepN, focus.totalSteps, ribbon.steps.length);
    const step = Math.max(1, focus.stepN || ribbon.steps.length);
    const summary = focus.label || ribbon.steps[ribbon.steps.length - 1]?.label || '실행 중';
    return (
      <button
        type="button"
        className="os-menubar-cu is-active"
        aria-label="Computer-Use 상태"
        data-tip="워크플로우 진행 리본 열기·접기"
        onClick={toggleRibbon}
      >
        <span className="os-menubar-cu-dot" aria-hidden="true" />
        <span className="os-menubar-cu-tag">Computer-Use</span>
        <span className="os-menubar-cu-step">{`${step}/${total} · ${summary}`}</span>
      </button>
    );
  }

  if (ribbon.status === 'waiting' && ribbon.steps.length > 0) {
    const rid = ribbon.runId ?? lastRunId;
    const waitLabel = ribbon.waitReason === 'approval' ? '승인 대기 중' : '답변 대기 중';
    return (
      <button
        type="button"
        className="os-menubar-cu is-waiting"
        aria-label={`워크플로우${rid ? ` #${rid}` : ''} ${waitLabel}`}
        data-tip="워크플로우 진행 리본 열기·접기"
        onClick={toggleRibbon}
      >
        <span className="os-menubar-cu-wait-dot" aria-hidden="true" />
        <span>{`${rid ? `워크플로우 #${rid}` : '워크플로우'} · ${waitLabel} ▾`}</span>
      </button>
    );
  }

  if (ribbon.collapsed && ribbon.steps.length > 0 && lastRunId !== null) {
    const failed = ribbon.status === 'failed';
    const endLabel = failed ? '실패' : ribbon.status === 'stopped' ? '멈춤' : '완료';
    return (
      <button
        type="button"
        className="os-menubar-cu is-done"
        aria-label={`워크플로우 #${lastRunId} ${endLabel}`}
        data-tip={`${failed ? '실패한' : ribbon.status === 'stopped' ? '멈춘' : '완료된'} 워크플로우 다시 펼치기`}
        onClick={toggleRibbon}
      >
        {failed && <span className="os-menubar-cu-wait-dot" style={{ background: 'var(--danger)' }} aria-hidden="true" />}
        <span>{`워크플로우 #${lastRunId} ${endLabel} ▾`}</span>
      </button>
    );
  }

  return null;
}

/** 메뉴바(48px): 왼쪽 로고 · 앱 메뉴들, 오른쪽 Computer-Use · 현장 선택 · 아이콘 단추 · 사용자 · 시계. */
export default function MenuBar() {
  return (
    <header className="os-menubar">
      <div className="os-mb-left">
        <MenuGroup menus={[{ ...logoMenu(), label: <ChronosMark size={24} /> }]} />
        <AppMenus />
      </div>
      <div className="os-mb-right">
        <ComputerUseBadge />
        <ScheduleSelector />
        <TopButtons />
        <UserMenu />
        <Clock />
      </div>
    </header>
  );
}
