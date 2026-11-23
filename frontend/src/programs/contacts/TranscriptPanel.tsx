// 통화 한 건의 받아쓰기(Task 92). 카드 안에 열리고 제 상자(.cl-tr-scroll)에서만 스크롤한다(200줄이어도 창이 늘지 않음).
// 통화하는 중(live)에는 자세히를 다시 읽어 받아쓰기를 잇고, 읽은 줄(상태·길이·요약)을 onRow 로 카드에 넘긴다. 읽기의 상한(고침 1):
// - 한 번에 하나: 다음 읽기는 앞 읽기가 끝난 뒤 LIVE_POLL_MS 를 기다려 건다(setTimeout 사슬 — 느린 서버에 요청이 쌓이지 않음).
// - 실패하면 기다림을 두 배로(2 → 4 → 8 → 16 → 30초까지), 한 번 읽히면 다시 2초.
// - 브라우저 탭이 가려지면 멈추고, 다시 보이면 곧바로 읽고 잇는다. 통화가 live 가 아니게 되거나 카드가 사라지면 멈춘다.
// - 줄에 넣은(queued) 채 QUEUED_GIVE_UP_MS 를 넘기면 멈추고 「아직 걸리지 않았습니다 — [새로 고침]」(사람이 누르면 다시 읽고 잇는다).
// 받아쓰기는 서버가 번호를 가린 글이고 늘 글로만 그린다.
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { outreachApi, type Call, type CallDetail, type TranscriptLine } from '../../shared/outreach/outreachApi';
import Button from '../../shared/ui/Button';

export const LIVE_POLL_MS = 2_000;
export const POLL_MAX_MS = 30_000;
export const QUEUED_GIVE_UP_MS = 120_000;

interface Props {
  scheduleId: number;
  callId: number;
  /** 걸고 있는 중이면 이어 읽는다. */
  live: boolean;
  /** 상대 이름(받아쓰기의 상대 줄 머리) */
  peerName: string;
  /** 다시 읽은 통화 줄(상태가 바뀌었을 수 있다) */
  onRow(row: Call): void;
}

/** 자세히에서 목록 줄만(받아쓰기·보고는 목록에 두지 않는다). */
function rowOf(d: CallDetail): Call {
  const row: Partial<CallDetail> = { ...d };
  delete row.transcript;
  delete row.reports;
  return row as Call;
}

/** 9 → 0:09, 398 → 6:38 */
const clock = (t: number) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}`;

/** 받아쓰기 읽기. read() 는 읽었으면 그 통화의 상태, 실패면 false, 이미 읽는 중이면 null(겹쳐 보내지 않는다). */
function useTranscript(scheduleId: number, callId: number, onRow: (row: Call) => void) {
  const [lines, setLines] = useState<TranscriptLine[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const alive = useRef(true);
  const busy = useRef(false);
  const report = useRef(onRow);
  useEffect(() => {
    report.current = onRow;
  }, [onRow]);
  const read = useCallback(async (): Promise<string | false | null> => {
    if (busy.current) return null;
    busy.current = true;
    try {
      const d = await outreachApi.getCall(scheduleId, callId);
      if (!alive.current) return d.status;
      setLines(d.transcript);
      setError(null);
      report.current(rowOf(d));
      return d.status;
    } catch (e) {
      if (alive.current) setError(e instanceof Error && e.message ? e.message : '받아쓰기를 읽을 수 없습니다.');
      return false;
    } finally {
      busy.current = false;
    }
  }, [scheduleId, callId]);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  return { lines, error, read };
}

/** live 인 동안의 이어 읽기(위 머리 글의 상한). stalled 면 멈춘 채로 둔다. */
function useLivePolling(live: boolean, stalled: boolean, read: () => Promise<string | false | null>, onStall: () => void) {
  useEffect(() => {
    if (!live || stalled) return;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let running = false;
    let stopped = false;
    let delay = LIVE_POLL_MS;
    let queuedSince: number | null = null;
    const schedule = () => {
      if (!stopped && timer === null && document.visibilityState !== 'hidden') timer = setTimeout(() => void tick(), delay);
    };
    const tick = async () => {
      timer = null;
      running = true;
      const got = await read();
      running = false;
      if (stopped) return;
      if (got !== null) delay = got === false ? Math.min(delay * 2, POLL_MAX_MS) : LIVE_POLL_MS;
      if (got === 'queued') {
        queuedSince ??= Date.now();
        if (Date.now() - queuedSince > QUEUED_GIVE_UP_MS) return onStall();
      } else if (got !== false && got !== null) queuedSince = null;
      schedule();
    };
    const onVisibility = () => {
      if (document.visibilityState === 'hidden') {
        if (timer !== null) clearTimeout(timer);
        timer = null;
      } else if (timer === null && !running) void tick();
    };
    void tick();
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      stopped = true;
      if (timer !== null) clearTimeout(timer);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [live, stalled, read, onStall]);
}

export default function TranscriptPanel({ scheduleId, callId, live, peerName, onRow }: Props) {
  const { lines, error, read } = useTranscript(scheduleId, callId, onRow);
  const [stalled, setStalled] = useState(false);
  const liveAtStart = useRef(live);
  const stall = useCallback(() => setStalled(true), []);
  const box = useRef<HTMLOListElement>(null);
  const stick = useRef(true); // 맨 아래를 보고 있으면 새 줄이 와도 맨 아래에

  // 걸고 있지 않은 통화는 한 번만 읽는다(걸고 있으면 이어 읽기가 곧바로 읽는다).
  useEffect(() => {
    if (!liveAtStart.current) void read();
  }, [read]);
  useLivePolling(live, stalled, read, stall);
  useLayoutEffect(() => {
    if (box.current && stick.current) box.current.scrollTop = box.current.scrollHeight;
  }, [lines]);

  return (
    <div className="cl-tr">
      <p className="cl-tr-head">{live && !stalled ? '받아쓰기 — 통화하는 동안 이어집니다' : '받아쓰기'}</p>
      {live && stalled && (
        <p className="th-note is-warn cl-stall">
          아직 걸리지 않았습니다 —{' '}
          <Button onClick={() => setStalled(false)}>새로 고침</Button>
        </p>
      )}
      {error && lines === null && (
        <p role="alert" className="ct-error">
          {error}
        </p>
      )}
      {lines === null && !error && <p className="ct-muted cl-small">받아쓰기를 읽는 중…</p>}
      {lines !== null && lines.length === 0 && <p className="ct-muted cl-small">{live ? '아직 받아 적은 말이 없습니다.' : '받아 적은 말이 없습니다.'}</p>}
      {lines !== null && lines.length > 0 && (
        <ol
          ref={box}
          className="cl-tr-scroll"
          role="log"
          aria-label="받아쓰기"
          tabIndex={0}
          onScroll={(e) => {
            const el = e.currentTarget;
            stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 32;
          }}
        >
          {lines.map((l, i) => (
            <li key={i}>
              <span className={`cl-tr-who${l.role === 'agent' ? ' is-ai' : ''}`}>{l.role === 'agent' ? 'AI' : peerName}</span>
              <span className="cl-tr-t">{l.t === null ? '' : clock(l.t)}</span>
              <span className="cl-tr-text">{l.text}</span>
            </li>
          ))}
        </ol>
      )}
      {error && lines !== null && <p className="th-note is-warn">새로 읽지 못했습니다 — 마지막으로 읽은 받아쓰기를 보이고 있습니다.</p>}
    </div>
  );
}
