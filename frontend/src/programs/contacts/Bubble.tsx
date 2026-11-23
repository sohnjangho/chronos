// 말풍선 한 건(시안 ①). 위: 누가 보냈나·채널·시각 / 가운데: 글(늘 글로만 — 받은 글의 링크·태그를 살리지 않는다)·번역 /
// 아래: 상태·연결된 작업·사건 접힌 줄·단추. 초안은 점선 말풍선에 [버리기][고치기][보내기], 예약은 [취소], 실패·확인 필요는 [다시 보내기].
// 상태는 서버가 준 줄에서만 읽는다 — 누른 뒤의 모습은 다시 읽은 줄이 정한다.
import { useState } from 'react';
import { getProgram } from '../../os/registry';
import { useWindows } from '../../os/windowStore';
import { channelLabel, eventLine, eventSummary, kstShort, kstTime, senderTag, statusLabel, verdictLabel, type Label } from '../../shared/outreach/labels';
import { batchLine } from '../../shared/outreach/BatchSendDialog';
import type { Message } from '../../shared/outreach/outreachApi';
import Button from '../../shared/ui/Button';
import { activityLabel, draftLine, replyLine } from './thread';

export const BODY_MAX = 1000; // 서버의 본문 길이(Task 73)

export interface BubbleProps {
  m: Message;
  /** 지금 읽어 둔 줄 전부(답한 줄을 찾는다) */
  all: Message[];
  scheduleId: number;
  /** 이 줄에 가고 있는 요청('send' 등). 있으면 단추가 모두 잠긴다. */
  busy: string | null;
  /** 방금 한 일의 결과 글 */
  note: Label | null;
  /** 보낼 수 없는 까닭(수신 거부). 있으면 [보내기]·[다시 보내기]가 꺼진다. */
  blocked: string | null;
  onSend(): void;
  onDiscard(): void;
  /** 고친 글을 저장한다. 됐으면 true(고치기를 닫는다). */
  onSave(body: string): Promise<boolean>;
  onCancel(): void;
  onResend(): void;
}

function Links({ m, scheduleId }: { m: Message; scheduleId: number }) {
  const sid = String(scheduleId);
  const links: { text: string; program: string | null; params: Record<string, string> }[] = [];
  // 지금 일정에 없는 작업은 열 곳이 없다 — 글로만.
  if (m.activity) links.push({ text: activityLabel(m.activity), program: m.activity.name === null ? null : 'schedule-table', params: { id: sid, activity: m.activity.id } });
  if (m.field_item_id !== null) links.push({ text: `현장 항목 #${m.field_item_id}`, program: 'progress', params: { id: sid, view: 'field' } });
  if (m.approval_id !== null) links.push({ text: `승인 #${m.approval_id}`, program: 'approvals', params: { id: String(m.approval_id) } });
  return (
    <>
      {links.map((l) => {
        const target = l.program ? getProgram(l.program) : undefined;
        if (!l.program || !target) return <span key={l.text} className="th-chip">{l.text}</span>;
        const program = l.program;
        return (
          <button key={l.text} type="button" className="th-chip" aria-label={`${l.text} — ${target.name}에서 열기`} title={`${target.name}에서 열기`} onClick={() => useWindows.getState().open(program, l.params)}>
            {l.text}
          </button>
        );
      })}
    </>
  );
}

function Events({ m }: { m: Message }) {
  const summary = eventSummary(m);
  if (summary === null) return null;
  return (
    <details className="th-events">
      <summary>{summary}</summary>
      <ul>
        {m.events.map((e, i) => (
          <li key={i}>
            <span className="th-verdict">{verdictLabel(e.verdict)}</span>
            {eventLine(e)}
          </li>
        ))}
      </ul>
    </details>
  );
}

function Actions({ p, editing, onEdit, onStopEdit, onSaveEdit, canSave }: { p: BubbleProps; editing: boolean; onEdit(): void; onStopEdit(): void; onSaveEdit(): void; canSave: boolean }) {
  const { m, busy, blocked } = p;
  const locked = busy !== null;
  const why = blocked ?? undefined;
  if (m.status === 'draft' && editing)
    return (
      <div className="th-acts">
        <Button disabled={locked} onClick={onStopEdit}>고치기 취소</Button>
        <Button variant="primary" disabled={locked || !canSave} onClick={onSaveEdit}>저장</Button>
      </div>
    );
  if (m.status === 'draft')
    return (
      <div className="th-acts">
        <Button disabled={locked} onClick={p.onDiscard}>버리기</Button>
        <Button disabled={locked} onClick={onEdit}>고치기</Button>
        <Button variant="primary" disabled={locked || blocked !== null} title={why} onClick={p.onSend}>{busy === 'send' ? '보내는 중…' : '보내기'}</Button>
      </div>
    );
  if (m.status === 'scheduled')
    return (
      <div className="th-acts">
        <Button disabled={locked} onClick={p.onCancel}>취소</Button>
      </div>
    );
  if (m.status === 'failed' || m.status === 'unconfirmed')
    return (
      <div className="th-acts">
        <Button disabled={locked || blocked !== null} title={why} onClick={p.onResend}>다시 보내기</Button>
      </div>
    );
  return null;
}

/** 아래 줄: 상태(보낸 줄만)·늦게 나간 시각·여러 명에게 보낸 묶음(「묶음 #31 · 3명 중 2명 회신」)·연결된 작업. 보일 것이 없으면 줄도 없다. */
function Foot({ m, scheduleId, status }: { m: Message; scheduleId: number; status: Label }) {
  const sentLater = m.sent_at !== null && Math.abs(new Date(m.sent_at).getTime() - new Date(m.created_at).getTime()) >= 60_000;
  const showStatus = m.direction === 'out' && m.status !== 'draft';
  if (!showStatus && !m.batch && !m.activity && m.field_item_id === null && m.approval_id === null) return null;
  return (
    <div className="th-meta">
      {showStatus && <span className={`th-chip is-${status.tone}`}>{status.text}</span>}
      {showStatus && sentLater && m.sent_at && <span>{`${kstShort(m.sent_at)} 보냄`}</span>}
      {m.batch && <span className="th-chip">{batchLine(m.batch)}</span>}
      <Links m={m} scheduleId={scheduleId} />
    </div>
  );
}

export default function Bubble(p: BubbleProps) {
  const { m } = p;
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState('');
  const status = statusLabel(m);
  const draft = m.status === 'draft';
  const agent = m.origin === 'agent';
  const who = draft ? (agent ? '에이전트 초안' : `${m.origin_name || '사용자'} 초안`) : senderTag(m);
  const reply = replyLine(m, p.all);
  // 상태 이름표가 이미 같은 말을 하면 결과 글을 한 번 더 적지 않는다.
  const note = p.note && p.note.text !== status.text ? p.note : null;
  const cls = ['th-b', m.direction === 'out' ? 'is-me' : 'is-them', agent && 'is-ai', draft && 'is-draft'].filter(Boolean).join(' ');
  const trimmed = text.trim();
  const save = async () => {
    if (await p.onSave(trimmed)) setEditing(false);
  };
  return (
    <article className={cls} aria-label={`${who} ${channelLabel(m.channel)} ${kstTime(m.created_at)}`}>
      <div className="th-meta">
        <span className={`th-who${agent ? ' is-ai' : ''}`}>{who}</span>
        <span className={`th-chip${m.channel === 'kakao' ? ' is-kakao' : ''}`}>{channelLabel(m.channel)}</span>
        {draft ? <span>{draftLine(m, status.text)}</span> : <time dateTime={m.created_at}>{kstTime(m.created_at)}</time>}
      </div>
      {reply && <p className="th-reply">{reply}</p>}
      {draft && editing ? (
        <textarea className="ct-input ct-textarea th-edit" aria-label="초안 고치기" maxLength={BODY_MAX} value={text} disabled={p.busy !== null} onChange={(e) => setText(e.target.value)} />
      ) : (
        <p className="th-bub">{m.body}</p>
      )}
      {m.body_ko && (
        <p className="th-ko">
          <span className="th-ko-tag">번역</span>
          {m.body_ko}
        </p>
      )}
      {draft && m.fail_reason && !note && <p className="th-why">{`보내지 않은 까닭: ${m.fail_reason}`}</p>}
      <Foot m={m} scheduleId={p.scheduleId} status={status} />
      <Events m={m} />
      <Actions
        p={p}
        editing={editing}
        canSave={trimmed !== '' && trimmed !== m.body}
        onEdit={() => {
          setText(m.body);
          setEditing(true);
        }}
        onStopEdit={() => setEditing(false)}
        onSaveEdit={() => void save()}
      />
      {note && <p role="status" className={`th-note is-${note.tone}`}>{note.text}</p>}
    </article>
  );
}
