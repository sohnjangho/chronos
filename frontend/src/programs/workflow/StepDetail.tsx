// 오른쪽 단계 상세: 도구·프로그램·왜·모델·걸린 시간·상태·토큰·비용, 받은 것·돌려준 것(접는 나무).
import JsonView from './JsonView';
import { circled, cost, programLabel, seconds, stepStatus, tokens, toolLabel } from './labels';
import type { Step } from './wfApi';

function timeText(s: Step): string {
  if (s.ms !== null) return seconds(s.ms);
  return s.status === 'running' ? '진행 중' : '—';
}

export default function StepDetail({ step }: { step: Step | null }) {
  return (
    <section className="wf-detail" aria-label="단계 상세">
      {step === null ? (
        <p className="wf-muted">단계를 고르면 여기에 자세히 보입니다.</p>
      ) : (
        <>
          <h3 className="wf-detail-h wf-wrap">{`${circled(step.n)} ${toolLabel(step.tool)}`}</h3>
          <dl className="wf-kv">
            <div>
              <dt>도구</dt>
              <dd className="wf-wrap">
                <code>{step.tool}</code>
              </dd>
            </div>
            <div>
              <dt>프로그램</dt>
              <dd>{programLabel(step.program)}</dd>
            </div>
            <div>
              <dt>왜</dt>
              <dd className="wf-wrap">{step.why || '—'}</dd>
            </div>
            <div>
              <dt>모델</dt>
              <dd className="wf-wrap">{step.model ?? '—'}</dd>
            </div>
            <div>
              <dt>걸린 시간</dt>
              <dd>{timeText(step)}</dd>
            </div>
            <div>
              <dt>상태</dt>
              <dd>{stepStatus(step.status)}</dd>
            </div>
            <div>
              <dt>토큰 · 비용</dt>
              <dd>{`${tokens(step.tokens)} · ${cost(step.cost)}`}</dd>
            </div>
          </dl>
          <JsonView label="받은 것" text={step.input_json} empty="없음" />
          <JsonView label="돌려준 것" text={step.output_json} empty={step.status === 'running' ? '아직 없습니다 (진행 중)' : '없음'} />
        </>
      )}
    </section>
  );
}
