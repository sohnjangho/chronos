import { useState } from 'react';
import { useAgentView, type AgentViewMode } from '../../os/agentView';
import { useDock } from '../../os/dockStore';
import { getProgram } from '../../os/registry';
import { useShell } from '../../os/shell';
import { useTabletRail } from '../../os/tabletRailStore';
import { useTheme, type Theme } from '../../os/theme';
import { useDetectedDevice, useDeviceMode, type DeviceMode, type ResolvedDevice } from '../../os/useIsMobile';
import { useZoom } from '../../os/zoom';
import Button from '../../shared/ui/Button';
import WallpaperCard from './WallpaperCard';

const THEMES: { id: Theme; title: string; subtitle: string; previewClass: string }[] = [
  { id: 'light', title: '주간 모드 (Daylight Sky)', subtitle: '맑은 하늘색 그라데이션 바탕과 밝은 유리 카드', previewClass: 'is-light' },
  { id: 'dark', title: '야간 모드 (Midnight Aurora)', subtitle: '깊은 네이비 오로라 바탕과 저눈부심 다크 패널', previewClass: 'is-dark' },
];

const AGENT_VIEW_MODES: { id: AgentViewMode; title: string; desc: string }[] = [
  {
    id: 'stage',
    title: '스테이지 창 전환 · 포커스 추적 (Computer Use 권장)',
    desc: '요청 시 워크플로우 창이 열려 노드가 생성되고, 각 단계의 도구 프로그램 창이 스테이지 전환 이펙트와 함께 전면 포커스로 작동합니다.',
  },
  {
    id: 'workflow',
    title: '워크플로우 창만 포커스',
    desc: '도구 프로그램 창을 열지 않고 워크플로우 실행 그래프 창만 전면으로 열어 단계 진행 상황을 실시간 표시합니다.',
  },
  {
    id: 'off',
    title: '끄기 (대화창 내부만 표시)',
    desc: '자동 창 전환 없이 에이전트 대화창 안의 도구 진행 상태만 표시합니다.',
  },
];

const DEVICE_MODES: { id: DeviceMode; label: string; desc: string }[] = [
  { id: 'auto', label: '자동 감지 (권장)', desc: '접속한 기기(스마트폰·태블릿·데스크톱)를 자동 판별해 맞는 화면으로 엽니다.' },
  { id: 'desktop', label: '데스크톱 (PC 창)', desc: '다중 창과 하단 Dock · 스테이지 전환을 쓰는 PC 화면으로 고정합니다.' },
  { id: 'tablet', label: '태블릿', desc: '2열 카드와 5열 앱 서랍 중심의 태블릿 전용 셸로 전환합니다.' },
  { id: 'phone', label: '스마트폰', desc: '1열 터치 최적화와 하단 5탭바 중심의 모바일 셸로 전환합니다.' },
];

const DEVICE_LABELS: Record<ResolvedDevice, string> = {
  desktop: '데스크톱 (PC 창)',
  tablet: '태블릿',
  phone: '스마트폰',
};

/** 주간 / 야간 모드 고르기. */
function ThemeCard({ onNotice }: { onNotice(text: string | null): void }) {
  const theme = useTheme((s) => s.theme);
  const setTheme = useTheme((s) => s.setTheme);
  return (
    <section className="st-card" aria-label="화면 테마 선택">
      <div className="st-card-head">
        <b className="st-card-name">주간 / 야간 모드</b>
        <span className="st-gap" />
        <span className="st-muted">{`현재: ${theme === 'dark' ? '야간 모드' : '주간 모드'}`}</span>
      </div>
      <div className="st-theme-grid" role="group" aria-label="테마 선택">
        {THEMES.map((item) => {
          const active = theme === item.id;
          return (
            <button
              key={item.id}
              type="button"
              className="st-theme-card"
              aria-pressed={active}
              onClick={() => {
                setTheme(item.id);
                onNotice(null);
              }}
            >
              <span className={`st-theme-preview ${item.previewClass}`} aria-hidden="true">
                <span className="st-tp-bar" />
                <span className="st-tp-win" />
              </span>
              <span className="st-theme-meta">
                <b>{item.title}</b>
                <span className="st-muted">{item.subtitle}</span>
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
}

/** 에이전트 실시간 작업 화면 연출(스테이지 · 워크플로우만 · 끄기). */
function AgentViewCard({ onNotice }: { onNotice(text: string | null): void }) {
  const agentViewMode = useAgentView((s) => s.mode);
  const setAgentViewMode = useAgentView((s) => s.setMode);
  return (
    <section className="st-card" aria-label="에이전트 실시간 작업 화면 연출">
      <div className="st-card-head">
        <b className="st-card-name">에이전트 실시간 작업 화면 연출 (Computer Use 뷰)</b>
        <span className="st-gap" />
        <span className="st-muted">
          {AGENT_VIEW_MODES.find((m) => m.id === agentViewMode)?.id === 'stage'
            ? '스테이지 포커스 켜짐'
            : agentViewMode === 'workflow'
              ? '워크플로우만 포커스'
              : '꺼짐'}
        </span>
      </div>
      <div className="st-radios" role="group" aria-label="에이전트 작업 연출 방식">
        {AGENT_VIEW_MODES.map((item) => (
          <button
            key={item.id}
            type="button"
            className="st-theme-card"
            aria-pressed={agentViewMode === item.id}
            onClick={() => {
              setAgentViewMode(item.id);
              onNotice(`에이전트 실시간 작업 화면 연출을 「${item.title}」(으)로 설정했습니다.`);
            }}
          >
            <span className="st-theme-meta">
              <b>{item.title}</b>
              <span className="st-muted">{item.desc}</span>
            </span>
          </button>
        ))}
      </div>
    </section>
  );
}

/** 접속 기기 화면 형태(자동 인식 · 수동 전환). */
function DeviceCard({ onNotice }: { onNotice(text: string | null): void }) {
  const deviceMode = useDeviceMode((s) => s.mode);
  const setDeviceMode = useDeviceMode((s) => s.setMode);
  const detectedDevice = useDetectedDevice();
  return (
    <section className="st-card" aria-label="접속 기기 화면 형태">
      <div className="st-card-head">
        <b className="st-card-name">접속 기기 화면 형태 (자동 인식 · 수동 전환)</b>
        <span className="st-gap" />
        <span className="st-muted">{`자동 감지된 현재 기기: ${DEVICE_LABELS[detectedDevice]}`}</span>
      </div>
      <div className="st-theme-grid" role="group" aria-label="화면 형태 선택">
        {DEVICE_MODES.map((item) => (
          <button
            key={item.id}
            type="button"
            className="st-theme-card"
            aria-pressed={deviceMode === item.id}
            onClick={() => {
              setDeviceMode(item.id);
              onNotice(`화면 형태를 「${item.label}」(으)로 변경했습니다.`);
            }}
          >
            <span className="st-theme-meta">
              <b>{item.label}</b>
              <span className="st-muted">{item.desc}</span>
            </span>
          </button>
        ))}
      </div>
    </section>
  );
}

/** 창 화면 배율(Zoom) 초기화. */
function ZoomCard({ onNotice }: { onNotice(text: string | null): void }) {
  const levels = useZoom((s) => s.levels);
  const resetZoom = useZoom((s) => s.reset);
  const resetAllZoom = useZoom((s) => s.resetAll);

  const customZooms = Object.entries(levels).filter(([, pct]) => pct !== 100);
  return (
    <section className="st-card" aria-label="창 화면 배율">
      <div className="st-card-head">
        <b className="st-card-name">창 화면 배율 (Zoom)</b>
        <span className="st-gap" />
        <Button
          disabled={customZooms.length === 0}
          onClick={() => {
            resetAllZoom();
            onNotice('모든 창의 배율을 100%로 초기화했습니다.');
          }}
        >
          모든 창 배율 100%로 초기화
        </Button>
      </div>
      {customZooms.length === 0 ? (
        <p className="st-muted">모든 프로그램 창이 기본 배율(100%)로 열립니다.</p>
      ) : (
        <ul className="st-chip-list" aria-label="배율이 변경된 프로그램">
          {customZooms.map(([id, pct]) => (
            <li key={id} className="st-chip-item">
              <span>{`${getProgram(id)?.name ?? id}: ${pct}%`}</span>
              <button type="button" className="st-chip-reset" aria-label={`${getProgram(id)?.name ?? id} 배율 초기화`} onClick={() => resetZoom(id)}>
                100%
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** Dock · 태블릿 메뉴 구성 복원. */
function DockCard({ onNotice }: { onNotice(text: string | null): void }) {
  const pinned = useDock((s) => s.pinned);
  const resetDock = useDock((s) => s.resetDefault);
  const tabletRail = useTabletRail((s) => s.items);
  const resetTabletRail = useTabletRail((s) => s.resetDefault);
  return (
    <section className="st-card" aria-label="Dock 구성">
      <div className="st-card-head">
        <b className="st-card-name">Dock · 태블릿 메뉴 구성</b>
        <span className="st-gap" />
        <Button onClick={() => useShell.getState().setDrawer('edit')}>Dock 아이콘 편집</Button>
        <Button
          disabled={pinned === null}
          onClick={() => {
            resetDock();
            onNotice('Dock 구성을 기본값으로 복원했습니다.');
          }}
        >
          Dock 기본 구성으로 복원
        </Button>
      </div>
      <p className="st-muted">
        {pinned === null
          ? '현재 기본 Dock 구성을 사용 중입니다. (Dock 아이콘을 직접 끌어 순서를 바꾸거나 「Dock 아이콘 편집」에서 추가·제거할 수 있습니다.)'
          : `사용자 지정 Dock 사용 중 · 고정 프로그램 ${pinned.length}개`}
      </p>
      <div className="st-card-head">
        <b className="st-card-name">태블릿 왼쪽 메뉴 구성</b>
        <span className="st-gap" />
        <Button
          disabled={tabletRail === null}
          onClick={() => {
            resetTabletRail();
            onNotice('태블릿 왼쪽 메뉴 구성을 기본값으로 복원했습니다.');
          }}
        >
          태블릿 메뉴 기본값 복원
        </Button>
      </div>
      <p className="st-muted">
        {tabletRail === null
          ? '현재 기본 태블릿 왼쪽 메뉴 구성을 사용 중입니다. (태블릿 왼쪽 하단 「메뉴 편집」에서 추가·제거·순서 변경 가능)'
          : `사용자 지정 태블릿 메뉴 사용 중 · ${tabletRail.length}개`}
      </p>
    </section>
  );
}

/** 「화면 · 테마」: 주간/야간 모드, Computer Use 연출, 기기 형태 전환, 창 배율 초기화, Dock 복원. */
export default function AppearanceSection() {
  const [notice, setNotice] = useState<string | null>(null);

  return (
    <div className="st-pane">
      <div className="st-section-head">
        <h2>화면 · 테마</h2>
        <p className="st-muted">바탕화면 색상 테마, 프로그램 창 배율(Zoom), 하단 Dock 구성을 관리합니다.</p>
      </div>

      <ThemeCard onNotice={setNotice} />

      <WallpaperCard />

      <AgentViewCard onNotice={setNotice} />

      <DeviceCard onNotice={setNotice} />

      <ZoomCard onNotice={setNotice} />

      <DockCard onNotice={setNotice} />

      {notice && (
        <p className="st-ok" role="status">
          {notice}
        </p>
      )}
    </div>
  );
}
