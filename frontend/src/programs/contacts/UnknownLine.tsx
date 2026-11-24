// 「모르는 번호 · 대표번호」 칸의 줄 하나(Task 85 · 96): 문자는 대화 칸과 같은 상태 글, 통화는 통화 탭과 같은 상태 글·등급 칩·
// 받지 않은(못한) 까닭·붉은 사건 줄(labels). 처리 기록(기계 출력)은 접어 둔다.
import { callerClassLabel, callStatusLabel, eventLine, inboundWhy, kstShort, redFlags, statusLabel } from '../../shared/outreach/labels';
import type { Message } from '../../shared/outreach/outreachApi';
import type { PeerLine } from './UnknownPeers';

export default function PeerLineItem({ l }: { l: PeerLine }) {
  const isCall = l.kind === 'call';
  const head = `${l.direction === 'out' ? (isCall ? '건 전화' : '보낸 문자') : isCall ? '받은 전화' : '받은 문자'}`;
  // 문자 상태는 대화 칸과 같은 글(labels.statusLabel), 통화는 통화 탭과 같은 글·등급 칩·까닭(Task 96) — 그 함수가 읽는 칸만 넘긴다.
  // 받지 않은(못한) 통화는 「요약 없음」 대신 까닭(서버 글, 없으면 판정 글).
  const flags = redFlags(l.events);
  const untaken = isCall && (l.status === 'rejected' || l.status === 'missed');
  const why = untaken ? inboundWhy(l) : null;
  const cls = isCall && l.direction === 'in' ? callerClassLabel(l.caller_class) : null;
  const status = isCall
    ? callStatusLabel({ ...l, scheduled_at: null } as unknown as Parameters<typeof callStatusLabel>[0]).text
    : statusLabel({ ...l, scheduled_at: null, fallback_sms: false } as unknown as Message).text;
  return (
    <li className={`ct-ib-line${l.direction === 'out' ? ' is-out' : ''}`}>
      <div className="ct-ib-meta">
        <span className="ct-tag">{head}</span>
        {cls && <span className="ct-tag">{cls}</span>}
        {l.message_kind === 'notice' && <span className="ct-tag">고정 안내</span>}
        {l.message_kind === 'auto_reply' && <span className="ct-tag">자동 답</span>}
        <span>{kstShort(l.at)}</span>
        <span>{status}</span>
      </div>
      {l.text ? <p className="ct-ib-text">{l.text}</p> : !untaken && <p className="ct-muted">{isCall ? '요약 없음' : '글 없음'}</p>}
      {why && <p className="ct-muted">{`${l.status === 'missed' ? '받지 못한' : '받지 않은'} 까닭: ${why}`}</p>}
      {flags.length > 0 && (
        <div className="ct-ib-meta" role="group" aria-label="확인할 사건">
          {flags.map((f) => <span key={f} className="ct-tag is-bad">{f}</span>)}
        </div>
      )}
      {l.events.length > 0 && (
        <details className="ct-ib-events">
          <summary>{`처리 기록 ${l.events.length}건`}</summary>
          <ul>
            {l.events.map((e, i) => (
              <li key={i}>{eventLine(e)}</li>
            ))}
          </ul>
        </details>
      )}
    </li>
  );
}
