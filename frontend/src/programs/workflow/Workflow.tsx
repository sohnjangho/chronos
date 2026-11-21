// 워크플로우(시안 「워크플로우·스킬」의 실행 기록): 왼쪽 실행 목록 · 가운데 단계 그림 · 오른쪽 단계 상세.
// 저장한 워크플로우·스킬은 묶음 3 이라 탭을 두지 않는다. params.run 이면 그 실행을 연다.
import { useState } from 'react';
import type { ProgramProps } from '../../os/registry';
import Badge from '../../shared/ui/Badge';
import Button from '../../shared/ui/Button';
import { cost, stepStatus, tokens } from './labels';
import RunList from './RunList';
import StepDetail from './StepDetail';
import StepGraph from './StepGraph';
import { useWorkflowData } from './useWorkflowData';
import { wfApi, type RunDetail } from './wfApi';
import './workflow.css';

/** 고르지 않았으면 실행 중인 단계, 없으면 마지막 단계. */
const autoStep = (run: RunDetail) => (run.steps.find((s) => s.status === 'running') ?? run.steps.at(-1))?.n ?? null;

function Legend({ run }: { run: RunDetail }) {
  return (
    <div className="wf-legend">
      <span>
        <i className="wf-sw done" />
        완료
      </span>
      <span>
        <i className="wf-sw running" />
        실행 중
      </span>
      <span>
        <i className="wf-sw pending" />
        대기
      </span>
      <span>{`토큰 ${tokens(run.tokens)} · 단계 ${run.steps.length}개 · 비용 ${cost(run.cost)}`}</span>
    </div>
  );
}

function RunView({ run, error }: { run: RunDetail; error: string | null }) {
  const [picked, setPicked] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedMsg, setSavedMsg] = useState<string | null>(null);
  const n = picked ?? autoStep(run);
  const step = run.steps.find((s) => s.n === n) ?? null;

  async function saveAsSkill() {
    setSaving(true);
    setSavedMsg(null);
    try {
      const s = await wfApi.saveSkill(run.id, run.title || `워크플로우 #${run.id}`);
      setSavedMsg(`스킬 「${s.name}」로 저장했습니다.`);
    } catch (e) {
      setSavedMsg(e instanceof Error ? e.message : '스킬을 저장하지 못했습니다.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <main className="wf-main">
        <header className="wf-head">
          <h2 className="wf-title wf-wrap">{run.title || '제목 없는 실행'}</h2>
          <Badge tone={run.status === 'running' ? 'info' : run.status === 'failed' ? 'danger' : 'neutral'}>{stepStatus(run.status)}</Badge>
          {run.status === 'done' && run.steps.length > 0 && (
            <Button disabled={saving} onClick={() => void saveAsSkill()}>
              {saving ? '저장 중…' : '스킬로 저장'}
            </Button>
          )}
          {savedMsg && <span className="wf-muted" role="status">{savedMsg}</span>}
          {run.request && <p className="wf-request wf-wrap">{`요청: "${run.request}"`}</p>}
          {error && (
            <p className="wf-error" role="alert">
              {error}
            </p>
          )}
        </header>
        <div className="wf-board">
          {run.steps.length === 0 ? <p className="wf-muted wf-pad">아직 단계가 없습니다.</p> : <StepGraph steps={run.steps} selected={n} onSelect={setPicked} />}
        </div>
        <Legend run={run} />
      </main>
      <StepDetail step={step} />
    </>
  );
}

export default function Workflow({ params }: ProgramProps) {
  const d = useWorkflowData(params?.run);
  return (
    <div className="wf-root">
      <RunList runs={d.runs} selected={d.selected} onSelect={d.select} />
      {d.run ? (
        <RunView key={d.run.id} run={d.run} error={d.error} />
      ) : (
        <main className="wf-main">
          {d.error ? (
            <p className="wf-error wf-pad" role="alert">
              {d.error}
            </p>
          ) : (
            <p className="wf-muted wf-pad">{d.runs?.length === 0 ? '' : '실행을 고르세요.'}</p>
          )}
        </main>
      )}
    </div>
  );
}
