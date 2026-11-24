// 고른 포인트의 자세히(시안 공통 오른쪽 칸): 여유·기간·담당 → 여유 흐름(버전별) → 바깥 위험(+ 건너뛴 자료 접힘, 근거 문장) →
// 「당겨도 소용 있나」(서버 계산, 읽기) → [담당자에게 확인 연락](현장 관리자에게는 없음) · [만회안 보기].
// [준비 상태 확인 요청]은 그 기능(G)이 생길 때까지 숨긴다(PM 11-24). 숫자·날짜·문장은 모두 서버 값 그대로.
import { useEffect, useState, type FormEvent } from 'react';
import { useWindows } from '../../os/windowStore';
import Badge from '../../shared/ui/Badge';
import Button from '../../shared/ui/Button';
import { md, span, stamp } from './format';
import PointContact from './PointContact';
import { Risks } from './Risks';
import { errorText, getHistory, postAccel, type AccelResult, type FloatRow, type HistoryEntry, type Point, type QuoteState, type Risk } from './pointsApi';

const DAYS_MAX = 365;

function FloatFlow({ sid, aid, version, k, entries }: { sid: number; aid: string; version: number; k: number; entries: HistoryEntry[] }) {
  const [rows, setRows] = useState<FloatRow[] | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let live = true;
    setRows(null);
    setError('');
    getHistory(sid, aid)
      .then((h) => live && setRows(h.float ?? []))
      .catch((e) => live && setError(errorText(e, '여유 흐름을 읽지 못했습니다.')));
    return () => {
      live = false;
    };
  }, [sid, aid, version]);
  if (error) return <p className="pt-error" role="alert">{error}</p>;
  if (rows === null) return <p className="pt-muted">여유 흐름을 읽는 중…</p>;
  if (rows.length === 0) return <p className="pt-muted">버전 기록이 없습니다.</p>;
  const scale = Math.max(1, k * 2, ...rows.map((r) => r.tf ?? 0));
  const at = (v: number) => stamp(entries.find((e) => e.version === v)?.saved_at ?? null);
  return (
    <div className="pt-flow" role="list" aria-label="여유 흐름">
      {rows.map((r) => (
        <div key={r.version} className="pt-flow-row" role="listitem">
          <span className="pt-muted">{`버전 ${r.version}${at(r.version) ? ` · ${at(r.version).slice(0, 5)}` : ''}`}</span>
          <span className="pt-flow-track" aria-hidden="true">
            {r.tf !== null && r.tf > 0 && (
              <span className={`pt-flow-fill${r.point ? (r.critical ? ' is-crit' : ' is-near') : ''}`} style={{ width: `${Math.min(100, (r.tf / scale) * 100)}%` }} />
            )}
            <span className="pt-flow-k" style={{ left: `${(k / scale) * 100}%` }} />
          </span>
          <span className="pt-flow-v">{r.tf === null ? '—' : `${r.tf}일`}</span>
        </div>
      ))}
      <p className="pt-muted">{`빨간 점선 = 기준(여유 ${k}일). 색 막대 = 그 버전의 관리 포인트, 회색 = 기준 밖.`}</p>
    </div>
  );
}

function Accel({ sid, aid }: { sid: number; aid: string }) {
  const [days, setDays] = useState('3');
  const [result, setResult] = useState<AccelResult | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const n = /^\d+$/.test(days.trim()) ? Number(days.trim()) : NaN;
  const valid = n >= 1 && n <= DAYS_MAX;
  const run = async (e: FormEvent) => {
    e.preventDefault();
    if (!valid || busy) return;
    setBusy(true);
    setError('');
    setResult(null);
    try {
      setResult(await postAccel(sid, aid, n));
    } catch (err) {
      setError(errorText(err, '계산하지 못했습니다.'));
    } finally {
      setBusy(false);
    }
  };
  const over = result !== null && result.reached_days > result.pulled_days; // 자원이 섞여 더 반영 — 경고 색 없음
  return (
    <div className="pt-accel">
      <form className="pt-try" onSubmit={(e) => void run(e)}>
        <input className="pt-input pt-days" inputMode="numeric" aria-label="당길 날 수" value={days} onChange={(e) => setDays(e.target.value)} />
        <span>일 당기면</span>
        <Button type="submit" disabled={!valid || busy}>
          {busy ? '계산 중…' : '계산'}
        </Button>
      </form>
      {!valid && days.trim() !== '' && <p className="pt-muted">{`1~${DAYS_MAX} 사이 근무일 수를 넣어 주세요.`}</p>}
      {error && <p className="pt-error" role="alert">{error}</p>}
      {result && (
        <div className="pt-accel-r" role="status">
          <p className={`pt-line${result.warn && !over ? ' is-warn' : ''}`}>{result.warn_line ?? `당긴 ${result.pulled_days}일 중 ${result.reached_days}일이 준공에 반영됩니다`}</p>
          <p className="pt-muted">{`준공 반영 ${result.pulled_days}일 중 ${result.reached_days}일 · 기간 ${result.od_before}일 → ${result.od_after}일 · 준공 ${md(result.finish_before)} → ${md(result.finish_after)}`}</p>
          {result.next_chain.length > 0 && (
            <p className="pt-chain">
              <span className="pt-muted">{result.same_chain ? '당긴 뒤에도 같은 줄이 일정을 정합니다: ' : '당긴 뒤 일정을 정하는 다음 줄: '}</span>
              {result.next_chain.map((c, i) => (
                <span key={c.activity_id}>
                  {i > 0 && ' → '}
                  <b>{c.name}</b>
                  {c.point && <Badge tone="warning">관리 포인트</Badge>}
                </span>
              ))}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

export interface DetailProps {
  sid: number;
  point: Point;
  version: number;
  k: number;
  dataDate: string;
  change: string | null;
  responsible: string[];
  risks: Risk[];
  quotes: Record<string, QuoteState | null>;
  looking: boolean;
  entries: HistoryEntry[];
  canContact: boolean;
  onQuote(key: string, q: QuoteState): void;
  onBack?: () => void;
}

export default function PointDetail(props: DetailProps) {
  const { sid, point, version, k, dataDate, change, responsible, risks, quotes, looking, entries, canContact, onQuote, onBack } = props;
  const [contact, setContact] = useState(false);
  const recovery = () =>
    useWindows.getState().open('chat', { ask: `${point.activity_id} 「${point.name}」 일정을 지킬 만회 계획을 만들어 줘` });
  return (
    <section className="pt-detail" aria-label={`${point.name} 자세히`}>
      {onBack && (
        <button type="button" className="pt-back" onClick={onBack}>
          ‹ 보드
        </button>
      )}
      <div className="pt-detail-head">
        <h3 className="pt-title">{point.name}</h3>
        {point.critical ? <Badge tone="danger">크리티컬</Badge> : <Badge tone="warning">크리티컬 직전</Badge>}
        {change && <Badge tone="info">{change}</Badge>}
      </div>
      <div className="pt-kv">
        <span>여유</span>
        <span>
          <b>{`${point.tf}일`}</b> <span className="pt-muted">{`(기준 ${k}일 이하)`}</span>
        </span>
      </div>
      <div className="pt-kv">
        <span>기간</span>
        <span>{`${point.es.slice(0, 4)}.${span(point.es, point.ef)}${point.es < dataDate ? ' · 진행 중' : ''}`}</span>
      </div>
      <div className="pt-kv">
        <span>작업 ID</span>
        <span>{point.activity_id}</span>
      </div>
      {responsible.length > 0 && (
        <div className="pt-kv">
          <span>담당</span>
          <span>{responsible.join(', ')}</span>
        </div>
      )}
      <div className="pt-sec">여유 흐름</div>
      <FloatFlow sid={sid} aid={point.activity_id} version={version} k={k} entries={entries} />
      <div className="pt-sec">바깥 위험</div>
      <Risks sid={sid} aid={point.activity_id} risks={risks} quotes={quotes} looking={looking} onQuote={onQuote} />
      <div className="pt-sec">당겨도 소용 있나</div>
      <Accel key={point.activity_id} sid={sid} aid={point.activity_id} />
      {contact && canContact ? (
        <PointContact sid={sid} aid={point.activity_id} name={point.name} onClose={() => setContact(false)} />
      ) : (
        <div className="pt-actions">
          {canContact && (
            <Button variant="primary" onClick={() => setContact(true)}>
              담당자에게 확인 연락
            </Button>
          )}
          <Button onClick={recovery}>만회안 보기</Button>
        </div>
      )}
    </section>
  );
}
