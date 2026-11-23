// 통화 카드 한 장(Task 92, 시안 ②). 위: 누가 걸었나 · 「AI 전화」 · 상태 · 시각 · 승인한 사람 / 목적(받지 않았으면 「자동으로 다시 걸지
// 않습니다」) · 요약 · 결과(에이전트 제안 · 사람이 확정) · 질문별 답과 근거(근거 없는 답은 「확인 필요」) · 연결된 작업 · 하네스 사건 접힌 줄 /
// 단추: [받아쓰기 보기][녹음 듣기][결과 확정][다시 걸기] · 걸고 있으면 [통화 끊기] · 초안 [버리기][전화 걸기 창 열기] · 예약 [예약 취소].
// 상태는 서버가 준 줄에서만 읽는다 — 누른 뒤의 모습은 다시 읽은 줄이 정한다. 사람이 쓴 글의 번호처럼 보이는 숫자는 가려 보인다.
import { useEffect, useState } from 'react';
import { getProgram } from '../../os/registry';
import { useWindows } from '../../os/windowStore';
import {
  callResultLine, callSender, callStatusLabel, callUnknown, eventLine, eventSummary, kstShort, kstTime, LIVE_CALL, maskPhones, verdictLabel, type Label,
} from '../../shared/outreach/labels';
import { outreachApi, type Call } from '../../shared/outreach/outreachApi';
import Button from '../../shared/ui/Button';
import { activityLabel } from './thread';
import TranscriptPanel from './TranscriptPanel';

export const REDIALABLE: ReadonlySet<string> = new Set(['no_answer', 'busy', 'failed']);
export const RESULT_MAX = 2000; // 서버의 확정 결과 길이(Task 91)

export interface CallCardProps {
  c: Call;
  scheduleId: number;
  peerName: string;
  /** 이 줄에 가고 있는 요청. 있으면 단추가 모두 잠긴다. */
  busy: string | null;
  note: Label | null;
  /** 걸 수 없는 까닭(수신 거부·번호 없음 …). 있으면 [다시 걸기]가 꺼진다. */
  blocked: string | null;
  onHangup(): void;
  onRedial(): void;
  /** 확정한다. 됐으면 true(편집을 닫는다). */
  onConfirm(result: string): Promise<boolean>;
  onCancel(): void;
  onDiscard(): void;
  onOpen(): void;
  onSchedule(at: string): void;
  /** 받아쓰기를 다시 읽으며 받은 줄 */
  onRow(row: Call): void;
}

function Head({ c }: { c: Call }) {
  const who = c.status === 'draft' ? (c.origin === 'agent' ? { tag: '에이전트 초안', approver: null } : { tag: `${c.origin_name || '사용자'} 초안`, approver: null }) : callSender(c);
  const status = callStatusLabel(c);
  const at = c.started_at ?? c.created_at;
  return (
    <div className="th-meta">
      <span className={`th-who${c.origin === 'agent' ? ' is-ai' : ''}`}>{who.tag}</span>
      <span className="th-chip is-ai">AI 전화</span>
      <span className={`th-chip is-${status.tone}`}>{status.text}</span>
      <span>
        <time dateTime={at}>{kstTime(at)}</time>
        {who.approver ? ` · ${who.approver} 승인` : ''}
      </span>
    </div>
  );
}

function Answers({ c }: { c: Call }) {
  if (c.answers.length === 0) return null;
  return (
    <ul className="cl-answers" aria-label="질문별 답">
      {c.answers.map((a, i) => (
        <li key={i}>
          <span className="cl-q">{maskPhones(a.question)}</span>
          <span className="cl-a">{a.answer}</span>
          {a.quote_found && a.quote ? (
            <span className="cl-quote">{`근거 「${a.quote}」`}</span>
          ) : (
            // 근거 말이 받아쓰기(상대 말)에 없으면 사실처럼 보이지 않게
            <span className="th-chip is-warn">{a.quote ? `확인 필요 — 근거 「${a.quote}」를 받아쓰기에서 찾지 못함` : '확인 필요 — 근거 말 없음'}</span>
          )}
        </li>
      ))}
    </ul>
  );
}

function Events({ c }: { c: Call }) {
  const summary = eventSummary(c);
  if (summary === null) return null;
  return (
    <details className="th-events">
      <summary>{summary}</summary>
      <ul>
        {c.events.map((e, i) => (
          <li key={i}>
            <span className="th-verdict">{verdictLabel(e.verdict)}</span>
            {eventLine(e)}
          </li>
        ))}
      </ul>
    </details>
  );
}

function ActivityLink({ c, scheduleId }: { c: Call; scheduleId: number }) {
  if (!c.activity) return null;
  const text = activityLabel(c.activity);
  const target = c.activity.name === null ? undefined : getProgram('schedule-table');
  if (!target) return <span className="th-chip">{text}</span>;
  const params = { id: String(scheduleId), activity: c.activity.id };
  return (
    <button type="button" className="th-chip" aria-label={`${text} — ${target.name}에서 열기`} title={`${target.name}에서 열기`} onClick={() => useWindows.getState().open('schedule-table', params)}>
      {text}
    </button>
  );
}

/** [녹음 듣기]: 로그인 머리글로 받아 Blob 주소로 재생한다. 카드가 사라지면 주소를 놓는다. */
function useRecording(scheduleId: number, callId: number) {
  const [src, setSrc] = useState<string | null>(null);
  const [state, setState] = useState<'idle' | 'loading' | 'error'>('idle');
  const [error, setError] = useState<string | null>(null);
  useEffect(() => () => void (src && URL.revokeObjectURL(src)), [src]);
  const load = async () => {
    if (state === 'loading' || src) return;
    setState('loading');
    try {
      setSrc(URL.createObjectURL(await outreachApi.callRecording(scheduleId, callId)));
      setState('idle');
    } catch (e) {
      setError(e instanceof Error && e.message ? e.message : '녹음을 읽을 수 없습니다.');
      setState('error');
    }
  };
  return { src, loading: state === 'loading', error, load };
}

function ConfirmEditor({ c, locked, onConfirm, onClose }: { c: Call; locked: boolean; onConfirm(result: string): Promise<boolean>; onClose(): void }) {
  const [text, setText] = useState(c.result_confirmed ?? c.result_proposed);
  const trimmed = text.trim();
  return (
    <div className="cl-confirm">
      <textarea className="ct-input ct-textarea" aria-label="확정할 결과" maxLength={RESULT_MAX} value={text} disabled={locked} onChange={(e) => setText(e.target.value)} />
      <div className="th-acts">
        <Button disabled={locked} onClick={onClose}>취소</Button>
        <Button variant="primary" disabled={locked || trimmed === ''} onClick={() => void onConfirm(trimmed).then((ok) => ok && onClose())}>
          {locked ? '확정하는 중…' : '확정'}
        </Button>
      </div>
    </div>
  );
}

function Actions({ p, transcript, onTranscript, onRecording, recordingBusy, onEditResult }: {
  p: CallCardProps;
  transcript: boolean;
  onTranscript(): void;
  onRecording(): void;
  recordingBusy: boolean;
  onEditResult(): void;
}) {
  const { c, busy, blocked } = p;
  const locked = busy !== null;
  const live = LIVE_CALL.has(c.status);
  // 말을 주고받았을 수 있는 통화만 받아쓰기가 있다(받지 않음·통화 중·막힘·초안에는 없음).
  const talked = c.status === 'completed' || (c.status === 'failed' && c.started_at !== null);
  const buttons = [];
  if (live) buttons.push(<Button key="hang" variant="danger" disabled={locked} onClick={p.onHangup}>{busy === 'hangup' ? '끊는 중…' : '통화 끊기'}</Button>);
  if (c.status === 'draft') {
    buttons.push(<Button key="discard" disabled={locked} onClick={p.onDiscard}>버리기</Button>);
    buttons.push(<Button key="open" variant="primary" disabled={locked} onClick={p.onOpen}>전화 걸기 창 열기</Button>);
  }
  if (c.status === 'blocked_hours') {
    if (c.scheduled_at) {
      const at = c.scheduled_at;
      buttons.push(<Button key="sched" disabled={locked || blocked !== null} title={blocked ?? undefined} onClick={() => p.onSchedule(at)}>{`${kstShort(at)}에 예약`}</Button>);
    }
    buttons.push(<Button key="open" disabled={locked} onClick={p.onOpen}>전화 걸기 창 열기</Button>);
  }
  if (c.status === 'scheduled') buttons.push(<Button key="cancel" disabled={locked} onClick={p.onCancel}>예약 취소</Button>);
  if (talked && !live) buttons.push(<Button key="tr" disabled={locked} aria-expanded={transcript} onClick={onTranscript}>{transcript ? '받아쓰기 닫기' : '받아쓰기 보기'}</Button>);
  if (c.has_recording) buttons.push(<Button key="rec" disabled={locked || recordingBusy} onClick={onRecording}>{recordingBusy ? '녹음 읽는 중…' : '녹음 듣기'}</Button>);
  if (c.status === 'completed') buttons.push(<Button key="confirm" disabled={locked} onClick={onEditResult}>결과 확정</Button>);
  if (REDIALABLE.has(c.status))
    buttons.push(<Button key="redial" disabled={locked || blocked !== null} title={blocked ?? undefined} onClick={p.onRedial}>{busy === 'redial' ? '초안 만드는 중…' : '다시 걸기'}</Button>);
  return buttons.length ? <div className="th-acts">{buttons}</div> : null;
}

export default function CallCard(p: CallCardProps) {
  const { c } = p;
  const live = LIVE_CALL.has(c.status);
  const [transcript, setTranscript] = useState(live); // 걸고 있는 통화는 받아쓰기를 펼친 채로(끝나도 그대로)
  const [editing, setEditing] = useState(false);
  const rec = useRecording(p.scheduleId, c.id);
  const status = callStatusLabel(c);
  const result = callResultLine({ ...c, result_confirmed: c.result_confirmed && maskPhones(c.result_confirmed) });
  const note = p.note && p.note.text !== status.text ? p.note : null;
  const draft = c.status === 'draft';
  const cls = ['cl-card', draft && 'is-draft', c.origin === 'agent' && 'is-ai', live && 'is-live'].filter(Boolean).join(' ');
  const showTranscript = live || (transcript && c.status !== 'draft');
  return (
    <article className={cls} aria-label={`${draft ? '통화 초안' : callSender(c).tag} AI 전화 ${kstTime(c.started_at ?? c.created_at)}`}>
      <Head c={c} />
      <p className="cl-text">
        <b>목적</b>
        {maskPhones(c.purpose)}
      </p>
      {c.status === 'no_answer' && <p className="cl-small">자동으로 다시 걸지 않습니다 — 다시 걸려면 [다시 걸기]를 눌러 주세요.</p>}
      {callUnknown(c) && (
        <p className="th-why">{`${c.fail_reason ? `${c.fail_reason} · ` : ''}자동으로 다시 걸지 않습니다. 상대가 받았을 수 있으니 확인한 뒤 다시 걸어 주세요.`}</p>
      )}
      {(draft || c.status === 'blocked_hours') && c.fail_reason && <p className="th-why">{`걸지 않은 까닭: ${c.fail_reason}`}</p>}
      {c.status === 'blocked_hours' && c.scheduled_at && <p className="cl-small">{`다음 근무 시작 ${kstShort(c.scheduled_at)}`}</p>}
      {c.summary_ko && (
        <p className="cl-text">
          <b>요약</b>
          {c.summary_ko}
        </p>
      )}
      {result && <p className="cl-small">{result}</p>}
      <Answers c={c} />
      {c.activity && (
        <div className="th-meta">
          <ActivityLink c={c} scheduleId={p.scheduleId} />
        </div>
      )}
      <Events c={c} />
      {showTranscript && <TranscriptPanel scheduleId={p.scheduleId} callId={c.id} live={live} peerName={p.peerName} onRow={p.onRow} />}
      {rec.src && <audio className="cl-audio" controls src={rec.src} aria-label="통화 녹음" />}
      {rec.error && <p className="th-note is-bad">{rec.error}</p>}
      {editing && c.status === 'completed' ? (
        <ConfirmEditor c={c} locked={p.busy !== null} onConfirm={p.onConfirm} onClose={() => setEditing(false)} />
      ) : (
        <Actions p={p} transcript={showTranscript} onTranscript={() => setTranscript((t) => !t)} onRecording={() => void rec.load()} recordingBusy={rec.loading} onEditResult={() => setEditing(true)} />
      )}
      {note && (
        <p role="status" className={`th-note is-${note.tone}`}>
          {note.text}
        </p>
      )}
    </article>
  );
}
