// 개발 콘솔(관리자, 시안 DevConsoleA A안): 탭 셋 — 에이전트 구조 · 실행 추적 · 사용량·비용.
// 설계 12장의 나머지 일곱 탭은 묶음 4. 위 줄은 요청 고르기와 그 요청의 루프·호출·토큰·비용·시간.
import { useEffect, useState } from 'react';
import type { ProgramProps } from '../../os/registry';
import { useSession } from '../../os/session';
import Badge from '../../shared/ui/Badge';
import Tabs from '../../shared/ui/Tabs';
import AgentStructure from './AgentStructure';
import { devApi, type CatalogOut, type NodeKey, type OutreachRow, type PointsStage as Stage, type TurnDetail } from './devApi';
import { costWithEstimate, seconds, status, tokens } from './format';
import HarnessTab from './HarnessTab';
import HealthTab from './HealthTab';
import NodeDetail from './NodeDetail';
import OutreachTrace from './OutreachTrace';
import PointsStage, { PointsStages } from './PointsStage';
import RegistryTab from './RegistryTab';
import SourcesTab from './SourcesTab';
import TraceTimeline from './TraceTimeline';
import TurnFlowDiagram from './TurnFlowDiagram';
import TurnPicker from './TurnPicker';
import UpdatesTab from './UpdatesTab';
import UsageTab from './UsageTab';
import { useTurnData } from './useTurnData';
import './devconsole.css';

type Tab = 'structure' | 'harness' | 'sources' | 'registry' | 'health' | 'trace' | 'usage' | 'updates';
const TABS: { id: Tab; label: string }[] = [
  { id: 'structure', label: '에이전트 구조' },
  { id: 'harness', label: '하네스·차단 시험' },
  { id: 'sources', label: '프롬프트·지식' },
  { id: 'registry', label: '도구·스킬' },
  { id: 'health', label: '시스템 진단' },
  { id: 'trace', label: '실행 추적' },
  { id: 'usage', label: '사용량·비용' },
  { id: 'updates', label: '업데이트 내역' },
];

/** active 인 동안 1초마다 다시 그린다(걸린 시간 「n초째」 를 위해). */
function useTicker(active: boolean) {
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!active) return;
    let timer: ReturnType<typeof setTimeout>;
    const next = () => {
      timer = setTimeout(() => {
        setTick((n) => n + 1);
        next();
      }, 1000);
    };
    next();
    return () => clearTimeout(timer);
  }, [active]);
}

/** 걸린 시간: 끝났으면 턴 전체, 실행 중이면 「n초째」(이 화면 시계), 다시 읽기를 멈췄으면 마지막으로 확인한 때까지. */
function Elapsed({ detail, halted, checkedAt }: { detail: TurnDetail; halted: boolean; checkedAt: number | null }) {
  const { turn } = detail;
  const running = turn.status === 'running';
  useTicker(running && !halted);
  if (!running) return <span>{turn.ms !== null ? seconds(turn.ms) : '—'}</span>;
  const start = Date.parse(turn.started_at);
  if (halted) {
    return <span title="상세를 더 읽지 못해 그 뒤는 알 수 없습니다.">{`${seconds(Math.max(0, (checkedAt ?? start) - start))}째까지 확인`}</span>;
  }
  return <span title="이 화면의 시계로 센 시간">{`${seconds(Math.max(0, Date.now() - start))}째`}</span>;
}

function TurnStats({ detail, halted, checkedAt }: { detail: TurnDetail; halted: boolean; checkedAt: number | null }) {
  const { turn, structure } = detail;
  const s = status(turn.status);
  return (
    <div className="dc-stats" role="group" aria-label="이 요청">
      <Badge tone={s.tone}>{s.label}</Badge>
      <span>
        루프 <b>{`${structure.loop_count}바퀴`}</b> <span>{`/ 한도 ${structure.limit}`}</span>
      </span>
      <span>
        도구 호출 <b>{turn.tool_calls}</b>
      </span>
      <span title="루프의 모델 호출과 도구 안 모델 호출을 더한 수">
        모델 호출 <b>{turn.llm_calls}</b>
      </span>
      <span>
        토큰 <b>{tokens(turn.tokens)}</b>
      </span>
      {turn.cost !== null && <b>{costWithEstimate(turn.cost, turn.cost_estimated)}</b>}
      <Elapsed detail={detail} halted={halted} checkedAt={checkedAt} />
    </div>
  );
}

function StructureView({ detail }: { detail: TurnDetail }) {
  const [picked, setPicked] = useState<NodeKey | null>(null);
  const [mode, setMode] = useState<'arch' | 'flow'>('arch');
  const { nodes, edges_lit: edgesLit, harness_summary: harnessSummary } = detail.structure;
  const key = picked ?? nodes.find((n) => n.state === 'now')?.key ?? 'respond';
  const node = nodes.find((n) => n.key === key) ?? nodes[0];
  const inner = detail.timeline.filter((t) => t.kind === 'inner_llm').length;
  return (
    <div className="dc-split">
      <div className="dc-board">
        <div className="dc-modebar" role="group" aria-label="다이어그램 보기 전환">
          <button type="button" className={`dc-mode-btn${mode === 'arch' ? ' is-on' : ''}`} aria-pressed={mode === 'arch'} onClick={() => setMode('arch')}>
            전체 구조
          </button>
          <button type="button" className={`dc-mode-btn${mode === 'flow' ? ' is-on' : ''}`} aria-pressed={mode === 'flow'} onClick={() => setMode('flow')}>
            이번 턴 실행 흐름도
          </button>
        </div>
        {mode === 'arch' ? (
          <AgentStructure
            nodes={nodes}
            turn={detail.turn}
            selected={node?.key ?? null}
            edgesLit={edgesLit}
            harnessSummary={harnessSummary}
            onSelect={setPicked}
          />
        ) : (
          <TurnFlowDiagram detail={detail} selected={node?.key ?? null} onSelect={setPicked} />
        )}
        <div className="dc-legend">
          <span>
            <i className="dc-sw is-past" />
            지나감
          </span>
          <span>
            <i className="dc-sw is-now" />
            지금
          </span>
          <span>
            <i className="dc-sw is-todo" />
            아직
          </span>
          <span>
            <i className="dc-sw is-skipped" />
            건너뜀
          </span>
          <span>
            <i className="dc-line-unknown" />
            기록에 남지 않는 길
          </span>
          <span>칸을 누르면 상세가 열립니다</span>
        </div>
      </div>
      {node && <NodeDetail node={node} innerCalls={inner} />}
    </div>
  );
}

/** 실행 추적에서 턴 대신 고른 것: 연락 기록(Task 108) 또는 관리 포인트 차이(계획 5 Task 7 — 승인함처럼 턴 밖에서 바뀐 것도).
 * 하나를 고르면 다른 하나는 비우고, 턴을 고르면 둘 다 비운다. */
function useTracePick() {
  const [contact, setContact] = useState<OutreachRow | null>(null);
  const [pointRun, setPointRun] = useState<Stage | null>(null);
  return {
    contact,
    pointRun,
    pickContact: (r: OutreachRow) => { setPointRun(null); setContact(r); },
    pickRun: (s: Stage) => { setContact(null); setPointRun(s); },
    clear: () => { setContact(null); setPointRun(null); },
  };
}

function resolveTab(tabParam: string | undefined): Tab {
  return TABS.some((t) => t.id === tabParam) ? (tabParam as Tab) : 'structure';
}

function AdminConsole({ params }: { params?: Record<string, string> }) {
  const [tab, setTab] = useState<Tab>(() => resolveTab(params?.tab));
  const [seenParams, setSeenParams] = useState(params);
  if (params !== seenParams) {
    setSeenParams(params);
    if (params?.tab) setTab(resolveTab(params.tab));
  }
  const focus = params?.focus; // 하네스 탭에서 내릴 카드(「관리 포인트」 창 → points)
  const [catalog, setCatalog] = useState<CatalogOut | null>(null);
  const [catalogTick, setCatalogTick] = useState(0);
  const d = useTurnData();
  const turnTab = tab === 'structure' || tab === 'trace';
  const { contact, pointRun, pickContact, pickRun, clear } = useTracePick();
  const showContact = tab === 'trace' && contact !== null;
  const showRun = tab === 'trace' && pointRun !== null && !showContact;
  const turnShown = turnTab && !showContact && !showRun;
  const catTab = tab === 'harness' || tab === 'sources' || tab === 'registry';
  useEffect(() => {
    if (!catTab) return;
    let live = true;
    void devApi
      .catalog()
      .then((c) => live && setCatalog(c))
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [catTab, catalogTick]);
  const reloadCatalog = () => setCatalogTick((t) => t + 1);
  const exportTurnJson = () => {
    if (!d.detail) return;
    const blob = new Blob([JSON.stringify(d.detail, null, 2)], { type: 'application/json;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `chronos-turn-${d.detail.turn.turn_id}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };
  const empty = d.turns?.length === 0 ? '아직 기록된 요청이 없습니다. 대화창에서 에이전트에게 요청하면 여기에 쌓입니다.' : '불러오는 중…';
  return (
    <div className="dc-root">
      <div className="dc-tabbar">
        <Tabs items={TABS} value={tab} onChange={(id) => setTab(id as Tab)} label="개발 콘솔" />
      </div>
      {turnTab && (
        <div className="dc-top">
          <TurnPicker
            turns={d.turns}
            current={d.detail?.turn ?? null}
            onOpen={() => void d.reloadTurns()}
            onPick={(id) => {
              clear();
              d.select(id);
            }}
            outreach={tab === 'trace' ? { current: contact, onPick: pickContact } : undefined}
            points={tab === 'trace' ? { current: pointRun, onPick: pickRun } : undefined}
          />
          {d.detail && turnShown && <TurnStats detail={d.detail} halted={d.halted} checkedAt={d.checkedAt} />}
          {d.detail && turnShown && (
            <button type="button" className="dc-btn dc-export-btn" onClick={exportTurnJson}>
              JSON 내보내기
            </button>
          )}
        </div>
      )}
      {turnShown && d.error && (
        <p className="dc-error dc-pad" role="alert">
          {d.error}
        </p>
      )}
      <div className="dc-body" role="tabpanel" aria-label={TABS.find((t) => t.id === tab)!.label}>
        {tab === 'usage' && <UsageTab />}
        {tab === 'health' && <HealthTab />}
        {tab === 'updates' && <UpdatesTab />}
        {catTab && !catalog && <p className="dc-empty">원천 카탈로그를 불러오는 중…</p>}
        {tab === 'harness' && catalog && <HarnessTab catalog={catalog} onSaved={reloadCatalog} focus={focus} />}
        {tab === 'sources' && catalog && <SourcesTab catalog={catalog} />}
        {tab === 'registry' && catalog && <RegistryTab catalog={catalog} onChanged={reloadCatalog} />}
        {turnShown && !d.detail && !d.error && <p className="dc-empty">{empty}</p>}
        {showContact && (
          <div className="dc-scroll">
            <OutreachTrace key={`${contact.kind}/${contact.id}`} row={contact} />
          </div>
        )}
        {tab === 'structure' && d.detail && <StructureView key={d.detail.turn.turn_id} detail={d.detail} />}
        {showRun && pointRun && <div className="dc-scroll"><PointsStage stage={pointRun} /></div>}
        {tab === 'trace' && turnShown && d.detail && (
          <div className="dc-scroll">
            <TraceTimeline key={d.detail.turn.turn_id} items={d.detail.timeline} running={d.detail.turn.status === 'running'} />
            <PointsStages stages={d.detail.points ?? []} />
          </div>
        )}
      </div>
    </div>
  );
}

export default function DevConsole({ params }: ProgramProps) {
  const admin = useSession((s) => s.session?.user.role === 'admin');
  if (!admin) {
    return (
      <div className="dc-root">
        <p className="dc-empty">개발 콘솔은 관리자만 쓸 수 있습니다.</p>
      </div>
    );
  }
  return <AdminConsole params={params} />;
}
