import { useEffect, useState, type ReactNode } from 'react';
import { useWindows } from '../../os/windowStore';
import Button from '../../shared/ui/Button';
import Tabs from '../../shared/ui/Tabs';
import { checkLine, asList, asObj, asNum } from './cards/Card';
import { listRuns, type RunItem } from './chatApi';
import { useChat } from './chatStore';
import { circled, domainLabel, STEP_STATUS, tokens, toolLabel } from './labels';
import type { Thread } from './thread';
import { useEffectiveUi, useScheduleItem, useSeeing } from './seeing';

const openWorkflow = (run: number) => useWindows.getState().open('workflow', { run: String(run) });

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="ch-ctx-row">
      <dt>{label}</dt>
      <dd className="ch-wrap">{children}</dd>
    </div>
  );
}

/** 이 대화의 카드에서 마지막 점검 결과와 가정 수(코드가 계산한 값만). */
function lastFindings(thread: Thread | undefined): { check: string | null; assumptions: number | null } {
  let check: string | null = null;
  let assumptions: number | null = null;
  for (const item of thread?.items ?? []) {
    if (item.kind !== 'agent') continue;
    for (const p of item.parts) {
      if (p.type !== 'card') continue;
      if (p.event === 'approval' || p.data.kind === 'auto_applied') check = checkLine(asObj(asObj(p.data.summary).check)) ?? check;
      if (p.data.kind === 'generation_result') {
        assumptions = asList(p.data.assumptions).length;
        check = `위반 ${asList(p.data.violations).length} · 자동 점검 안 됨 ${asNum(p.data.uncheckable_count) ?? 0}`;
      }
    }
  }
  return { check, assumptions };
}

function ContextTab({ thread }: { thread: Thread | undefined }) {
  const ui = useEffectiveUi();
  const seeing = useSeeing(ui);
  const schedule = useScheduleItem(ui.schedule_id, thread?.streaming);
  const found = lastFindings(thread);
  const wf = thread?.workflow;
  const u = thread?.usage;
  return (
    <div className="ch-ctx-body">
      <h3 className="ch-ctx-h">지금 다루는 것</h3>
      <dl className="ch-ctx-dl">
        <Row label="일정">{schedule ? <b>{schedule.name}</b> : ui.schedule_id === undefined ? '고른 일정 없음' : `일정 ${ui.schedule_id}`}</Row>
        {schedule && <Row label="분야·정밀도">{`${domainLabel(schedule.domain)} · ${schedule.level} · 버전 ${schedule.version}`}</Row>}
        <Row label="보는 화면">{seeing || '없음'}</Row>
      </dl>
      <h3 className="ch-ctx-h">에이전트가 참고하는 것</h3>
      <dl className="ch-ctx-dl">
        <Row label="마지막 점검">{found.check ?? '아직 없음'}</Row>
        <Row label="가정">{found.assumptions === null ? '아직 없음' : `${found.assumptions}개`}</Row>
      </dl>
      <h3 className="ch-ctx-h">워크플로우</h3>
      {wf && wf.steps.length > 0 ? (
        <>
          <ol className="ch-ctx-steps" aria-label="워크플로우 단계">
            {wf.steps.map((s) => (
              <li key={s.n}>
                <span className={`ch-dot is-${s.status}`} aria-hidden="true" />
                <span className="ch-wrap">{`${circled(s.n)} ${toolLabel(s.tool)} · ${STEP_STATUS[s.status] ?? s.status}`}</span>
              </li>
            ))}
          </ol>
          <Button className="ch-ctx-btn" onClick={() => openWorkflow(wf.run_id)}>
            워크플로우 창에서 보기
          </Button>
        </>
      ) : (
        <p className="ch-muted">이번 요청에서 아직 실행한 단계가 없습니다.</p>
      )}
      <h3 className="ch-ctx-h">이 창에서 받은 사용량</h3>
      <dl className="ch-ctx-dl">
        <Row label="토큰">{u ? `입력 ${tokens(u.input_tokens)} · 출력 ${tokens(u.output_tokens)}` : '—'}</Row>
        <Row label="호출">{u ? `${u.calls}회` : '—'}</Row>
        <Row label="비용">{u?.cost === null || u?.cost === undefined ? '—' : `$${u.cost.toFixed(2)}`}</Row>
      </dl>
    </div>
  );
}

/** 이 대화의 워크플로우 실행(새것부터). 누르면 워크플로우 창. */
function ActivityTab({ sessionId, streaming }: { sessionId: number | null; streaming: boolean }) {
  const [runs, setRuns] = useState<RunItem[] | null>(null);
  useEffect(() => {
    if (sessionId === null) return;
    let live = true;
    listRuns().then(
      (all) => live && setRuns(all.filter((r) => r.chat_session_id === sessionId)),
      () => live && setRuns([]),
    );
    return () => {
      live = false;
    };
  }, [sessionId, streaming]);
  if (sessionId === null || !runs?.length) return <p className="ch-ctx-body ch-muted">이 대화의 실행 기록이 아직 없습니다.</p>;
  return (
    <div className="ch-ctx-body">
      {runs.map((r) => (
        <button key={r.id} type="button" className="ch-run" onClick={() => openWorkflow(r.id)}>
          <span className="ch-wrap">{r.title}</span>
          <span className="ch-muted">{`${STEP_STATUS[r.status] ?? r.status} · 단계 ${r.step_count}개`}</span>
        </button>
      ))}
    </div>
  );
}

/** 큰 화면 오른쪽(330px): 컨텍스트(지금 다루는 일정 · 참고하는 것 · 워크플로우 · 사용량) · 활동(이 대화의 실행). */
export default function ContextPanel() {
  const [tab, setTab] = useState('context');
  const currentId = useChat((s) => s.currentId);
  const thread = useChat((s) => (s.currentId === null ? undefined : s.threads[s.currentId]));
  return (
    <aside className="ch-ctx" aria-label="대화 정보">
      <Tabs
        label="대화 정보"
        value={tab}
        onChange={setTab}
        items={[
          { id: 'context', label: '컨텍스트' },
          { id: 'activity', label: '활동' },
        ]}
      />
      <div className="ch-ctx-scroll">
        {tab === 'context' ? <ContextTab thread={thread} /> : <ActivityTab sessionId={currentId} streaming={thread?.streaming ?? false} />}
      </div>
    </aside>
  );
}
