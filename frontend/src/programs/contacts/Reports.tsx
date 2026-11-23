// 「확인할 보고」(Task 85): 문자·전화로 받은 보고(지연·문제·변경 요청·메모·긴급)와 뒤 확인에 걸린 답(「내용 확인 필요」).
// 이 프로젝트의 보고와 일정 없는 보고(모르는 번호)를 함께 보이되 길은 따로다. 글은 서버가 번호를 가려 준 그대로 — 화면은 풀지 않는다.
// [확인함] = 보고를 읽었다는 표시(일정은 바뀌지 않는다), [지연 기록 만들기] = 대화 창에 그 보고로 지연 기록을 만들어 달라고 묻는다.
import { useCallback, useEffect, useState } from 'react';
import { useWindows } from '../../os/windowStore';
import { api, ApiError } from '../../shared/api';
import { kstShort } from '../../shared/outreach/labels';
import Button from '../../shared/ui/Button';
import './inbound.css';

export interface Report {
  id: number;
  /** null = 일정 없는 보고(모르는 번호에서) */
  schedule_id: number | null;
  medium: 'sms' | 'call';
  kind: string;
  text: string;
  quote: string;
  quote_found: boolean;
  status: 'open' | 'reviewed';
  contact_id: number | null;
  contact_name: string | null;
  peer_masked: string | null;
  peer_key: string | null;
  message_id: number | null;
  call_id: number | null;
  /** kind review: 뒤 확인에 걸려 남은 답 초안 */
  draft_id: number | null;
  created_at: string;
  reviewed_by: string | null;
  reviewed_at: string | null;
}

/** 보고 종류(서버 contact_reports.kind). 차례 = 화면의 묶음 차례(긴급 먼저). */
export const REPORT_KIND: Readonly<Record<string, string>> = {
  emergency: '긴급', review: '내용 확인 필요', change_request: '일정 변경 요청', delay: '지연', problem: '문제', message: '메모', other: '그 밖',
};
export const mediumLabel = (m: string) => (m === 'call' ? '전화로 받은 보고' : '문자로 받은 보고');
const kindLabel = (k: string) => REPORT_KIND[k] ?? k;

export const getReports = (sid: number) => api<Report[]>(`/api/schedules/${sid}/outreach/reports?status=open`);
export const getLooseReports = () => api<Report[]>('/api/outreach/reports?unassigned=1&status=open');
/** 일정 없는 보고는 일정 없는 길로, 이 프로젝트의 보고는 이 프로젝트의 길로. */
export const reviewReport = (sid: number, r: Report) =>
  api<Report>(r.schedule_id === null ? `/api/outreach/reports/${r.id}/review` : `/api/schedules/${sid}/outreach/reports/${r.id}/review`, { method: 'POST' });

const list = (r: unknown): Report[] => (Array.isArray(r) ? (r as Report[]) : []);

/** 이 프로젝트의 보고 + 일정 없는 보고(확인하지 않은 것). 읽지 못하면 빈 목록. */
export function useReports(sid: number) {
  const [items, setItems] = useState<Report[]>([]);
  const [n, setN] = useState(0);
  useEffect(() => {
    let live = true;
    Promise.all([getReports(sid).then(list, () => []), getLooseReports().then(list, () => [])]).then(([mine, loose]) => live && setItems([...mine, ...loose]));
    return () => {
      live = false;
    };
  }, [sid, n]);
  return { items, reload: useCallback(() => setN((x) => x + 1), []) };
}

const who = (r: Report) => r.contact_name ?? (r.peer_masked ? `모르는 번호 ${r.peer_masked}` : '모르는 번호');

/** 대화 창에 보낼 부탁 — 번호는 넣지 않는다(가린 꼴도). 글은 서버가 이미 가렸다. */
export function delayAsk(r: Report): string {
  const from = r.contact_name ?? '모르는 번호';
  const heard = r.quote ? ` 들은 말: 「${r.quote}」.` : '';
  return `${from}이(가) ${r.medium === 'call' ? '전화로' : '문자로'} 알린 ${kindLabel(r.kind)} 보고로 지연 기록을 만들어 주세요. 일정은 바꾸지 말고 기록만 남겨 주세요. 내용: 「${r.text}」.${heard}`;
}

interface CardProps {
  r: Report;
  busy: boolean;
  onReview: (r: Report) => void;
  onOpenPerson: (id: number, tab: 'messages' | 'calls') => void;
  onOpenPeer: (key: string) => void;
}

function Card({ r, busy, onReview, onOpenPerson, onOpenPeer }: CardProps) {
  const review = r.kind === 'review';
  const open = () => (r.contact_id !== null ? onOpenPerson(r.contact_id, r.medium === 'call' ? 'calls' : 'messages') : r.peer_key && onOpenPeer(r.peer_key));
  const canOpen = r.contact_id !== null || r.peer_key !== null;
  return (
    <article className={`ct-ib-card${r.kind === 'emergency' ? ' is-urgent' : ''}${review ? ' is-review' : ''}`} aria-label={`${kindLabel(r.kind)} — ${r.text}`}>
      <div className="ct-ib-meta">
        <span className="ct-tag">{mediumLabel(r.medium)}</span>
        <span className={`ct-tag${r.kind === 'emergency' ? ' is-bad' : review ? ' is-warn' : ''}`}>{kindLabel(r.kind)}</span>
        <span className="ct-ellipsis">{who(r)}</span>
        {r.schedule_id === null && <span className="ct-tag is-warn">일정 없음</span>}
        <span>{kstShort(r.created_at)}</span>
      </div>
      <p className="ct-ib-text">{review ? '에이전트가 쓴 답이 뒤 확인에 걸려 보내지 않고 남았습니다. 초안을 읽고 고치거나 버려 주세요.' : r.text}</p>
      {r.quote && (
        <p className="ct-ib-quote">
          <span>들은 말</span>
          <q>{`“${r.quote}”`}</q>
          <span className={`ct-tag ${r.quote_found ? 'ct-ib-tag-ok' : 'is-warn'}`}>{r.quote_found ? '근거 있음' : '근거 못 찾음'}</span>
        </p>
      )}
      <div className="ct-actions">
        <Button variant="primary" disabled={busy} onClick={() => onReview(r)}>
          확인함
        </Button>
        {!review && <Button onClick={() => useWindows.getState().open('chat', { ask: delayAsk(r) })}>지연 기록 만들기</Button>}
        {canOpen && (
          <Button onClick={open}>{review ? '초안 보기' : r.medium === 'call' ? '통화 보기' : '대화 보기'}</Button>
        )}
      </div>
    </article>
  );
}

const ORDER = Object.keys(REPORT_KIND);
const rank = (k: string) => (ORDER.includes(k) ? ORDER.indexOf(k) : ORDER.length);
const matches = (r: Report, q: string) => [r.text, r.quote, r.contact_name ?? '', r.peer_masked ?? '', kindLabel(r.kind), mediumLabel(r.medium)].some((t) => t.toLowerCase().includes(q));

/** 오른쪽 칸의 「확인할 보고」 — 종류별 묶음(긴급 먼저)과 찾기. */
export function ReportsPane({ scheduleId, items, onChanged, onOpenPerson, onOpenPeer }: {
  scheduleId: number;
  items: Report[];
  onChanged: () => void;
  onOpenPerson: (id: number, tab: 'messages' | 'calls') => void;
  onOpenPeer: (key: string) => void;
}) {
  const [query, setQuery] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const q = query.trim().toLowerCase();
  const shown = q ? items.filter((r) => matches(r, q)) : items;
  const kinds = [...new Set(shown.map((r) => r.kind))].sort((a, b) => rank(a) - rank(b));
  const onReview = (r: Report) => {
    setBusy(true);
    setError(null);
    reviewReport(scheduleId, r)
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : '요청을 처리할 수 없습니다.'))
      .finally(() => {
        setBusy(false);
        onChanged();
      });
  };
  return (
    <section className="ct-ib-pane" aria-label="확인할 보고">
      <div className="ct-ib-head">
        <h2 className="ct-ib-title">{`확인할 보고 ${items.length}`}</h2>
      </div>
      <p className="ct-hint">문자·전화로 받은 보고입니다. 일정은 바뀌지 않았습니다 — 읽고 [확인함]을 누르거나 지연 기록을 만드세요.</p>
      <div className="ct-ib-tools">
        <input type="search" className="ct-input" aria-label="보고 찾기" placeholder="글·이름·종류 찾기" value={query} onChange={(e) => setQuery(e.target.value)} />
        {q && <span className="ct-muted">{`${shown.length} / ${items.length}`}</span>}
      </div>
      {error && (
        <p className="ct-error" role="alert">
          {error}
        </p>
      )}
      {items.length === 0 ? <p className="ct-muted">확인할 보고가 없습니다.</p> : shown.length === 0 && <p className="ct-muted">찾는 보고가 없습니다.</p>}
      {kinds.map((k) => {
        const group = shown.filter((r) => r.kind === k);
        return (
          <div key={k} className="ct-ib-sec">
            <h3 className="ct-ib-sec-title">{`${kindLabel(k)} ${group.length}`}</h3>
            {group.map((r) => (
              <Card key={`${r.schedule_id ?? 'x'}-${r.id}`} r={r} busy={busy} onReview={onReview} onOpenPerson={onOpenPerson} onOpenPeer={onOpenPeer} />
            ))}
          </div>
        );
      })}
    </section>
  );
}
