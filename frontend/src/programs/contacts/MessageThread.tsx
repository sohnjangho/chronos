// 한 사람과의 문자·카카오톡 대화(시안 ①): 날짜 줄 아래 말풍선, 맨 위 「이전 대화 더 보기」, 여기만 세로로 스크롤한다.
// 단추를 누르면 그 줄의 단추는 답이 오고 대화를 다시 읽을 때까지 잠긴다(두 번 눌러도 요청은 하나). 결과는 서버가 준 판정 글을 그 줄 아래에
// 적고, 줄의 상태는 다시 읽은 것으로 그린다 — 「보냄」을 미리 그리지 않는다. 「확인 필요」 줄의 [다시 보내기]는 먼저 묻는다.
import { Fragment, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { outcomeLabel, SEND_UNKNOWN, type Label } from '../../shared/outreach/labels';
import { outreachApi, sendOutcomeUnknown, type Message } from '../../shared/outreach/outreachApi';
import Button from '../../shared/ui/Button';
import Bubble from './Bubble';
import { groupByDay } from './thread';
import type { ThreadHandle } from './useThread';
import XferDialog from './XferDialog';
import './thread.css';

interface Props {
  scheduleId: number;
  thread: ThreadHandle;
  /** 보낼 수 없는 까닭(수신 거부) — 있으면 보내는 단추가 꺼진다. */
  blocked: string | null;
}

const NEW_DRAFT = '새 초안을 만들었습니다 — 아직 보내지 않았습니다. [보내기]를 눌러야 나갑니다.';
/** [보내기] 요청이 답을 받지 못함 — 나갔는지 모른다. 글은 labels.ts 에 있다(대화 카드도 쓴다). */
export { SEND_UNKNOWN };
type Done = { on: number; note: Label } | void;

/** 줄마다 한 번에 요청 하나. 끝나면 대화를 다시 읽은 뒤에 잠금을 푼다. */
function useActions(reload: () => Promise<void>) {
  const [busy, setBusy] = useState<Record<number, string>>({});
  const [notes, setNotes] = useState<Record<number, Label>>({});
  const inFlight = useRef(new Set<number>());
  const without = <T,>(map: Record<number, T>, id: number) => {
    const next = { ...map };
    delete next[id];
    return next;
  };
  const run = async (id: number, verb: string, work: () => Promise<Done>): Promise<boolean> => {
    if (inFlight.current.has(id)) return false;
    inFlight.current.add(id);
    setBusy((b) => ({ ...b, [id]: verb }));
    setNotes((n) => without(n, id));
    let ok = true;
    try {
      const done = await work();
      if (done) setNotes((n) => ({ ...n, [done.on]: done.note }));
    } catch (e) {
      ok = false;
      setNotes((n) => ({ ...n, [id]: { text: e instanceof Error && e.message ? e.message : '요청을 처리할 수 없습니다.', tone: 'bad' } }));
    }
    await reload();
    inFlight.current.delete(id);
    setBusy((b) => without(b, id));
    return ok;
  };
  return { busy, notes, run };
}

/** 스크롤 칸의 속: 읽기 실패 · 읽는 중 · 빈 대화 · 날짜 줄과 말풍선(맨 위에 「이전 대화 더 보기」). */
function Rows({ thread, onOlder, bubble }: { thread: ThreadHandle; onOlder(): void; bubble(m: Message, all: Message[]): ReactNode }) {
  const { messages } = thread;
  if (thread.error)
    return (
      <div className="th-center">
        <p role="alert" className="ct-error">{thread.error}</p>
        <Button onClick={() => void thread.reload()}>다시 읽기</Button>
      </div>
    );
  if (messages === null) return <p className="ct-muted th-center">대화를 읽는 중…</p>;
  if (messages.length === 0) return <p className="ct-muted th-center">아직 주고받은 문자가 없습니다.</p>;
  return (
    <>
      {thread.hasMore && (
        <div className="th-older">
          <Button disabled={thread.loadingOlder} onClick={onOlder}>{thread.loadingOlder ? '읽는 중…' : '이전 대화 더 보기'}</Button>
          {thread.olderError && <p role="alert" className="ct-error">{thread.olderError}</p>}
        </div>
      )}
      {groupByDay(messages).map((g) => (
        <Fragment key={g.items[0].id}>
          <h3 className="th-day">{g.day}</h3>
          {g.items.map((m) => bubble(m, messages))}
        </Fragment>
      ))}
    </>
  );
}

/** 「확인 필요」 줄을 다시 보내기 전에 묻는다 — 이미 나갔을 수 있다. 초점은 [취소]에서 시작한다. */
function ResendConfirm({ onClose, onConfirm }: { onClose(): void; onConfirm(): void }) {
  return (
    <XferDialog
      title="다시 보내기 확인"
      busy={false}
      onClose={onClose}
      foot={
        <>
          <Button onClick={onClose}>취소</Button>
          <Button variant="primary" onClick={onConfirm}>새 초안 만들기</Button>
        </>
      }
    >
      <p className="ct-xfer-top th-dialog-text">
        <strong>이미 나갔을 수 있습니다.</strong> 이 글은 보냈는지 확인되지 않았습니다. 다시 보내면 상대가 같은 글을 두 번 받을 수 있습니다. 계속하면 같은 글의 새 초안을
        만들고, 그 초안에서 [보내기]를 눌러야 나갑니다.
      </p>
    </XferDialog>
  );
}

export default function MessageThread({ scheduleId, thread, blocked }: Props) {
  const { messages } = thread;
  const scroller = useRef<HTMLDivElement>(null);
  const stick = useRef(true); // 맨 아래를 보고 있었으면 새 줄이 와도 맨 아래에 둔다
  const anchor = useRef<number | null>(null); // 「이전 대화 더 보기」를 누른 때의 아래쪽까지 거리
  const firstId = useRef<number | null>(null);
  const { busy, notes, run } = useActions(thread.reload);
  const [confirm, setConfirm] = useState<Message | null>(null);

  useLayoutEffect(() => {
    const el = scroller.current;
    if (!el || !messages) return;
    const first = messages[0]?.id ?? null;
    if (anchor.current !== null && first !== firstId.current) {
      el.scrollTop = el.scrollHeight - anchor.current; // 앞에 줄이 붙어도 보던 자리 그대로
      anchor.current = null;
    } else if (stick.current) el.scrollTop = el.scrollHeight;
    firstId.current = first;
  }, [messages, notes]);

  const older = () => {
    const el = scroller.current;
    if (!el || !messages?.length) return;
    anchor.current = el.scrollHeight - el.scrollTop;
    void thread.loadOlder(messages[0].id);
  };
  const resend = (m: Message) =>
    void run(m.id, 'resend', async () => {
      const r = await outreachApi.resend(scheduleId, m.id);
      stick.current = true; // 새 초안은 맨 아래에 생긴다
      return { on: r.message.id, note: { text: r.warning ? `${r.warning} · ${NEW_DRAFT}` : NEW_DRAFT, tone: r.warning ? 'warn' : 'info' } };
    });
  const bubble = (m: Message, all: Message[]) => (
    <Bubble
      key={m.id}
      m={m}
      all={all}
      scheduleId={scheduleId}
      busy={busy[m.id] ?? null}
      note={notes[m.id] ?? null}
      blocked={blocked}
      onSend={() =>
        void run(m.id, 'send', async () => {
          let r;
          try {
            r = await outreachApi.send(scheduleId, m.id);
          } catch (e) {
            // 답이 오지 않았다: 서버가 받아 보냈을 수도 있다 — 「실패」가 아니라 「모름」, 다시 읽은 줄이 상태를 말한다.
            if (sendOutcomeUnknown(e)) return { on: m.id, note: { text: SEND_UNKNOWN, tone: 'warn' } };
            throw e;
          }
          thread.apply(r.message);
          return r.outcome ? { on: m.id, note: outcomeLabel(r.outcome) } : undefined;
        })
      }
      onDiscard={() =>
        void run(m.id, 'discard', async () => {
          await outreachApi.remove(scheduleId, m.id);
          thread.drop(m.id);
        })
      }
      onSave={(body) => run(m.id, 'save', async () => void thread.apply(await outreachApi.patch(scheduleId, m.id, { body })))}
      onCancel={() =>
        void run(m.id, 'cancel', async () => {
          thread.apply(await outreachApi.cancel(scheduleId, m.id));
          return { on: m.id, note: { text: '예약을 취소했습니다 — 초안으로 돌아왔습니다.', tone: 'info' } };
        })
      }
      onResend={() => (m.status === 'unconfirmed' ? setConfirm(m) : resend(m))}
    />
  );

  return (
    <>
      <div
        ref={scroller}
        className="th-scroll"
        role="log"
        aria-label="문자 · 카카오톡 대화"
        tabIndex={0}
        onScroll={(e) => {
          const el = e.currentTarget;
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
        }}
      >
        <Rows thread={thread} onOlder={older} bubble={bubble} />
      </div>
      {thread.stale && (
        <p className="th-strip is-warn" role="status">새로 읽지 못했습니다 — 마지막으로 읽은 대화를 보이고 있습니다.</p>
      )}
      {confirm && (
        <ResendConfirm
          onClose={() => setConfirm(null)}
          onConfirm={() => {
            setConfirm(null);
            resend(confirm);
          }}
        />
      )}
    </>
  );
}
