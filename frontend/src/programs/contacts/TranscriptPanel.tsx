// 통화 한 건의 받아쓰기(Task 92). 카드 안에 열리고 제 상자(.cl-tr-scroll)에서만 스크롤한다(200줄이어도 창이 늘지 않음).
// 통화하는 중(live)에는 LIVE_POLL_MS 마다 자세히를 다시 읽어 받아쓰기를 잇고, 읽은 줄(상태·길이·요약)을 onRow 로 카드에 넘긴다 —
// 통화가 끝나면(onRow 의 줄이 더는 live 가 아니면) 읽기를 멈춘다. 받아쓰기는 서버가 번호를 가린 글이고 늘 글로만 그린다.
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { outreachApi, type Call, type CallDetail, type TranscriptLine } from '../../shared/outreach/outreachApi';

export const LIVE_POLL_MS = 2_000;

interface Props {
  scheduleId: number;
  callId: number;
  /** 걸고 있는 중이면 2초마다 다시 읽는다. */
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

export default function TranscriptPanel({ scheduleId, callId, live, peerName, onRow }: Props) {
  const [lines, setLines] = useState<TranscriptLine[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const box = useRef<HTMLOListElement>(null);
  const stick = useRef(true); // 맨 아래를 보고 있으면 새 줄이 와도 맨 아래에
  const alive = useRef(true);
  const seq = useRef(0);
  const report = useRef(onRow);
  useEffect(() => {
    report.current = onRow;
  }, [onRow]);

  const read = useCallback(async () => {
    const mine = ++seq.current;
    try {
      const d: CallDetail = await outreachApi.getCall(scheduleId, callId);
      if (!alive.current || mine !== seq.current) return; // 더 늦게 떠난 읽기가 있으면 이 답은 버린다
      setLines(d.transcript);
      setError(null);
      report.current(rowOf(d));
    } catch (e) {
      if (alive.current && mine === seq.current) setError(e instanceof Error && e.message ? e.message : '받아쓰기를 읽을 수 없습니다.');
    }
  }, [scheduleId, callId]);

  useEffect(() => {
    alive.current = true;
    void read();
    return () => {
      alive.current = false;
    };
  }, [read]);
  useEffect(() => {
    if (!live) return;
    const timer = setInterval(() => void read(), LIVE_POLL_MS);
    return () => clearInterval(timer);
  }, [live, read]);
  useLayoutEffect(() => {
    if (box.current && stick.current) box.current.scrollTop = box.current.scrollHeight;
  }, [lines]);

  return (
    <div className="cl-tr">
      <p className="cl-tr-head">{live ? '받아쓰기 — 통화하는 동안 2초마다 이어집니다' : '받아쓰기'}</p>
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
