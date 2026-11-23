import { useEffect, useRef, useState } from 'react';
import { getProgram } from '../../os/registry';
import { useWindows } from '../../os/windowStore';
import Button from '../../shared/ui/Button';
import { asList, asObj, asText } from './cards/Card';
import { CardView, type CardCtx } from './cards';
import { useChat } from './chatStore';
import { seconds, STEP_STATUS, toolLabel } from './labels';
import { Markdown } from './markdown';
import type { Item, Json, Part, Retry, Step } from './thread';
import './thread.css';

type Agent = Extract<Item, { kind: 'agent' }>;

const stepsState = (steps: Step[]) =>
  steps.some((s) => s.status === 'running') ? 'running' : steps.some((s) => s.status === 'failed') ? 'failed' : steps.some((s) => s.status === 'stopped') ? 'stopped' : 'done';

/** 도구 단계는 접힌 한 줄 「이름들 · 도구 n개 · n초」. 펼치면 단계마다 이름·서버 도구 이름·시간·오류. */
function StepsLine({ steps }: { steps: Step[] }) {
  const [open, setOpen] = useState(false);
  const state = stepsState(steps);
  const ms = steps.reduce((sum, s) => sum + (s.ms ?? 0), 0);
  const known = steps.some((s) => s.ms !== null);
  const meta = `도구 ${steps.length}개${state === 'running' ? ' · 진행 중' : known ? ` · ${seconds(ms)}` : ''}`;
  return (
    <div className="ch-steps-wrap">
      <button type="button" className="ch-step" aria-expanded={open} onClick={() => setOpen(!open)}>
        <span className={`ch-dot is-${state}`} aria-hidden="true" />
        {!open && <span className="ch-step-names ch-ellipsis" title={[...new Set(steps.map((s) => s.tool))].join(' · ')}>{[...new Set(steps.map((s) => toolLabel(s.tool)))].join(' · ')}</span>}
        <span className="ch-step-meta">{meta}</span>
        <span aria-hidden="true">{open ? '⌄' : '›'}</span>
      </button>
      {open && (
        <ol className="ch-steps">
          {steps.map((s) => (
            <li key={s.callId}>
              <span className={`ch-dot is-${s.status}`} aria-hidden="true" />
              <span className="ch-step-body">
                {toolLabel(s.tool) !== s.tool && <span className="ch-step-name">{toolLabel(s.tool)}</span>}
                <code className="ch-wrap">{s.tool}</code>
                <span className="ch-muted">
                  {STEP_STATUS[s.status]}
                  {s.ms !== null && ` · ${seconds(s.ms)}`}
                </span>
                {s.error && <span className="ch-step-error ch-wrap">{s.error}</span>}
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function ErrorLine({ part }: { part: Extract<Part, { type: 'error' }> }) {
  const action = part.action;
  return (
    <div className={`ch-line-card ${part.code === 'stopped' ? 'is-muted' : 'is-bad'}`}>
      <span className="ch-wrap">{part.message}</span>
      {action && (
        <Button onClick={() => useWindows.getState().open(action.open, action.params)}>{`${getProgram(action.open)?.name ?? action.open} 열기`}</Button>
      )}
    </div>
  );
}

function AgentBlock({ item, ctx }: { item: Agent; ctx: CardCtx }) {
  return (
    <div className="ch-agent">
      {item.steps.length > 0 && <StepsLine steps={item.steps} />}
      {item.parts.map((p, i) =>
        p.type === 'text' ? (
          <Markdown key={i} text={p.text} />
        ) : p.type === 'notice' ? (
          <div key={i} className="ch-turn-notice" role="status">
            {p.text}
          </div>
        ) : p.type === 'card' ? (
          <CardView key={i} event={p.event} data={p.data} ctx={ctx} />
        ) : (
          <ErrorLine key={i} part={p} />
        ),
      )}
    </div>
  );
}

/** 질문지 제출·승인 거부 뒤 이어 가기(사용자 메시지)는 작은 시스템 카드로. */
function SystemCard({ content }: { content: Json }) {
  if (content.kind === 'approval_rejected') {
    return (
      <div className="ch-sys">
        <p className="ch-wrap">{`승인 거부 · ${asText(content.title) || `승인 ${asText(content.approval_id)}`}`}</p>
        {asText(content.note) && <p className="ch-muted ch-wrap">{`이유: ${asText(content.note)}`}</p>}
      </div>
    );
  }
  const head = `질문지 ${asText(content.questionnaire_id)} 제출`;
  if (!Array.isArray(content.answers)) return <div className="ch-sys"><p>{head}</p></div>;
  // 서버 자료라도 칸이 깨져 있을 수 있다: 묶음 수는 그대로 세고, 질문 글이 있는 줄만 보인다.
  const answers = asList(content.answers).map(asObj);
  const assumed = asList(content.assumed).map(asObj);
  return (
    <details className="ch-sys">
      <summary>{`${head} · 답 ${answers.length}개 · 가정 ${assumed.length}개`}</summary>
      <ul className="ch-plain">
        {answers.map((a, i) => asText(a.question) && <li key={`a${i}`} className="ch-wrap">{`${asText(a.question)}: ${asText(a.label)}`}</li>)}
        {assumed.map((a, i) => asText(a.question) && <li key={`g${i}`} className="ch-wrap ch-muted">{`${asText(a.question)}: 가정 — ${asText(a.assumption)}`}</li>)}
      </ul>
    </details>
  );
}

/** 다른 사람이 '거부하고 다시 짜기' 로 결정한 건: 누가·왜 + [다시 짜기 시작](approval_id 로 이어 가기). */
function RetryCard({ retry, sessionId }: { retry: Retry; sessionId: number }) {
  return (
    <section className="ch-card is-warn" aria-label="다시 짜기 요청">
      <h4 className="ch-card-h">다시 짜기 요청</h4>
      <div className="ch-card-b">
        <p className="ch-card-title ch-wrap">{retry.title}</p>
        <p className="ch-wrap">{`${retry.decided_by_name}님이 거부했습니다: ${retry.note}`}</p>
        <div className="ch-actions">
          <Button variant="primary" onClick={() => void useChat.getState().resume(sessionId, { approval_id: retry.approval_id })}>
            다시 짜기 시작
          </Button>
        </div>
      </div>
    </section>
  );
}

/** 다른 사람이 '거부하고 다시 짜기'로 돌려보낸 건이 있으면 대화 위쪽에 늘 보이는 띠(B4). 가장 오래된 건부터 시작한다. */
function RetryBanner({ retries, sessionId }: { retries: Retry[]; sessionId: number }) {
  const first = retries[0];
  return (
    <div className="ch-retry-banner" role="status" aria-label="거부 재작성 대기">
      <b>{`거부 재작성 대기 ${retries.length}건`}</b>
      <span className="ch-wrap">{`${first.decided_by_name}님이 「${first.title}」을 거부하고 다시 짜게 했습니다.`}</span>
      <Button variant="primary" onClick={() => void useChat.getState().resume(sessionId, { approval_id: first.approval_id })}>
        다시 짜기 시작
      </Button>
    </div>
  );
}

/** 아래 끝 가까이 있을 때만 새 내용으로 따라 내려간다(위를 읽는 중이면 두기). */
function useStickToBottom(dep: unknown, sessionId: number | null) {
  const ref = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  // 다른 대화로 옮기면 다시 아래 끝부터 따라간다.
  useEffect(() => {
    stick.current = true;
  }, [sessionId]);
  useEffect(() => {
    const el = ref.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [dep]);
  const onScroll = () => {
    const el = ref.current;
    if (el) stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  };
  return { ref, onScroll };
}

/** 가운데 대화: 내 말은 오른쪽 말풍선, 에이전트 답은 본문(도구 한 줄 · 글 · 카드). */
export default function Conversation() {
  const currentId = useChat((s) => s.currentId);
  const thread = useChat((s) => (s.currentId === null ? undefined : s.threads[s.currentId]));
  const { ref, onScroll } = useStickToBottom(thread, currentId);
  const failed = thread?.failedResume;
  const ctx: CardCtx = {
    sessionId: currentId,
    sendText: (text) => useChat.getState().send(text),
    failedQuestionnaire: failed && 'questionnaire_id' in failed ? failed.questionnaire_id : null,
    retryResume: () => {
      if (currentId !== null && failed) void useChat.getState().resume(currentId, failed);
    },
  };
  const items = thread?.items ?? [];
  const retries = thread?.retries ?? [];
  const waiting = thread?.streaming && items[items.length - 1]?.kind !== 'agent';
  return (
    <>
      {currentId !== null && retries.length > 0 && <RetryBanner retries={retries} sessionId={currentId} />}
      <div className="ch-scroll" ref={ref} onScroll={onScroll}>
        <div className="ch-thread" role="log" aria-label="대화 내용">
          {items.length === 0 && retries.length === 0 && !thread?.notice && (
            <p className="ch-empty">일정을 만들거나, 지연 영향을 묻거나, 고른 액티비티에 대해 물어보세요.</p>
          )}
          {items.map((it) =>
            it.kind === 'user' ? (
              <div key={it.key} className="ch-me ch-wrap">
                {it.fileNames && it.fileNames.length > 0 && (
                  <div className="ch-me-files">
                    {it.fileNames.map((n, i) => (
                      <span key={i} className="ch-mini-chip">
                        📎 {n}
                      </span>
                    ))}
                  </div>
                )}
                <div>{it.text}</div>
              </div>
            ) : it.kind === 'system' ? (
              <SystemCard key={it.key} content={it.content} />
            ) : (
              <AgentBlock key={it.key} item={it} ctx={ctx} />
            ),
          )}
          {waiting && <p className="ch-muted">답을 기다리는 중…</p>}
          {currentId !== null && retries.map((r) => <RetryCard key={r.approval_id} retry={r} sessionId={currentId} />)}
        </div>
      </div>
    </>
  );
}
