// 스마트폰(<= 768px) · 태블릿(>= 600px 또는 수동 전환) 전용 앱 셸.
// OS 다중 창·Dock 대신 상단 헤더(화면 형태 전환 포함) + 풀스크린 본문 + 하단 5개 탭바로 구성하며
// 「일정」 탭 안의 「현장 점검」에서 일일 체크인·사진 AI 판독·만회안 의견·D-3 핸드오프를 바로 수행한다.
import { Suspense, useEffect, useRef, useState } from 'react';
import { useApprovalPolling, useApprovals } from './approvals';
import { ChronosMark, MoonIcon, SunIcon } from './icons';
import { getProgram, programs, type ProgramManifest } from './registry';
import ScheduleSelector from './ScheduleSelector';
import { useSession } from './session';
import { useTheme } from './theme';
import { useDeviceMode, useResolvedDevice } from './useIsMobile';
import { useWindows } from './windowStore';
import './mobile.css';

type TabId = 'chat' | 'schedule' | 'approvals' | 'library' | 'more';

const SCHEDULE_SUBS = [
  { id: 'schedule-table', label: '스케줄' },
  { id: 'gantt', label: '간트' },
  { id: 'progress', label: '공정률' },
  { id: 'delays', label: '지연' },
  { id: 'field', label: '현장 점검' },
] as const;

const SCHEDULE_IDS = new Set<string>(['schedule-table', 'gantt', 'progress', 'delays']);

function tabForProgram(programId: string): TabId {
  if (programId === 'chat') return 'chat';
  if (programId === 'approvals') return 'approvals';
  if (programId === 'library') return 'library';
  if (SCHEDULE_IDS.has(programId)) return 'schedule';
  return 'more';
}

function MoreGrid({ list, onPick }: { list: ProgramManifest[]; onPick(id: string): void }) {
  return (
    <div className="mob-more" aria-label="전체 프로그램">
      <h2 className="mob-more-title">전체 프로그램</h2>
      <div className="mob-more-grid">
        {list.map((p) => (
          <button key={p.id} type="button" className="mob-more-btn" onClick={() => onPick(p.id)}>
            <span className={`os-icon os-tone-${p.tone ?? 'slate'}`} style={{ '--icon-size': '44px' } as React.CSSProperties} aria-hidden="true">
              {p.icon}
            </span>
            <span className="mob-more-name">{p.name}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

function DeviceSwitch({ device }: { device: 'phone' | 'tablet' }) {
  const mode = useDeviceMode((s) => s.mode);
  const setMode = useDeviceMode((s) => s.setMode);
  return (
    <div className="mob-dev-switch" role="group" aria-label="화면 형태">
      <button type="button" className="mob-dev-btn" aria-pressed={mode === 'phone' || (mode === 'auto' && device === 'phone')} onClick={() => setMode('phone')}>
        폰
      </button>
      <button type="button" className="mob-dev-btn" aria-pressed={mode === 'tablet' || (mode === 'auto' && device === 'tablet')} onClick={() => setMode('tablet')}>
        태블릿
      </button>
      <button type="button" className="mob-dev-btn" aria-pressed={false} onClick={() => setMode('desktop')}>
        PC 창
      </button>
    </div>
  );
}

function MobileHeader({
  title,
  device,
  showBack,
  onBack,
}: {
  title: string;
  device: 'phone' | 'tablet';
  showBack: boolean;
  onBack(): void;
}) {
  const theme = useTheme((s) => s.theme);
  const toggleTheme = useTheme((s) => s.toggle);
  const logout = useSession((s) => s.logout);

  return (
    <header className="mob-head">
      <div className="mob-head-left">
        {showBack ? (
          <button type="button" className="mob-icon-btn" aria-label="목록으로" onClick={onBack}>
            ←
          </button>
        ) : (
          <span className="mob-brand" aria-hidden="true">
            <ChronosMark />
          </span>
        )}
        <span className="mob-title">{title}</span>
      </div>
      <div className="mob-head-right">
        <ScheduleSelector />
        <DeviceSwitch device={device} />
        <button type="button" className="mob-icon-btn" aria-label={theme === 'dark' ? '밝은 테마' : '어두운 테마'} onClick={toggleTheme}>
          {theme === 'dark' ? <SunIcon /> : <MoonIcon />}
        </button>
        <button type="button" className="mob-text-btn" onClick={logout}>
          나가기
        </button>
      </div>
    </header>
  );
}

function MobileTabBar({
  tab,
  pending,
  onSelect,
}: {
  tab: TabId;
  pending: number;
  onSelect(next: TabId): void;
}) {
  const items: { id: TabId; label: string; icon: string; badge?: number }[] = [
    { id: 'chat', label: '대화', icon: '💬' },
    { id: 'schedule', label: '일정·현장', icon: '📅' },
    { id: 'approvals', label: '승인', icon: '✓', badge: pending },
    { id: 'library', label: '자료함', icon: '📁' },
    { id: 'more', label: '전체', icon: '☰' },
  ];
  return (
    <nav className="mob-nav" aria-label="모바일 탐색">
      {items.map((it) => (
        <button
          key={it.id}
          type="button"
          className={`mob-tab${tab === it.id ? ' is-active' : ''}`}
          aria-current={tab === it.id ? 'page' : undefined}
          onClick={() => onSelect(it.id)}
        >
          <span className="mob-tab-icon" aria-hidden="true">
            {it.icon}
            {it.badge && it.badge > 0 ? <span className="mob-badge">{it.badge > 99 ? '99+' : it.badge}</span> : null}
          </span>
          <span className="mob-tab-label">{it.label}</span>
        </button>
      ))}
    </nav>
  );
}

export default function MobileShell() {
  useApprovalPolling();
  const role = useSession((s) => s.session?.user.role ?? 'user');
  const pending = useApprovals((s) => s.pending);
  const wins = useWindows((s) => s.wins);
  const device = useResolvedDevice();

  const [tab, setTab] = useState<TabId>('chat');
  const [scheduleSub, setScheduleSub] = useState<string>('schedule-table');
  const [moreProgram, setMoreProgram] = useState<string | null>(null);
  const [params, setParams] = useState<Record<string, string> | undefined>(undefined);
  const lastTopRef = useRef<string | null>(null);

  // 프로그램 내부에서 useWindows.open(id, params) 호출 시 모바일/태블릿 화면도 해당 프로그램으로 자동 전환.
  useEffect(() => {
    if (wins.length === 0) return;
    const top = wins.reduce((a, b) => (b.z > a.z ? b : a));
    const sig = `${top.id}:${top.z}:${JSON.stringify(top.params ?? {})}`;
    if (sig === lastTopRef.current) return;
    lastTopRef.current = sig;
    const nextTab = tabForProgram(top.programId);
    setTab(nextTab);
    if (nextTab === 'schedule') {
      if (top.programId === 'progress' && top.params?.view === 'field') setScheduleSub('field');
      else setScheduleSub(top.programId);
    }
    if (nextTab === 'more') setMoreProgram(top.programId);
    setParams(top.params);
  }, [wins]);

  const activeId =
    tab === 'chat'
      ? 'chat'
      : tab === 'approvals'
        ? 'approvals'
        : tab === 'library'
          ? 'library'
          : tab === 'schedule'
            ? scheduleSub === 'field'
              ? 'progress'
              : scheduleSub
            : moreProgram;

  const screenParams =
    tab === 'schedule' && scheduleSub === 'field'
      ? { ...(params ?? {}), view: 'field' }
      : tab === 'schedule' && scheduleSub === 'progress'
        ? { ...(params ?? {}), view: 'dashboard' }
        : params;

  const manifest = activeId ? getProgram(activeId) : undefined;
  const Screen = manifest?.component;
  const title =
    tab === 'more' && !moreProgram
      ? '전체'
      : tab === 'schedule' && scheduleSub === 'field'
        ? '현장 모바일 점검'
        : (manifest?.name ?? 'ChronOS');

  function selectTab(next: TabId) {
    setTab(next);
    if (next === 'more') setMoreProgram(null);
    setParams(undefined);
  }

  return (
    <div className="mob-root" data-testid="mobile-shell" data-device={device}>
      <MobileHeader
        title={title}
        device={device}
        showBack={tab === 'more' && moreProgram !== null}
        onBack={() => setMoreProgram(null)}
      />

      {tab === 'schedule' && (
        <div className="mob-subbar" role="tablist" aria-label="일정 보기 전환">
          {SCHEDULE_SUBS.map((s) => (
            <button
              key={s.id}
              type="button"
              role="tab"
              aria-selected={scheduleSub === s.id}
              className={`mob-sub-btn${scheduleSub === s.id ? ' is-on' : ''}`}
              onClick={() => setScheduleSub(s.id)}
            >
              {s.label}
            </button>
          ))}
        </div>
      )}

      <main className="mob-main">
        {tab === 'more' && !moreProgram ? (
          <MoreGrid
            list={programs(role)}
            onPick={(id) => {
              const target = tabForProgram(id);
              setTab(target);
              if (target === 'schedule') setScheduleSub(id);
              if (target === 'more') setMoreProgram(id);
            }}
          />
        ) : Screen ? (
          <Suspense fallback={<div className="mob-loading">불러오는 중…</div>}>
            <Screen windowId="mobile" params={screenParams} />
          </Suspense>
        ) : (
          <div className="mob-loading">화면을 열 수 없습니다.</div>
        )}
      </main>

      <MobileTabBar tab={tab} pending={pending} onSelect={selectTab} />
    </div>
  );
}
