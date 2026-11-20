// 개발 콘솔(관리자, 시안 DevConsoleA A안): 탭 셋 — 에이전트 구조 · 실행 추적 · 사용량·비용.
// 설계 12장의 나머지 일곱 탭은 묶음 4. 위 줄은 요청 고르기와 그 요청의 루프·호출·토큰·비용·시간.
import { useState } from 'react';
import type { ProgramProps } from '../../os/registry';
import { useSession } from '../../os/session';
import Badge from '../../shared/ui/Badge';
import Tabs from '../../shared/ui/Tabs';
import AgentStructure from './AgentStructure';
import type { NodeKey, TurnDetail } from './devApi';
import { cost, seconds, status, tokens } from './format';
import NodeDetail from './NodeDetail';
import TraceTimeline from './TraceTimeline';
import TurnPicker from './TurnPicker';
import UsageTab from './UsageTab';
import { useTurnData } from './useTurnData';
import './devconsole.css';

type Tab = 'structure' | 'trace' | 'usage';
const TABS: { id: Tab; label: string }[] = [
  { id: 'structure', label: '에이전트 구조' },
  { id: 'trace', label: '실행 추적' },
  { id: 'usage', label: '사용량·비용' },
];

function TurnStats({ detail }: { detail: TurnDetail }) {
  const { turn, structure } = detail;
  const s = status(turn.status);
  const elapsed = turn.status === 'running' ? `${seconds(Math.max(0, Date.now() - Date.parse(turn.started_at)))}째` : turn.ms !== null ? seconds(turn.ms) : '—';
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
      {turn.cost !== null && <b>{cost(turn.cost)}</b>}
      <span title={turn.status === 'running' ? '이 화면의 시계로 센 시간' : undefined}>{elapsed}</span>
    </div>
  );
}

function StructureView({ detail }: { detail: TurnDetail }) {
  const [picked, setPicked] = useState<NodeKey | null>(null);
  const { nodes } = detail.structure;
  const key = picked ?? nodes.find((n) => n.state === 'now')?.key ?? 'respond';
  const node = nodes.find((n) => n.key === key) ?? nodes[0];
  const inner = detail.timeline.filter((t) => t.kind === 'inner_llm').length;
  return (
    <div className="dc-split">
      <div className="dc-board">
        <AgentStructure nodes={nodes} turn={detail.turn} selected={node?.key ?? null} onSelect={setPicked} />
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
            건너뜀(묶음 3)
          </span>
          <span>칸을 누르면 상세가 열립니다</span>
        </div>
      </div>
      {node && <NodeDetail node={node} innerCalls={inner} />}
    </div>
  );
}

function AdminConsole() {
  const [tab, setTab] = useState<Tab>('structure');
  const d = useTurnData();
  const turnTab = tab !== 'usage';
  const empty = d.turns?.length === 0 ? '아직 기록된 요청이 없습니다. 대화창에서 에이전트에게 요청하면 여기에 쌓입니다.' : '불러오는 중…';
  return (
    <div className="dc-root">
      <div className="dc-tabbar">
        <Tabs items={TABS} value={tab} onChange={(id) => setTab(id as Tab)} label="개발 콘솔" />
      </div>
      {turnTab && (
        <div className="dc-top">
          <TurnPicker turns={d.turns} current={d.detail?.turn ?? null} onOpen={() => void d.reloadTurns()} onPick={d.select} />
          {d.detail && <TurnStats detail={d.detail} />}
        </div>
      )}
      {turnTab && d.error && (
        <p className="dc-error dc-pad" role="alert">
          {d.error}
        </p>
      )}
      <div className="dc-body" role="tabpanel" aria-label={TABS.find((t) => t.id === tab)!.label}>
        {tab === 'usage' && <UsageTab />}
        {turnTab && !d.detail && !d.error && <p className="dc-empty">{empty}</p>}
        {tab === 'structure' && d.detail && <StructureView key={d.detail.turn.turn_id} detail={d.detail} />}
        {tab === 'trace' && d.detail && (
          <div className="dc-scroll">
            <TraceTimeline key={d.detail.turn.turn_id} items={d.detail.timeline} />
          </div>
        )}
      </div>
    </div>
  );
}

export default function DevConsole(_: ProgramProps) {
  void _;
  const admin = useSession((s) => s.session?.user.role === 'admin');
  if (!admin) {
    return (
      <div className="dc-root">
        <p className="dc-empty">개발 콘솔은 관리자만 쓸 수 있습니다.</p>
      </div>
    );
  }
  return <AdminConsole />;
}
