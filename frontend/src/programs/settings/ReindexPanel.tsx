// 임베딩 다시 넣기 상태(시안 설정 A — 임베딩 줄 바로 아래 펼침, 진행 줄은 B 의 네 단계 글).
import { useEffect, useState } from 'react';
import { ApiError } from '../../shared/api';
import Button from '../../shared/ui/Button';
import type { LlmError, ReindexJob, ReindexState } from './model';
import { ErrorLine, toProblem } from './parts';
import { settingsApi } from './settingsApi';
import './reindex.css';

/** 진행 중이면 이만큼마다 다시 읽는다. */
export const POLL_MS = 3000;
export const OFF_LINE = '뜻 검색 서버가 꺼져 있어 낱말 검색만 씁니다.';
const RUNNING_LINE = '이미 다시 넣는 중입니다.';

/** 다시 넣기 요청의 실패: 503 은 오류가 아니라 상태(뜻 검색 서버 꺼짐), 409 already_running 은 정한 글. */
export type ReindexProblem = { off: true } | { error: LlmError };
export function reindexProblem(e: unknown): ReindexProblem {
  if (e instanceof ApiError && e.status === 503) return { off: true };
  if (e instanceof ApiError && e.code === 'already_running') return { error: { code: e.code, message: RUNNING_LINE } };
  return { error: toProblem(e) };
}

/** 503 이면 상태 한 줄(role=status), 아니면 오류 줄. */
export function ProblemLine({ problem, extra }: { problem: ReindexProblem | null; extra?: string }) {
  if (!problem) return null;
  if ('off' in problem) {
    return (
      <p className="st-muted" role="status">
        {extra ? `${OFF_LINE} ${extra}` : OFF_LINE}
      </p>
    );
  }
  return <ErrorLine error={problem.error} />;
}

/** 진행 중이면 POLL_MS 마다 다시 읽고, 끝나면(running 이 아니면) 멈춘다. tick 이 바뀌면 곧바로 다시 읽는다. */
function useReindexState(tick: number) {
  const [state, setState] = useState<ReindexState | null>(null);
  const [problem, setProblem] = useState<ReindexProblem | null>(null);
  const [poll, setPoll] = useState(0);
  useEffect(() => {
    let live = true;
    settingsApi
      .reindex()
      .then((s) => live && setState(s))
      .catch((e) => live && setProblem(reindexProblem(e)));
    return () => {
      live = false;
    };
  }, [tick, poll]);
  const running = state?.job?.status === 'running';
  useEffect(() => {
    if (!running) return;
    const timer = setTimeout(() => setPoll((p) => p + 1), POLL_MS);
    return () => clearTimeout(timer);
  }, [running, state]);
  const reload = () => setPoll((p) => p + 1);
  return { state, problem, setProblem, reload };
}

const percent = (job: ReindexJob) => (job.total > 0 ? Math.floor((job.done / job.total) * 100) : 0);

/** 네 단계: 새 모음 → 다시 넣기 → 찾기 바꾸기 → 옛 모음 지우기. 서버는 running 동안 2단계, done 이면 넷 다 끝. */
function Steps({ job }: { job: ReindexJob }) {
  const failed = job.status === 'failed';
  const second = failed ? `다시 넣기 실패 · ${job.done.toLocaleString()} / ${job.total.toLocaleString()}` : `다시 넣기 ${percent(job)}%`;
  const items: [string, 'done' | 'now' | 'fail' | 'wait'][] = [
    ['새 모음 만들기', 'done'],
    [second, failed ? 'fail' : 'now'],
    ['찾기를 새 모델로', 'wait'],
    ['옛 모음 지우기', 'wait'],
  ];
  return (
    <ol className="st-ri-steps" aria-label="다시 넣기 단계">
      {items.map(([text, mark], i) => (
        <li key={i} className={`st-ri-step is-${mark}`}>
          <i aria-hidden="true">{mark === 'done' ? '✓' : i + 1}</i>
          {text}
        </li>
      ))}
    </ol>
  );
}

function Progress({ job, active }: { job: ReindexJob; active: string }) {
  return (
    <div className="st-ri-run">
      <div className="st-ri-line">
        <b>{`다시 넣는 중 ${percent(job)}%`}</b>
        <span className="st-muted">{`${job.done.toLocaleString()} / ${job.total.toLocaleString()} 조각`}</span>
      </div>
      <div
        className="st-ri-bar"
        role="progressbar"
        aria-label="다시 넣기 진행"
        aria-valuemin={0}
        aria-valuemax={job.total}
        aria-valuenow={job.done}
      >
        <span style={{ width: `${percent(job)}%` }} />
      </div>
      <p className="st-muted st-wrap">{`찾기는 다 끝날 때까지 지금 모델(${active})로 합니다.`}</p>
    </div>
  );
}

/** 임베딩 줄 아래: 지금 찾기 모델과 배정한 모델, 진행 막대(3초마다 읽음), 「다시 시작」. tick 이 바뀌면 다시 읽는다. */
export default function ReindexPanel({ tick }: { tick: number }) {
  const { state, problem, setProblem, reload } = useReindexState(tick);
  const [busy, setBusy] = useState(false);
  const job = state?.job ?? null;
  const running = job?.status === 'running';
  const canRestart = !!state && (job?.status === 'failed' || (state.assigned_model !== state.active_model && !running));
  async function restart() {
    setBusy(true);
    setProblem(null);
    try {
      await settingsApi.restartReindex();
    } catch (e) {
      setProblem(reindexProblem(e));
    }
    setBusy(false);
    reload();
  }
  return (
    <section className="st-ri" aria-label="임베딩 다시 넣기">
      {state && (
        <dl className="st-facts st-facts-wide">
          <dt>지금 찾기 모델</dt>
          <dd>{state.active_model}</dd>
          <dt>배정한 모델</dt>
          <dd>{state.assigned_model}</dd>
        </dl>
      )}
      {job && (running || job.status === 'failed') && <Steps job={job} />}
      {job && running && state && <Progress job={job} active={state.active_model} />}
      {job?.status === 'failed' && <p className="st-warn">다시 넣기에 실패했습니다. 찾기는 지금 모델로 계속합니다.</p>}
      {state && !running && job?.status !== 'failed' && state.assigned_model !== state.active_model && (
        <p className="st-muted">배정한 모델로 아직 다시 넣지 않았습니다.</p>
      )}
      <ProblemLine problem={problem} />
      {canRestart && (
        <div className="st-actions">
          <Button disabled={busy} onClick={restart}>
            다시 시작
          </Button>
        </div>
      )}
    </section>
  );
}
