// 태블릿(iPad 등) 전용 워크스테이션 셸.
// 스마트폰의 하단 탭바 대신 왼쪽 76px 아이콘 레일 + 상단 명령 바 + 좌우 분할(Split View: 메인 화면 + 보조 AI·승인·현장 패널)을 제공한다.
import { Suspense, useEffect, useRef, useState, type CSSProperties } from 'react';
import { useAgentView } from './agentView';
import { useApprovalPolling, useApprovals } from './approvals';
import { AppsIcon, ChronosMark, MoonIcon, PanelIcon, SunIcon } from './icons';
import ProgramIcon from './ProgramIcon';
import { getProgram, programs, type ProgramManifest } from './registry';
import ScheduleSelector from './ScheduleSelector';
import { useSession } from './session';
import { useTheme } from './theme';
import { useDeviceMode } from './useIsMobile';
import { useWindows } from './windowStore';
import './tablet.css';

type NavId =
  | 'chat'
  | 'schedule-table'
  | 'gantt'
  | 'progress'
  | 'field'
  | 'cpm'
  | 'delays'
  | 'workflow'
  | 'approvals'
  | 'library'
  | 'settings';

type SideId = 'chat' | 'approvals' | 'field';

interface RailSpec {
  id: NavId;
  label: string;
  programId: string;
}

const RAIL_MAIN: RailSpec[] = [
  { id: 'chat', label: '대화', programId: 'chat' },
  { id: 'schedule-table', label: '스케줄', programId: 'schedule-table' },
  { id: 'gantt', label: '간트', programId: 'gantt' },
  { id: 'progress', label: '공정률', programId: 'progress' },
  { id: 'field', label: '현장 점검', programId: 'progress' },
  { id: 'cpm', label: 'CPM', programId: 'cpm' },
  { id: 'delays', label: '지연', programId: 'delays' },
  { id: 'workflow', label: '워크플로우', programId: 'workflow' },
  { id: 'approvals', label: '승인함', programId: 'approvals' },
  { id: 'library', label: '자료함', programId: 'library' },
];

const SIDE_TABS: { id: SideId; label: string; programId: string; params?: Record<string, string> }[] = [
  { id: 'chat', label: 'AI 대화', programId: 'chat' },
  { id: 'approvals', label: '승인함', programId: 'approvals' },
  { id: 'field', label: '현장 점검', programId: 'progress', params: { view: 'field' } },
];

const ALL_RAIL_MAP = new Map<string, NavId>([
  ...RAIL_MAIN.filter((r) => r.id !== 'field').map((r) => [r.programId, r.id] as [string, NavId]),
  ['settings', 'settings'],
]);

function navForWindow(programId: string, params?: Record<string, string>): NavId | null {
  if (programId === 'progress' && params?.view === 'field') return 'field';
  return ALL_RAIL_MAP.get(programId) ?? null;
}

function TabletAppsGrid({ list, onPick }: { list: ProgramManifest[]; onPick(id: string): void }) {
  return (
    <div className="tab-apps" aria-label="전체 프로그램">
      <div className="tab-apps-head">
        <h2>전체 프로그램</h2>
        <span className="tab-muted">원하는 프로그램을 선택해 태블릿 스테이지에서 바로 여세요.</span>
      </div>
      <div className="tab-apps-grid">
        {list.map((p) => (
          <button key={p.id} type="button" className="tab-app-tile" onClick={() => onPick(p.id)}>
            <ProgramIcon program={p} size={52} />
            <span className="tab-app-name">{p.name}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

function TabletDeviceSwitch() {
  const mode = useDeviceMode((s) => s.mode);
  const setMode = useDeviceMode((s) => s.setMode);
  return (
    <div className="tab-dev-switch" role="group" aria-label="화면 형태">
      <button type="button" className="tab-dev-btn" aria-pressed={mode === 'auto'} title="자동 감지: 태블릿" onClick={() => setMode('auto')}>
        자동
      </button>
      <button type="button" className="tab-dev-btn" aria-pressed={mode === 'phone'} onClick={() => setMode('phone')}>
        폰
      </button>
      <button type="button" className="tab-dev-btn" aria-pressed={mode === 'tablet'} onClick={() => setMode('tablet')}>
        태블릿
      </button>
      <button type="button" className="tab-dev-btn" aria-pressed={false} onClick={() => setMode('desktop')}>
        PC 창
      </button>
    </div>
  );
}

export default function TabletShell() {
  useApprovalPolling();
  const role = useSession((s) => s.session?.user.role ?? 'user');
  const logout = useSession((s) => s.logout);
  const theme = useTheme((s) => s.theme);
  const toggleTheme = useTheme((s) => s.toggle);
  const pending = useApprovals((s) => s.pending);
  const wins = useWindows((s) => s.wins);
  const agentFocus = useAgentView((s) => s.focus);

  const [navId, setNavId] = useState<NavId>('schedule-table');
  const [customProgram, setCustomProgram] = useState<string | null>(null);
  const [showApps, setShowApps] = useState(false);
  const [params, setParams] = useState<Record<string, string> | undefined>(undefined);
  const [splitOpen, setSplitOpen] = useState<boolean>(() => (typeof window !== 'undefined' ? window.innerWidth >= 960 : true));
  const [sideTab, setSideTab] = useState<SideId>('chat');
  const lastTopRef = useRef<string | null>(null);

  // 프로그램 내부에서 open(...) 또는 Computer Use stageFocus(...) 가 호출되면 태블릿 스테이지도 따라간다.
  useEffect(() => {
    if (wins.length === 0) return;
    const top = wins.reduce((a, b) => (b.z > a.z ? b : a));
    const sig = `${top.id}:${top.z}:${JSON.stringify(top.params ?? {})}`;
    if (sig === lastTopRef.current) return;
    lastTopRef.current = sig;
    const mapped = navForWindow(top.programId, top.params);
    setShowApps(false);
    if (mapped) {
      setNavId(mapped);
      setCustomProgram(null);
    } else {
      setCustomProgram(top.programId);
    }
    setParams(top.params);
  }, [wins]);

  const primaryProgramId =
    customProgram ??
    (navId === 'field' ? 'progress' : navId);
  const primaryManifest = !showApps ? getProgram(primaryProgramId) : undefined;
  const PrimaryScreen = primaryManifest?.component;

  const primaryParams =
    navId === 'field' && !customProgram
      ? { ...(params ?? {}), view: 'field' }
      : navId === 'progress' && !customProgram
        ? { ...(params ?? {}), view: 'dashboard' }
        : params;

  const title = showApps
    ? '전체 프로그램'
    : navId === 'field' && !customProgram
      ? '현장 모바일 점검'
      : (primaryManifest?.name ?? 'ChronOS');

  // 보조 분할 창이 주 화면과 같은 프로그램이 되지 않도록 자동 보정한다.
  const effectiveSide: SideId =
    sideTab === 'chat' && primaryProgramId === 'chat'
      ? 'approvals'
      : sideTab === 'approvals' && primaryProgramId === 'approvals'
        ? 'chat'
        : sideTab === 'field' && navId === 'field' && !customProgram
          ? 'chat'
          : sideTab;
  const sideSpec = SIDE_TABS.find((t) => t.id === effectiveSide) ?? SIDE_TABS[0];
  const SideScreen = getProgram(sideSpec.programId)?.component;

  const showAgentBanner = agentFocus.active && !showApps && agentFocus.programId === primaryProgramId;

  function pickRail(id: NavId) {
    setShowApps(false);
    setCustomProgram(null);
    setNavId(id);
    setParams(undefined);
  }

  function pickApp(id: string) {
    setShowApps(false);
    const mapped = navForWindow(id);
    if (mapped) {
      setNavId(mapped);
      setCustomProgram(null);
    } else {
      setCustomProgram(id);
    }
    setParams(undefined);
  }

  const settingsManifest = getProgram('settings');

  return (
    <div className="tab-root" data-testid="tablet-shell" data-device="tablet">
      <header className="tab-head">
        <div className="tab-head-left">
          <ChronosMark size={24} />
          <span className="tab-title">{title}</span>
          <span className="tab-pill">태블릿</span>
        </div>
        <div className="tab-head-right">
          <ScheduleSelector />
          <button
            type="button"
            className="tab-split-btn"
            aria-pressed={splitOpen}
            title="좌우 분할 화면 전환"
            onClick={() => setSplitOpen((v) => !v)}
          >
            <PanelIcon />
            <span>좌우 분할</span>
          </button>
          <TabletDeviceSwitch />
          <button type="button" className="tab-icon-btn" aria-label={theme === 'dark' ? '밝은 테마' : '어두운 테마'} onClick={toggleTheme}>
            {theme === 'dark' ? <SunIcon /> : <MoonIcon />}
          </button>
          <button type="button" className="tab-text-btn" onClick={logout}>
            나가기
          </button>
        </div>
      </header>

      <div className="tab-body">
        <nav className="tab-rail" aria-label="태블릿 탐색">
          <div className="tab-rail-scroll">
            {RAIL_MAIN.map((item) => {
              const m = getProgram(item.programId);
              if (!m) return null;
              const isCurrent = !showApps && !customProgram && navId === item.id;
              return (
                <button
                  key={item.id}
                  type="button"
                  className="tab-rail-btn"
                  aria-current={isCurrent ? 'page' : undefined}
                  onClick={() => pickRail(item.id)}
                >
                  <span className="tab-rail-ico-wrap">
                    <ProgramIcon program={m} size={32} />
                    {item.id === 'approvals' && pending > 0 && (
                      <span className="tab-rail-badge">{pending > 99 ? '99+' : pending}</span>
                    )}
                  </span>
                  <span className="tab-rail-label">{item.label}</span>
                </button>
              );
            })}
          </div>
          <div className="tab-rail-foot">
            <button
              type="button"
              className="tab-rail-btn"
              aria-current={showApps ? 'page' : undefined}
              onClick={() => setShowApps((s) => !s)}
            >
              <span className="tab-rail-ico-wrap">
                <span className="os-icon os-tone-slate" style={{ '--icon-size': '32px' } as CSSProperties} aria-hidden="true">
                  <AppsIcon size={18} />
                </span>
              </span>
              <span className="tab-rail-label">전체 앱</span>
            </button>
            {settingsManifest && (
              <button
                type="button"
                className="tab-rail-btn"
                aria-current={!showApps && !customProgram && navId === 'settings' ? 'page' : undefined}
                onClick={() => pickRail('settings')}
              >
                <span className="tab-rail-ico-wrap">
                  <ProgramIcon program={settingsManifest} size={32} />
                </span>
                <span className="tab-rail-label">설정</span>
              </button>
            )}
          </div>
        </nav>

        <div className="tab-stage">
          <main className="tab-primary">
            {showAgentBanner && (
              <div className="os-win-agent-bar" role="status" aria-label="에이전트 실시간 작업">
                <span className="os-win-agent-pulse" aria-hidden="true" />
                <b className="os-win-agent-tag">Computer Use</b>
                <span className="os-win-agent-label">{agentFocus.label}</span>
              </div>
            )}
            <div className="tab-primary-body">
              {showApps ? (
                <TabletAppsGrid list={programs(role)} onPick={pickApp} />
              ) : PrimaryScreen ? (
                <Suspense fallback={<p className="tab-loading">불러오는 중…</p>}>
                  <PrimaryScreen windowId="tablet-main" params={primaryParams} />
                </Suspense>
              ) : (
                <p className="tab-loading">이 프로그램을 열 수 없습니다.</p>
              )}
            </div>
          </main>

          {splitOpen && SideScreen && (
            <aside className="tab-side" aria-label="보조 분할 화면">
              <div className="tab-side-bar">
                <div className="tab-side-tabs" role="tablist" aria-label="보조 화면 선택">
                  {SIDE_TABS.map((t) => (
                    <button
                      key={t.id}
                      type="button"
                      role="tab"
                      aria-selected={effectiveSide === t.id}
                      className={`tab-side-tab${effectiveSide === t.id ? ' is-on' : ''}`}
                      onClick={() => setSideTab(t.id)}
                    >
                      {t.label}
                    </button>
                  ))}
                </div>
                <button type="button" className="tab-side-close" aria-label="분할 화면 닫기" onClick={() => setSplitOpen(false)}>
                  ×
                </button>
              </div>
              <div className="tab-side-body">
                <Suspense fallback={<p className="tab-loading">불러오는 중…</p>}>
                  <SideScreen windowId="tablet-side" params={sideSpec.params} />
                </Suspense>
              </div>
            </aside>
          )}
        </div>
      </div>
    </div>
  );
}
