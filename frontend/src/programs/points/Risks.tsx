// 바깥 위험 줄과 [근거 문장 보기](사람이 누를 때만 찾기를 부른다). 자료 없음(none) 줄은 본문에 그대로, 건너뛴 자료(skipped)는
// 「건너뛴 자료 n개 ▸」로 접어 둔다(처음엔 닫힘, PM 11-24). 줄·출처·문장은 서버 값 그대로.
import { useState } from 'react';
import { KindIcon, KINDS } from './format';
import { errorText, findQuote, type QuoteState, type Risk } from './pointsApi';

function Quotes({ q, busy, onRetry }: { q: QuoteState | null; busy: boolean; onRetry(): void }) {
  if (q === null || q.status === 'pending')
    return (
      <span className="pt-muted" role="status">
        근거 문장 찾는 중 · 보통 30초쯤 걸립니다
      </span>
    );
  if (q.status === 'ready' && q.quotes.length > 0)
    return (
      <>
        {q.quotes.map((x, i) => (
          <blockquote key={i} className="pt-q">
            <p>{x.text}</p>
            {x.url && (
              <a href={x.url} target="_blank" rel="noreferrer">
                {`${x.title || x.url} ↗`}
              </a>
            )}
          </blockquote>
        ))}
      </>
    );
  return (
    <span className="pt-muted">
      근거 문장을 찾지 못했습니다.{' '}
      {q.status === 'failed' && (
        <button type="button" className="pt-link" disabled={busy} onClick={onRetry}>
          다시 찾기
        </button>
      )}
    </span>
  );
}

function RiskRow({ sid, r, quote, onQuote }: { sid: number; r: Risk; quote: QuoteState | null; onQuote(q: QuoteState): void }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const ok = r.status === 'ok';
  const src = [r.source, r.as_of].filter(Boolean).join(' · ');
  const ask = async (retry: boolean) => {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      onQuote(await findQuote(sid, r.activity_id, r.kind, retry));
    } catch (e) {
      setError(errorText(e, '근거 문장을 찾지 못했습니다.'));
    } finally {
      setBusy(false);
    }
  };
  const toggle = () => {
    if (open) return setOpen(false);
    setOpen(true);
    if (quote === null) void ask(false); // 사람이 처음 누를 때만 찾기를 부른다(찾는 중·찾은 것은 다시 부르지 않음)
  };
  return (
    <li className={`pt-risk${ok ? '' : ' is-quiet'}`}>
      <span className="pt-kind">
        <KindIcon kind={r.kind} />
        {KINDS[r.kind] ?? r.kind}
      </span>
      <div className="pt-risk-b">
        <span className="pt-risk-text">{r.line}</span>
        {ok && src && <span className="pt-muted">{src}</span>}
        {ok && (
          <button type="button" className="pt-link" aria-expanded={open} onClick={toggle}>
            {open ? '근거 문장 접기' : '근거 문장 보기'}
          </button>
        )}
        {r.why && <span className="pt-why">{r.why}</span>}
        {open && <div className="pt-quotes">{error ? <p className="pt-error" role="alert">{error}</p> : <Quotes q={quote} busy={busy} onRetry={() => void ask(true)} />}</div>}
      </div>
    </li>
  );
}

export function Risks({ sid, aid, risks, quotes, looking, onQuote }: {
  sid: number;
  aid: string;
  risks: Risk[];
  quotes: Record<string, QuoteState | null>;
  looking: boolean;
  onQuote(key: string, q: QuoteState): void;
}) {
  const [skippedOpen, setSkippedOpen] = useState(false);
  const mine = risks.filter((r) => r.activity_id === aid);
  const shown = mine.filter((r) => r.status !== 'skipped');
  const skipped = mine.filter((r) => r.status === 'skipped');
  if (mine.length === 0)
    return <p className="pt-muted">{looking ? '바깥 위험 찾는 중…' : '바깥 위험은 이번 버전에 새로 들어온 포인트만 찾습니다. 이 포인트는 찾은 기록이 없습니다.'}</p>;
  return (
    <>
      {shown.length > 0 && (
        <ul className="pt-risks">
          {shown.map((r, i) => {
            const key = `${r.activity_id}/${r.kind}`;
            return <RiskRow key={`${key}-${i}`} sid={sid} r={r} quote={quotes[key] ?? null} onQuote={(q) => onQuote(key, q)} />;
          })}
        </ul>
      )}
      {skipped.length > 0 && (
        <div className="pt-skipped">
          <button type="button" className="pt-link" aria-expanded={skippedOpen} onClick={() => setSkippedOpen((o) => !o)}>
            {`건너뛴 자료 ${skipped.length}개 ${skippedOpen ? '▾' : '▸'}`}
          </button>
          {skippedOpen && (
            <ul className="pt-plain">
              {skipped.map((r, i) => (
                <li key={i} className="pt-muted">{`${KINDS[r.kind] ?? r.kind} · ${r.line}`}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </>
  );
}

/** 바깥 위험 찾기가 실패했을 때(멈춘 것 포함): 서버 글과 [다시 찾기](사람이 누를 때만). */
export function RiskRetry({ message, onRetry }: { message: string; onRetry(): Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const press = async () => {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      await onRetry();
    } catch (e) {
      setError(errorText(e, '다시 찾지 못했습니다.'));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="pt-retry" role="alert">
      <span>{message || '바깥 위험을 찾지 못했습니다'}</span>
      <button type="button" className="pt-link" disabled={busy} onClick={() => void press()}>
        다시 찾기
      </button>
      {error && <span className="pt-error">{error}</span>}
    </div>
  );
}
