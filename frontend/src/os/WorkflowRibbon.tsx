import Button from '../shared/ui/Button';
import { useAgentView } from './agentView';
import './workflowRibbon.css';

const GEN_STAGE_LABELS: Record<string, string> = {
  wbs: 'WBS 설계',
  schedule: '액티비티 조립',
  compute: 'CPM 계산',
  critical: '크리티컬 분석',
  check: '하네스 검증',
};

const STEP_ICON: Record<string, string> = {
  done: '✓',
  failed: '!',
  stopped: '■',
};

/**
 * OS 최상단 메뉴바 바로 아래(40px)에 뜨는 얇은 워크플로우 진행 리본.
 * 에이전트가 도구를 실행할 때 가로 노드로 실시간 진행을 보여 주고, 완료 후 1.8초 뒤 자동으로 접힌다.
 */
export default function WorkflowRibbon() {
  const ribbon = useAgentView((s) => s.ribbon);
  const collapse = useAgentView((s) => s.collapseRibbon);
  const openFullWorkflow = useAgentView((s) => s.openFullWorkflow);

  if (!ribbon.visible || ribbon.collapsed || ribbon.steps.length === 0) return null;

  const running = ribbon.status === 'running';
  const statusText =
    ribbon.status === 'running'
      ? '진행 중'
      : ribbon.status === 'done'
        ? '완료'
        : ribbon.status === 'stopped'
          ? '중단됨'
          : '실패';
  const genStageText = ribbon.genStage ? (GEN_STAGE_LABELS[ribbon.genStage] ?? ribbon.genStage) : null;

  return (
    <section
      role="region"
      aria-label="워크플로우 진행 상황"
      className={`os-wf-ribbon is-${ribbon.status}`}
    >
      <div className="os-wf-ribbon-left">
        <span className={`os-wf-ribbon-badge ${running ? 'is-running' : 'is-done'}`}>
          {running && <span className="os-wf-ribbon-dot" aria-hidden="true" />}
          {statusText}
        </span>
        <span className="os-wf-ribbon-title">
          {`워크플로우${ribbon.runId ? ` #${ribbon.runId}` : ''}`}
        </span>
      </div>

      <ol className="os-wf-ribbon-steps" aria-label="실행 단계">
        {ribbon.steps.map((step, idx) => (
          <li key={step.n} className="os-wf-ribbon-node-wrap">
            {idx > 0 && (
              <span className="os-wf-ribbon-arrow" aria-hidden="true">
                →
              </span>
            )}
            <span className={`os-wf-ribbon-node is-${step.status}`}>
              <span className="os-wf-ribbon-step-ico" aria-hidden="true">
                {step.status === 'running' ? <span className="os-wf-ribbon-pulse" /> : (STEP_ICON[step.status] ?? '·')}
              </span>
              <span className="os-wf-ribbon-step-text">{`${step.n}. ${step.label}`}</span>
              {step.tool === 'generate.run' && step.status === 'running' && genStageText && (
                <span className="os-wf-ribbon-sub">{genStageText}</span>
              )}
            </span>
          </li>
        ))}
      </ol>

      <div className="os-wf-ribbon-actions">
        <Button className="os-wf-ribbon-btn" onClick={openFullWorkflow}>
          상세
        </Button>
        <Button className="os-wf-ribbon-btn" onClick={collapse}>
          접기
        </Button>
      </div>
    </section>
  );
}
