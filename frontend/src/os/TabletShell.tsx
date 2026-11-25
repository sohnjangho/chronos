// 태블릿(iPad 등) 전용 워크스테이션 셸.
// 스마트폰의 하단 탭바 대신 왼쪽 76px 아이콘 레일 + 상단 명령 바 + 좌우 분할(Split View: 메인 화면 + 보조 AI·승인·현장 패널)을 제공한다.
import { Suspense, useEffect, useRef, useState, type Dispatch, type ReactNode, type SetStateAction } from 'react';
import { useAgentView } from './agentView';
import { useApprovalPolling, useApprovals } from './approvals';
import { ChronosMark, MoonIcon, PanelIcon, SunIcon } from './icons';
import { readTablet, tabletFor, tabletLayout, type TabletLayout } from './layoutMemory';
import { loadCached, useShellLayout } from './layoutSync';
import { useOutreachAlerts } from './outreachAlerts';
import ProgramIcon, { SystemIcon } from './ProgramIcon';
import { getProgram, programs, type ProgramManifest } from './registry';
import ScheduleSelector from './ScheduleSelector';
import { signOut } from './auth';
import { useSession, type Role } from './session';
import { defaultTabletRailIds, resolveTabletRail, tabletCatalog, useTabletRail } from './tabletRailStore';
import { useTheme } from './theme';
import ToastStack from './ToastStack';
import { useDeviceMode } from './useIsMobile';
import { useWindows } from './windowStore';
import WallpaperLayer from './WallpaperLayer';
import WorkflowRibbon from './WorkflowRibbon';
import './tablet.css';

function navForWindow(programId: string, params?: Record<string, string>): string {
  if (programId === 'progress' && params?.view === 'field') return 'field';
  return programId;
}

interface AppsGridItem {
  id: string;
  fullName: string;
  program: ProgramManifest;
  iconId?: 'field';
}

function appsGridItems(list: ProgramManifest[]): AppsGridItem[] {
  const out: AppsGridItem[] = [];
  for (const p of list) {
    out.push({ id: p.id, fullName: p.name, program: p });
    if (p.id === 'progress') {
      out.push({ id: 'field', fullName: '현장 모바일 점검', program: p, iconId: 'field' });
    }
  }
  return out;
}

function TabletAppsGrid({
  list,
  pinnedSet,
  railEdit,
  isDefault,
  onPick,
  onToggleEdit,
  onAddRail,
  onRemoveRail,
  onResetRail,
}: {
  list: ProgramManifest[];
  pinnedSet: Set<string>;
  railEdit: boolean;
  isDefault: boolean;
  onPick(id: string): void;
  onToggleEdit(): void;
  onAddRail(id: string): void;
  onRemoveRail(id: string): void;
  onResetRail(): void;
}) {
  const items = appsGridItems(list);
  return (
    <div className="tab-apps" aria-label="전체 프로그램">
      <div className="tab-apps-head">
        <div className="tab-apps-head-row">
          <h2>전체 프로그램</h2>
          <div className="tab-apps-actions">
            <button type="button" className="tab-apps-action" aria-pressed={railEdit} onClick={onToggleEdit}>
              {railEdit ? '편집 완료' : '메뉴 편집'}
            </button>
            {railEdit && (
              <button type="button" className="tab-apps-action" disabled={isDefault} onClick={onResetRail}>
                기본 메뉴 복원
              </button>
            )}
          </div>
        </div>
        <span className="tab-muted">
          {railEdit
            ? '왼쪽 메뉴에 넣을 앱을 고르거나, 왼쪽 막대를 끌어·↑↓ 버튼으로 순서를 바꾸세요.'
            : '원하는 프로그램을 선택해 태블릿 스테이지에서 바로 여세요.'}
        </span>
      </div>
      <div className="tab-apps-grid">
        {items.map((item) => {
          const inRail = pinnedSet.has(item.id);
          return (
            <div key={item.id} className="tab-app-card">
              <button type="button" className="tab-app-tile" onClick={() => onPick(item.id)}>
                <ProgramIcon program={item.program} size={52} iconId={item.iconId} />
                <span className="tab-app-name">{item.fullName}</span>
              </button>
              {railEdit && item.id !== 'settings' && (
                <button
                  type="button"
                  className={inRail ? 'tab-app-pin is-pinned' : 'tab-app-pin'}
                  aria-pressed={inRail}
                  aria-label={inRail ? `${item.fullName} 메뉴에서 빼기` : `${item.fullName} 메뉴에 추가`}
                  onClick={() => (inRail ? onRemoveRail(item.id) : onAddRail(item.id))}
                >
                  {inRail ? '메뉴에서 빼기' : '+ 메뉴에 추가'}
                </button>
              )}
            </div>
          );
        })}
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

function TabletWorkflowBadge() {
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
        className="tab-cu-btn is-active"
        aria-label="Computer-Use 상태"
        data-tip="워크플로우 진행 리본 열기·접기"
        onClick={toggleRibbon}
      >
        <span className="tab-cu-dot" aria-hidden="true" />
        <span className="tab-cu-tag">Computer-Use</span>
        <span className="tab-cu-step">{`${step}/${total} · ${summary}`}</span>
      </button>
    );
  }

  if (ribbon.status === 'waiting' && ribbon.steps.length > 0) {
    const rid = ribbon.runId ?? lastRunId;
    const waitLabel = ribbon.waitReason === 'approval' ? '승인 대기 중' : '답변 대기 중';
    return (
      <button
        type="button"
        className="tab-cu-btn is-waiting"
        aria-label={`워크플로우${rid ? ` #${rid}` : ''} ${waitLabel}`}
        onClick={toggleRibbon}
      >
        <span className="tab-cu-wait-dot" aria-hidden="true" />
        <span>{`${rid ? `워크플로우 #${rid}` : '워크플로우'} · ${waitLabel} ▾`}</span>
      </button>
    );
  }

  if (ribbon.collapsed && ribbon.steps.length > 0 && lastRunId !== null) {
    return (
      <button
        type="button"
        className="tab-cu-btn is-done"
        aria-label={`워크플로우 #${lastRunId} 완료`}
        onClick={toggleRibbon}
      >
        <span>{`워크플로우 #${lastRunId} 완료 ▾`}</span>
      </button>
    );
  }

  return null;
}

/** 위 명령 바: 이름 · 일정 고르기 · 좌우 분할 · 화면 형태 · 테마 · 나가기. */
function TabletHeader({
  title,
  isFieldRole,
  splitOpen,
  onToggleSplit,
}: {
  title: string;
  isFieldRole: boolean;
  splitOpen: boolean;
  onToggleSplit(): void;
}) {
  const theme = useTheme((s) => s.theme);
  const toggleTheme = useTheme((s) => s.toggle);
  return (
    <header className="tab-head">
      <div className="tab-head-left">
        <ChronosMark size={24} />
        <span className="tab-title">{title}</span>
        <span className="tab-pill">{isFieldRole ? '태블릿 · 현장 전용' : '태블릿'}</span>
      </div>
      <div className="tab-head-right">
        <TabletWorkflowBadge />
        <ScheduleSelector />
        <button
          type="button"
          className="tab-split-btn"
          aria-pressed={splitOpen}
          title="오른쪽 AI 대화 패널 열기·접기"
          onClick={onToggleSplit}
        >
          <PanelIcon />
          <span>좌우 분할</span>
        </button>
        <TabletDeviceSwitch />
        <button type="button" className="tab-icon-btn" aria-label={theme === 'dark' ? '밝은 테마' : '어두운 테마'} onClick={toggleTheme}>
          {theme === 'dark' ? <SunIcon /> : <MoonIcon />}
        </button>
        <button type="button" className="tab-text-btn" onClick={signOut}>
          나가기
        </button>
      </div>
    </header>
  );
}

type RailItem = ReturnType<typeof resolveTabletRail>[number];

/** 메뉴 편집 중 끌어서 옮기는 상태(끄는 줄 · 놓을 줄). */
interface RailDrag {
  dragId: string | null;
  overId: string | null;
  setDragId(id: string | null): void;
  setOverId(id: string | null): void;
}

/** 레일 아래: 메뉴 편집 · 전체 앱(현장 관리자 없음) · 설정. 편집을 켜면 전체 앱 격자도 연다. */
function RailFoot({
  railEdit,
  setRailEdit,
  showApps,
  setShowApps,
  isFieldRole,
  activeId,
  settingsManifest,
  onPick,
}: {
  railEdit: boolean;
  setRailEdit: Dispatch<SetStateAction<boolean>>;
  showApps: boolean;
  setShowApps: Dispatch<SetStateAction<boolean>>;
  isFieldRole: boolean;
  activeId: string;
  settingsManifest: ProgramManifest | undefined;
  onPick(id: string): void;
}) {
  return (
    <div className="tab-rail-foot">
      <button
        type="button"
        className={railEdit ? 'tab-rail-btn is-editing-on' : 'tab-rail-btn'}
        aria-pressed={railEdit}
        onClick={() =>
          setRailEdit((prev) => {
            const next = !prev;
            if (next && !isFieldRole) setShowApps(true);
            return next;
          })
        }
      >
        <span className="tab-rail-label">{railEdit ? '편집 완료' : '메뉴 편집'}</span>
      </button>
      {!isFieldRole && (
        <button
          type="button"
          className="tab-rail-btn"
          aria-current={showApps ? 'page' : undefined}
          onClick={() => setShowApps((s) => !s)}
        >
          <span className="tab-rail-ico-wrap">
            <SystemIcon id="apps" size={32} />
          </span>
          <span className="tab-rail-label">전체 앱</span>
        </button>
      )}
      {settingsManifest && (
        <button
          type="button"
          className="tab-rail-btn"
          aria-current={!showApps && activeId === 'settings' ? 'page' : undefined}
          onClick={() => onPick('settings')}
        >
          <span className="tab-rail-ico-wrap">
            <ProgramIcon program={settingsManifest} size={32} />
          </span>
          <span className="tab-rail-label">설정</span>
        </button>
      )}
    </div>
  );
}

/** 왼쪽 레일: 프로그램 단추들(편집 중이면 끌기 · ↑↓× 줄) + 아래 메뉴 편집 · 전체 앱 · 설정. */
function TabletRail({
  railList,
  activeId,
  showApps,
  railEdit,
  setRailEdit,
  setShowApps,
  isFieldRole,
  defaults,
  pending,
  settingsManifest,
  onPick,
}: {
  railList: RailItem[];
  activeId: string;
  showApps: boolean;
  railEdit: boolean;
  setRailEdit: Dispatch<SetStateAction<boolean>>;
  setShowApps: Dispatch<SetStateAction<boolean>>;
  isFieldRole: boolean;
  defaults: string[];
  pending: number;
  settingsManifest: ProgramManifest | undefined;
  onPick(id: string): void;
}) {
  const [dragId, setDragId] = useState<string | null>(null);
  const [overId, setOverId] = useState<string | null>(null);
  const drag: RailDrag = { dragId, overId, setDragId, setOverId };
  return (
    <nav className={railEdit ? 'tab-rail is-editing' : 'tab-rail'} aria-label="태블릿 탐색">
      <div className="tab-rail-scroll">
        {railList.map((item, idx) => {
          const m = getProgram(item.programId);
          if (!m) return null;
          const isCurrent = !showApps && activeId === item.id;
          if (railEdit) {
            return (
              <RailEditItem
                key={item.id}
                item={item}
                program={m}
                idx={idx}
                last={idx === railList.length - 1}
                isFieldRole={isFieldRole}
                defaults={defaults}
                drag={drag}
              />
            );
          }
          return (
            <button
              key={item.id}
              type="button"
              className="tab-rail-btn"
              aria-current={isCurrent ? 'page' : undefined}
              onClick={() => onPick(item.id)}
            >
              <span className="tab-rail-ico-wrap">
                <ProgramIcon program={m} size={32} iconId={item.iconId} />
                {item.id === 'approvals' && pending > 0 && (
                  <span className="tab-rail-badge">{pending > 99 ? '99+' : pending}</span>
                )}
              </span>
              <span className="tab-rail-label">{item.label}</span>
            </button>
          );
        })}
      </div>
      <RailFoot
        railEdit={railEdit}
        setRailEdit={setRailEdit}
        showApps={showApps}
        setShowApps={setShowApps}
        isFieldRole={isFieldRole}
        activeId={activeId}
        settingsManifest={settingsManifest}
        onPick={onPick}
      />
    </nav>
  );
}

/** 메뉴 편집 중 레일 한 줄: 끌어서 옮기기 · ↑ · ↓ · ×(현장 관리자는 빼기 없음). */
function RailEditItem({
  item,
  program,
  idx,
  last,
  isFieldRole,
  defaults,
  drag,
}: {
  item: RailItem;
  program: ProgramManifest;
  idx: number;
  last: boolean;
  isFieldRole: boolean;
  defaults: string[];
  drag: RailDrag;
}) {
  const { dragId, overId, setDragId, setOverId } = drag;
  const itemCls = [
    'tab-rail-edit-item',
    dragId === item.id ? 'is-dragging' : '',
    overId === item.id && dragId !== null && dragId !== item.id ? 'is-drop-target' : '',
  ]
    .filter(Boolean)
    .join(' ');
  return (
    <div
      className={itemCls}
      data-rail-id={item.id}
      draggable
      onDragStart={(e) => {
        setDragId(item.id);
        e.dataTransfer?.setData('text/plain', item.id);
        if (e.dataTransfer) e.dataTransfer.effectAllowed = 'move';
      }}
      onDragOver={(e) => {
        e.preventDefault();
        if (e.dataTransfer) e.dataTransfer.dropEffect = 'move';
        if (overId !== item.id) setOverId(item.id);
      }}
      onDragLeave={() => {
        if (overId === item.id) setOverId(null);
      }}
      onDrop={(e) => {
        e.preventDefault();
        const from = dragId || e.dataTransfer?.getData('text/plain') || null;
        if (from && from !== item.id) useTabletRail.getState().move(from, idx, defaults);
        setDragId(null);
        setOverId(null);
      }}
      onDragEnd={() => {
        setDragId(null);
        setOverId(null);
      }}
    >
      <span className="tab-rail-ico-wrap">
        <ProgramIcon program={program} size={28} iconId={item.iconId} />
      </span>
      <span className="tab-rail-label">{item.label}</span>
      <div className="tab-rail-edit-ctrls">
        <button
          type="button"
          className="tab-rail-mini"
          aria-label={`${item.label} 위로 이동`}
          disabled={idx === 0}
          onClick={() => useTabletRail.getState().moveBy(item.id, -1, defaults)}
        >
          ↑
        </button>
        <button
          type="button"
          className="tab-rail-mini"
          aria-label={`${item.label} 아래로 이동`}
          disabled={last}
          onClick={() => useTabletRail.getState().moveBy(item.id, 1, defaults)}
        >
          ↓
        </button>
        {!isFieldRole && (
          <button
            type="button"
            className="tab-rail-mini is-del"
            aria-label={`${item.label} 메뉴에서 제거`}
            onClick={() => useTabletRail.getState().remove(item.id, defaults)}
          >
            ×
          </button>
        )}
      </div>
    </div>
  );
}

/** 오른쪽 보조 분할 화면(AI 대화). */
function ChatSidePanel({ Screen, onCollapse }: { Screen: ProgramManifest['component']; onCollapse(): void }) {
  return (
    <aside className="tab-side" aria-label="보조 분할 화면">
      <div className="tab-side-bar">
        <span className="tab-side-title">AI 대화</span>
        <button
          type="button"
          className="tab-side-collapse"
          aria-label="오른쪽 보조 패널 접기"
          onClick={onCollapse}
        >
          접기 ▸
        </button>
      </div>
      <div className="tab-side-body">
        <Suspense fallback={<p className="tab-loading">불러오는 중…</p>}>
          <Screen windowId="tablet-side" />
        </Suspense>
      </div>
    </aside>
  );
}

/** 공정률 화면은 「현장 점검」이면 field, 「공정률」이면 dashboard 보기로 연다. */
function primaryParamsFor(activeId: string, params: Record<string, string> | undefined) {
  return activeId === 'field'
    ? { ...(params ?? {}), view: 'field' }
    : activeId === 'progress'
      ? { ...(params ?? {}), view: 'dashboard' }
      : params;
}

/** 프로그램 내부에서 open(...) 또는 Computer Use stageFocus(...) 가 호출되면 태블릿 스테이지도 따라간다. */
function useFollowTopWindow(follow: (top: { programId: string; params?: Record<string, string> }) => void) {
  const wins = useWindows((s) => s.wins);
  const lastTopRef = useRef<string | null>(null);
  useEffect(() => {
    if (wins.length === 0) return;
    const top = wins.reduce((a, b) => (b.z > a.z ? b : a));
    const sig = `${top.id}:${top.z}:${JSON.stringify(top.params ?? {})}`;
    if (sig === lastTopRef.current) return;
    lastTopRef.current = sig;
    follow(top);
  }, [wins]);
}

/** 이 등급이 쓸 수 있는 프로그램과 레일(저장된 차례 · 기본값 · 넣을 수 있는 것 · 지금 들어 있는 것). */
function useRailModel(role: Role) {
  const allowed = programs(role);
  const savedRail = useTabletRail((s) => s.items);
  const defaults = defaultTabletRailIds(role);
  const railList = resolveTabletRail(role, allowed, savedRail);
  const catalogSet = new Set(tabletCatalog(role, allowed).map((e) => e.id));
  const pinnedSet = new Set(railList.map((r) => r.id));
  return { allowed, savedRail, defaults, railList, catalogSet, pinnedSet };
}

/** 본문 위 「Computer Use」 띠: 에이전트가 지금 이 화면에서 하는 일. */
function AgentBar({ label }: { label: string }) {
  return (
    <div className="os-win-agent-bar" role="status" aria-label="에이전트 실시간 작업">
      <span className="os-win-agent-pulse" aria-hidden="true" />
      <b className="os-win-agent-tag">Computer Use</b>
      <span className="os-win-agent-label">{label}</span>
    </div>
  );
}

/** 본문: 전체 앱 격자(apps 가 있으면) 또는 고른 프로그램 화면. */
function PrimaryBody({
  apps,
  Screen,
  params,
}: {
  apps: ReactNode;
  Screen: ProgramManifest['component'] | undefined;
  params: Record<string, string> | undefined;
}) {
  return (
    <div className="tab-primary-body">
      {apps ? (
        apps
      ) : Screen ? (
        <Suspense fallback={<p className="tab-loading">불러오는 중…</p>}>
          <Screen windowId="tablet-main" params={params} />
        </Suspense>
      ) : (
        <p className="tab-loading">이 프로그램을 열 수 없습니다.</p>
      )}
    </div>
  );
}

/** 보조 패널을 접었을 때 오른쪽 끝의 펼치기 손잡이. */
function ExpandSideButton({ onExpand }: { onExpand(): void }) {
  return (
    <button
      type="button"
      className="tab-side-expand"
      aria-label="오른쪽 보조 패널 펼치기"
      title="AI 대화 보조 패널 펼치기"
      onClick={onExpand}
    >
      <span aria-hidden="true">◂</span>
      <span className="tab-side-expand-txt">AI 대화</span>
    </button>
  );
}

export default function TabletShell() {
  useApprovalPolling();
  useOutreachAlerts(); // 긴급 보고 토스트 — 바탕화면과 같게(현장 관리자는 묻지 않음)
  const role = useSession((s) => s.session?.user.role ?? 'user');
  const isFieldRole = role === 'field';
  const pending = useApprovals((s) => s.pending);
  const agentFocus = useAgentView((s) => s.focus);

  const userId = useSession((s) => s.session?.user.id ?? null);
  // 다시 열면 그대로: 이 계정이 태블릿에서 마지막에 연 프로그램(서버 것이 더 새것이면 곧 바뀐다).
  const [boot] = useState(() => readTablet(loadCached('tablet', userId)?.state, role));
  const [activeId, setActiveId] = useState<string>(() => boot?.active ?? (role === 'field' ? 'field' : 'schedule-table'));
  const [showApps, setShowApps] = useState(false);
  const [railEdit, setRailEdit] = useState(false);
  const [params, setParams] = useState<Record<string, string> | undefined>(boot?.params);
  const [splitOpen, setSplitOpen] = useState<boolean>(() => (typeof window !== 'undefined' ? window.innerWidth >= 960 : true));
  const showLayout = (l: TabletLayout) => {
    setShowApps(false);
    setActiveId(l.active);
    setParams(l.params);
  };
  useShellLayout('tablet', tabletLayout(activeId, params), {
    apply: (raw) => {
      const l = readTablet(raw, role);
      if (l) showLayout(l);
      return l;
    },
    openFocus: (f) => {
      const l = tabletFor(f, role);
      if (l) showLayout(l);
    },
  });

  useFollowTopWindow((top) => {
    setShowApps(false);
    setActiveId(navForWindow(top.programId, top.params));
    setParams(top.params);
  });

  const primaryProgramId = activeId === 'field' ? 'progress' : activeId;
  const primaryManifest = !showApps ? getProgram(primaryProgramId) : undefined;
  const PrimaryScreen = primaryManifest?.component;

  const primaryParams = primaryParamsFor(activeId, params);
  const title = showApps ? '전체 프로그램' : activeId === 'field' ? '현장 모바일 점검' : (primaryManifest?.name ?? 'ChronOS');

  const ChatSideScreen = getProgram('chat')?.component;
  const showSidePanel = splitOpen && ChatSideScreen && primaryProgramId !== 'chat';
  const showExpandTab = !splitOpen && ChatSideScreen && primaryProgramId !== 'chat';

  const showAgentBanner = agentFocus.active && !showApps && agentFocus.programId === primaryProgramId;

  function pickRail(id: string) {
    setShowApps(false);
    setActiveId(id);
    setParams(undefined);
  }

  function pickApp(id: string) {
    setShowApps(false);
    setRailEdit(false);
    setActiveId(id);
    setParams(undefined);
  }

  const { allowed, savedRail, defaults, railList, catalogSet, pinnedSet } = useRailModel(role);
  const settingsManifest = getProgram('settings');

  return (
    <div className="tab-root" data-testid="tablet-shell" data-device="tablet">
      <WallpaperLayer />
      <TabletHeader title={title} isFieldRole={isFieldRole} splitOpen={splitOpen} onToggleSplit={() => setSplitOpen((v) => !v)} />

      <WorkflowRibbon />

      <div className="tab-body">
        <TabletRail
          railList={railList} activeId={activeId} showApps={showApps}
          railEdit={railEdit} setRailEdit={setRailEdit} setShowApps={setShowApps}
          isFieldRole={isFieldRole} defaults={defaults} pending={pending}
          settingsManifest={settingsManifest} onPick={pickRail}
        />

        <div className="tab-stage">
          <main className="tab-primary">
            {showAgentBanner && <AgentBar label={agentFocus.label} />}
            <PrimaryBody
              apps={
                showApps ? (
                  <TabletAppsGrid
                    list={allowed}
                    pinnedSet={pinnedSet}
                    railEdit={railEdit}
                    isDefault={savedRail === null}
                    onPick={pickApp}
                    onToggleEdit={() => setRailEdit((v) => !v)}
                    onAddRail={(id) => catalogSet.has(id) && useTabletRail.getState().add(id, defaults)}
                    onRemoveRail={(id) => useTabletRail.getState().remove(id, defaults)}
                    onResetRail={() => useTabletRail.getState().resetDefault()}
                  />
                ) : null
              }
              Screen={PrimaryScreen}
              params={primaryParams}
            />
          </main>

          {showSidePanel && <ChatSidePanel Screen={ChatSideScreen} onCollapse={() => setSplitOpen(false)} />}
          {showExpandTab && <ExpandSideButton onExpand={() => setSplitOpen(true)} />}
        </div>
      </div>
      <ToastStack />
    </div>
  );
}
