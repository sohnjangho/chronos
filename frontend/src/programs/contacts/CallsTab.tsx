// 연락처 창의 「통화」 탭(Task 92, 시안 ②). 위: 통화가 많으면 찾기 칸 / 가운데(여기만 스크롤): 날짜 줄 아래 통화 카드(오래된 것이 위) /
// 아래: 「통화는 AI 음성 에이전트가 겁니다…」 + [전화 걸기] → 「전화 걸기」 창(CallDialog). 다른 프로그램이 넘긴 call(초안 id)이 있으면
// 그 초안으로 창을 연 채 뜬다. 목록은 15초마다, 걸고 있는 통화는 카드의 받아쓰기가 2초마다 다시 읽는다.
// 단추는 줄마다 한 번에 요청 하나(두 번 눌러도 하나) — 끝나면 목록을 다시 읽은 뒤에 잠금을 푼다. [다시 걸기]는 새 초안을 만들고(걸지 않음)
// 그 초안으로 창을 연다. 결과를 모르는 통화(「확인 필요」)의 [다시 걸기]는 먼저 묻는다 — 문이 그 번호를 잠깐 막을 수 있다.
import { Fragment, useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from 'react';
import { callStatusLabel, callUnknown, kstDay, type Label } from '../../shared/outreach/labels';
import { outreachApi, type Call } from '../../shared/outreach/outreachApi';
import Button from '../../shared/ui/Button';
import CallCard from './CallCard';
import CallDialog from './CallDialog';
import type { PersonBrief } from './contactsApi';
import type { CallsSlotProps } from './ThreadPane';
import { POLL_MS } from './useThread';
import XferDialog from './XferDialog';
import './calls.css';

export { LIVE_POLL_MS } from './TranscriptPanel';
/** 통화가 이만큼 넘으면 찾기 칸을 보인다. */
export const SEARCH_FROM = 6;
export const CALL_FOOT = '통화는 AI 음성 에이전트가 겁니다. 걸기 전에 목적과 물어볼 것을 확인합니다.';

const positiveInt = (s: string | undefined) => (s && /^\d+$/.test(s) && Number(s) > 0 ? Number(s) : null);
const errText = (e: unknown, fallback: string) => (e instanceof Error && e.message ? e.message : fallback);

/** 이 사람에게 걸 수 없는 까닭(없으면 null). 수신 거부가 먼저다. */
export function callBlocked(p: PersonBrief): string | null {
  if (p.do_not_contact) return '수신 거부한 사람에게는 걸 수 없습니다.';
  if (!p.has_phone) return '번호 없음 — 번호를 넣은 뒤에 걸 수 있습니다';
  if (p.phone_invalid) return '번호 오류 — 번호를 고친 뒤에 걸 수 있습니다';
  if (!p.channels.includes('call')) return '이 사람은 전화를 받지 않게 되어 있습니다';
  return null;
}

/** 그 사람의 통화 목록(오래된 것부터). 15초마다 다시 읽고, 늦게 온 옛 읽기는 버린다. */
function useCalls(scheduleId: number, contactId: number, root: RefObject<HTMLDivElement | null>) {
  const [calls, setCalls] = useState<Call[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const alive = useRef(true);
  const seq = useRef(0);
  const read = useRef(false); // 한 번이라도 읽었나(다시 읽기의 실패는 보이던 목록을 둔다)
  const reload = useCallback(async () => {
    const mine = ++seq.current;
    try {
      const rows = await outreachApi.listCalls(scheduleId, contactId);
      if (!alive.current || mine !== seq.current) return;
      read.current = true;
      setCalls([...rows].sort((a, b) => a.id - b.id));
      setError(null);
      setStale(false);
    } catch (e) {
      if (!alive.current || mine !== seq.current) return;
      if (read.current) setStale(true);
      else setError(errText(e, '통화 기록을 읽을 수 없습니다.'));
    }
  }, [scheduleId, contactId]);
  /** 받아쓰기·동작의 답이 준 줄로 바꾼다 — 그보다 먼저 떠난 목록 읽기는 버린다. */
  const apply = useCallback((row: Call) => {
    seq.current += 1;
    if (alive.current) setCalls((prev) => (prev ? prev.map((c) => (c.id === row.id ? row : c)) : prev));
  }, []);
  useEffect(() => {
    alive.current = true;
    void reload();
    const timer = setInterval(() => {
      if (document.visibilityState !== 'hidden' && !root.current?.closest('[hidden]')) void reload();
    }, POLL_MS);
    return () => {
      alive.current = false;
      clearInterval(timer);
    };
  }, [reload, root]);
  return { calls, error, stale, reload, apply };
}

const without = <T,>(map: Record<number, T>, id: number) => {
  const next = { ...map };
  delete next[id];
  return next;
};

/** 줄마다 한 번에 요청 하나. 끝나면 목록을 다시 읽은 뒤에 잠금을 푼다. */
function useActions(reload: () => Promise<void>, changed: () => void) {
  const [busy, setBusy] = useState<Record<number, string>>({});
  const [notes, setNotes] = useState<Record<number, Label>>({});
  const inFlight = useRef(new Set<number>());
  const run = async (id: number, verb: string, work: () => Promise<Label | void>): Promise<boolean> => {
    if (inFlight.current.has(id)) return false;
    inFlight.current.add(id);
    setBusy((b) => ({ ...b, [id]: verb }));
    setNotes((n) => without(n, id));
    let ok = true;
    try {
      const note = await work();
      if (note) setNotes((n) => ({ ...n, [id]: note }));
    } catch (e) {
      ok = false;
      setNotes((n) => ({ ...n, [id]: { text: errText(e, '요청을 처리할 수 없습니다.'), tone: 'bad' } }));
    }
    await reload();
    changed();
    inFlight.current.delete(id);
    setBusy((b) => without(b, id));
    return ok;
  };
  return { busy, notes, run };
}

/** 찾기: 목적·요약·결과·질문·답·건 사람·상태 글. */
const haystack = (c: Call) =>
  [c.purpose, c.summary_ko, c.result_proposed, c.result_confirmed ?? '', c.origin_name, callStatusLabel(c).text, ...c.questions, ...c.answers.map((a) => `${a.question} ${a.answer}`)]
    .join('\n')
    .toLowerCase();

function RedialConfirm({ onClose, onConfirm }: { onClose(): void; onConfirm(): void }) {
  return (
    <XferDialog
      title="다시 걸기 확인"
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
        <strong>이미 걸렸을 수 있습니다.</strong> 이 통화는 상대가 받았는지 확인되지 않았습니다. 다시 걸면 같은 일로 두 번 전화가 갈 수 있습니다. 계속하면 같은 내용의
        새 초안을 만들고, 「전화 걸기」 창에서 [전화 걸기]를 눌러야 걸립니다. 방금 끝난 통화라면 잠시 동안은 걸리지 않습니다.
      </p>
    </XferDialog>
  );
}

/** 만든 날(KST)이 같은 통화끼리 차례대로 묶는다. */
function byDay(calls: Call[]) {
  const groups: { day: string; items: Call[] }[] = [];
  for (const c of calls) {
    const day = kstDay(c.created_at);
    const last = groups.at(-1);
    if (last && last.day === day) last.items.push(c);
    else groups.push({ day, items: [c] });
  }
  return groups;
}

/** 가운데 스크롤 칸의 속: 읽기 실패 · 읽는 중 · 빈 목록 · 찾은 것 없음 · 날짜 줄과 카드(오래된 것이 위). */
function ListBody({ calls, shown, error, reload, card }: { calls: Call[] | null; shown: Call[]; error: string | null; reload(): void; card(c: Call): ReactNode }) {
  if (error)
    return (
      <div className="th-center">
        <p role="alert" className="ct-error">{error}</p>
        <Button onClick={reload}>다시 읽기</Button>
      </div>
    );
  if (calls === null) return <p className="ct-muted th-center">통화 기록을 읽는 중…</p>;
  if (calls.length === 0) return <p className="ct-muted th-center">아직 통화한 기록이 없습니다.</p>;
  if (shown.length === 0) return <p className="ct-muted th-center">찾는 통화가 없습니다.</p>;
  return (
    <>
      {byDay(shown).map((g) => (
        <Fragment key={g.items[0].id}>
          <h3 className="th-day">{g.day}</h3>
          {g.items.map(card)}
        </Fragment>
      ))}
    </>
  );
}

export default function CallsTab({ scheduleId, person, call, onChanged }: CallsSlotProps) {
  const root = useRef<HTMLDivElement>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const { calls, error, stale, reload, apply } = useCalls(scheduleId, person.id, root);
  const changed = useRef(onChanged);
  useEffect(() => {
    changed.current = onChanged;
  }, [onChanged]);
  const { busy, notes, run } = useActions(reload, () => changed.current());
  const [query, setQuery] = useState('');
  const [dialog, setDialog] = useState<{ id: number | null } | null>(null);
  const [ask, setAsk] = useState<Call | null>(null);
  const blocked = callBlocked(person);

  // 넘겨받은 초안(call)으로 창을 연 채 뜬다 — 같은 값을 다시 받으면 여기서는 다시 열지 않는다(Contacts 가 한 번만 넘긴다).
  useEffect(() => {
    const id = positiveInt(call);
    if (id !== null) setDialog({ id });
  }, [call]);
  useLayoutEffect(() => {
    const el = scroller.current;
    if (el && calls && stick.current) el.scrollTop = el.scrollHeight;
  }, [calls]);

  const q = query.trim().toLowerCase();
  const shown = calls && q ? calls.filter((c) => haystack(c).includes(q)) : (calls ?? []);
  const redial = (c: Call) =>
    void run(c.id, 'redial', async () => {
      const fresh = await outreachApi.redialCall(scheduleId, c.id);
      stick.current = true;
      setDialog({ id: fresh.id });
      return { text: '같은 내용의 새 초안을 만들었습니다 — 아직 걸지 않았습니다.', tone: 'info' };
    });
  const say = (text: string): Label => ({ text, tone: 'info' });
  const card = (c: Call) => (
    <CallCard
      key={c.id}
      c={c}
      scheduleId={scheduleId}
      peerName={person.name}
      busy={busy[c.id] ?? null}
      note={notes[c.id] ?? null}
      blocked={blocked}
      onHangup={() => void run(c.id, 'hangup', async () => (apply(await outreachApi.hangupCall(scheduleId, c.id)), say('끊기를 요청했습니다 — 곧 통화가 끝납니다.')))}
      onRedial={() => (callUnknown(c) ? setAsk(c) : redial(c))}
      onConfirm={(result) => run(c.id, 'confirm', async () => void apply(await outreachApi.confirmCall(scheduleId, c.id, result)))}
      onCancel={() => void run(c.id, 'cancel', async () => (apply(await outreachApi.cancelCall(scheduleId, c.id)), say('예약을 취소했습니다 — 초안으로 돌아왔습니다.')))}
      onDiscard={() => void run(c.id, 'discard', () => outreachApi.removeCall(scheduleId, c.id))}
      onOpen={() => setDialog({ id: c.id })}
      onSchedule={(at) => void run(c.id, 'schedule', async () => void apply(await outreachApi.scheduleCall(scheduleId, c.id, at)))}
      onRow={apply}
    />
  );

  return (
    <div className="th-tab" ref={root}>
      {calls && calls.length >= SEARCH_FROM && (
        <div className="cl-search">
          <input type="search" className="ct-input" aria-label="통화 찾기" placeholder="목적·요약·답 찾기" value={query} onChange={(e) => setQuery(e.target.value)} />
          {q && <span className="cl-search-count">{`${calls.length}건 중 ${shown.length}건`}</span>}
        </div>
      )}
      <div
        ref={scroller}
        className="th-scroll"
        role="log"
        aria-label="통화 기록"
        tabIndex={0}
        onScroll={(e) => {
          const el = e.currentTarget;
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
        }}
      >
        <ListBody calls={calls} shown={shown} error={error} reload={() => void reload()} card={card} />
      </div>
      {stale && <p className="th-strip is-warn" role="status">새로 읽지 못했습니다 — 마지막으로 읽은 통화 기록을 보이고 있습니다.</p>}
      <div className="th-composer cl-foot" data-slot="call-foot">
        <p className="cl-small">{blocked ?? CALL_FOOT}</p>
        <Button variant="primary" disabled={blocked !== null} title={blocked ?? undefined} onClick={() => setDialog({ id: null })}>
          전화 걸기
        </Button>
      </div>
      {dialog && (
        <CallDialog key={dialog.id ?? 'new'} scheduleId={scheduleId} person={person} callId={dialog.id} blocked={blocked} onClose={() => setDialog(null)} onChanged={() => (void reload(), changed.current())} />
      )}
      {ask && <RedialConfirm onClose={() => setAsk(null)} onConfirm={() => (setAsk(null), redial(ask))} />}
    </div>
  );
}
