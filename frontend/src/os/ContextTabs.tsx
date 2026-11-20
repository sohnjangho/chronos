import { useEffect, useState, type FormEvent } from 'react';
import { api } from '../shared/api';
import Button from '../shared/ui/Button';
import { useAiChat } from './aiChat';
import { ageText } from './ApprovalWidget';
import type { ContextSource } from './contextStore';
import type { EvidenceItem } from './evidence';
import { useWindows } from './windowStore';

/** 「AI」: 출처 창의 맥락(프로그램·일정·보낼 때 고른 액티비티)으로 묻는 작은 대화. 대화는 패널 밖(useAiChat)에 있어
 * 탭을 바꾸거나 패널을 닫아도 이어진다. 「전체 화면으로」는 같은 대화를 대화 프로그램에서 연다. */
export function AiTab({ source, stale }: { source: ContextSource | null; stale: boolean }) {
  const { lines, busy, sessionId } = useAiChat();
  const [text, setText] = useState('');

  function send(e: FormEvent) {
    e.preventDefault();
    const ask = text.trim();
    if (!ask || busy || !source) return;
    setText('');
    void useAiChat.getState().ask(ask, source);
  }

  function fullScreen() {
    const id = useWindows.getState().open('chat', { session: String(sessionId) });
    if (!useWindows.getState().wins.find((x) => x.id === id)?.maximized) useWindows.getState().toggleMaximize(id);
  }

  return (
    <div className="os-ctx-ai">
      <div className="os-ctx-lines">
        {lines.length === 0 && <p className="os-ctx-empty">이 창에 대해 에이전트에게 물어보세요.</p>}
        {lines.map((l, i) => (
          <p key={i} className={`os-ctx-line is-${l.who}`}>
            {l.text}
          </p>
        ))}
        {busy && <p className="os-ctx-empty">답을 기다리는 중…</p>}
      </div>
      <form className="os-ctx-ask" onSubmit={send}>
        <input aria-label="에이전트에게 묻기" placeholder="에이전트에게 묻기" value={text} disabled={stale || !source} onChange={(e) => setText(e.target.value)} />
        <Button type="submit" variant="primary" disabled={busy || stale || !source}>
          보내기
        </Button>
      </form>
      <Button className="os-ctx-full" disabled={sessionId === null} onClick={fullScreen}>
        전체 화면으로
      </Button>
    </div>
  );
}

/** 「근거」: 출처가 넘긴 근거 줄. 없으면 빈 상태 글. */
export function EvidenceTab({ items }: { items: EvidenceItem[] }) {
  if (!items.length) return <p className="os-ctx-empty">이 창이 넘긴 근거가 없습니다.</p>;
  return (
    <dl className="os-ctx-evidence">
      {items.map((it) => (
        <div key={it.label} className="os-ctx-row">
          <dt>{it.label}</dt>
          <dd>
            {it.value}
            {it.detail && <span className="os-ctx-detail">{it.detail}</span>}
          </dd>
        </div>
      ))}
    </dl>
  );
}

interface Pending {
  id: number;
  title: string;
  created_at: string;
  schedule_id: number | null;
}
interface Run {
  id: number;
  chat_session_id: number | null;
  title: string;
  status: string;
  started_at: string;
}
const RUN_STATUS: Record<string, string> = { running: '실행 중', done: '끝남', failed: '실패', stopped: '멈춤' };

/** 「활동」: 지금 일정의 승인 대기 카드와 최근 워크플로우 실행(그 일정 대화의 실행만). */
export function ActivityTab({ scheduleId }: { scheduleId: number | null }) {
  const [pending, setPending] = useState<Pending[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  useEffect(() => {
    if (scheduleId === null) return;
    api<{ items: Pending[] }>('/api/approvals?status=pending').then((r) => setPending(r.items.filter((a) => a.schedule_id === scheduleId)), () => {});
    Promise.all([api<{ id: number; schedule_id: number | null }[]>('/api/chat/sessions'), api<Run[]>('/api/workflows/runs')]).then(
      ([sessions, all]) => {
        const mine = new Set(sessions.filter((s) => s.schedule_id === scheduleId).map((s) => s.id));
        setRuns(all.filter((r) => r.chat_session_id !== null && mine.has(r.chat_session_id)).slice(0, 5));
      },
      () => {},
    );
  }, [scheduleId]);
  if (scheduleId === null) return <p className="os-ctx-empty">현장을 고르면 이 일정의 활동이 보입니다.</p>;
  const open = useWindows.getState().open;
  return (
    <div className="os-ctx-activity">
      <h3 className="os-ctx-h">승인 대기 {pending.length}</h3>
      {pending.length === 0 && <p className="os-ctx-empty">이 일정의 승인 대기가 없습니다.</p>}
      {pending.map((a) => (
        <button key={a.id} type="button" className="os-ctx-card" onClick={() => open('approvals', { id: String(a.id) })}>
          <span className="os-ctx-card-title">{a.title}</span>
          <span className="os-ctx-detail">{ageText(a.created_at)}</span>
        </button>
      ))}
      <h3 className="os-ctx-h">최근 실행</h3>
      {runs.length === 0 && <p className="os-ctx-empty">최근 실행이 없습니다.</p>}
      <ol className="os-ctx-timeline">
        {runs.map((r) => (
          <li key={r.id}>
            <span className="os-ctx-card-title">{r.title}</span>
            <span className="os-ctx-detail">
              {RUN_STATUS[r.status] ?? r.status} · {ageText(r.started_at)}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}
