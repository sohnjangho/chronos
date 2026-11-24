// 관리 포인트 카드의 바깥 위험 줄과 [근거 문장 보기](계획 5 Task 6). 숫자·출처·기준 시각은 서버 줄 그대로.
// 아직 안 눌렀으면 POST(서버가 뒤에서 찾음), 찾는 중이면 카드의 폴링(GET)이 바꾼다. 실패(멈춘 찾기 포함)면 「다시 찾기」(retry).
// 카드가 멈췄으면(frozen — 지난 버전 old · 너무 오래 cap) 찾는 중을 돌리지 않고 그렇다고 적는다. 지난 버전이면 새로 찾지 않는다.
import { useState } from 'react';
import { asList, asText, type CardCtx } from './Card';
import { errorText, findQuote, type QuoteState } from './pointsApi';
import type { Json } from '../thread';

export const KINDS: Record<string, string> = { weather: '날씨', materials: '자재', fx: '환율', business: '업체' };
const ICONS: Record<string, string[]> = {
  weather: ['M7 15a4 4 0 0 1-.6-7.95A5.5 5.5 0 0 1 17 7.5a3.75 3.75 0 0 1 .5 7.5z', 'M8 18.5l-1 2M12 18.5l-1 2M16 18.5l-1 2'],
  materials: ['M12 3l8 4.5v9L12 21l-8-4.5v-9z', 'M4 7.5l8 4.5 8-4.5M12 12v9'],
  fx: ['M4 8h14l-3.5-3.5', 'M20 16H6l3.5 3.5'],
  business: ['M4 21V6l8-3v18', 'M12 9l8 2v10', 'M3 21h18M7.5 9h1M7.5 13h1M7.5 17h1M15.5 14h1M15.5 18h1'],
};

export function KindIcon({ kind }: { kind: string }) {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {(ICONS[kind] ?? ICONS.business).map((d) => (
        <path key={d} d={d} />
      ))}
    </svg>
  );
}

/** 카드가 다시 읽기를 멈춘 까닭: old = 지난 버전 카드(또는 가정이 사라짐), cap = 너무 오래 걸림. */
export type Frozen = 'old' | 'cap' | null;
export const STALE_HINT = '지난 버전 카드 — 지금 포인트 보기에서 찾을 수 있습니다';
const FROZEN_WAIT: Record<'old' | 'cap', string> = { old: '지난 버전 카드라 결과를 더 읽지 않습니다.', cap: '오래 걸려 이 카드에서는 더 읽지 않습니다.' };

function Quotes({ q, busy, frozen, onRetry }: { q: QuoteState | null; busy: boolean; frozen: Frozen; onRetry(): void }) {
  if (frozen && (q === null || q.status === 'pending')) return <span className="pc-fail">{FROZEN_WAIT[frozen]}</span>;
  if (q === null || q.status === 'pending')
    return (
      <span className="pc-wait" role="status">
        <span className="pc-spin" aria-hidden="true" />
        근거 문장 찾는 중 · 보통 30초쯤 걸립니다
      </span>
    );
  if (q.status === 'ready' && q.quotes.length > 0)
    return (
      <>
        {q.quotes.map((x, i) => (
          <blockquote key={i} className="pc-q">
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
    <span className="pc-fail">
      근거 문장을 찾지 못했습니다.
      {q.status === 'failed' && frozen !== 'old' && (
        <button type="button" className="pc-link" disabled={busy} onClick={onRetry}>
          다시 찾기
        </button>
      )}
    </span>
  );
}

export function RiskRow({ r, quote, whatIf, sid, ctx, pointName, frozen, onQuote }: {
  r: Json;
  quote: QuoteState | null;
  frozen: Frozen;
  whatIf: boolean;
  sid: number | null;
  ctx: CardCtx;
  pointName: string;
  onQuote(q: QuoteState): void;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const kind = asText(r.kind);
  const aid = asText(r.activity_id);
  const ok = asText(r.status) === 'ok';
  const actions = asList(r.actions).map(asText);
  const src = [asText(r.source), asText(r.as_of)].filter(Boolean).join(' · ');
  const why = asText(r.why);

  const ask = async (retry: boolean) => {
    if (sid === null || busy) return;
    setBusy(true);
    setError('');
    try {
      onQuote(await findQuote(sid, aid, kind, whatIf, retry));
    } catch (e) {
      setError(errorText(e, '근거 문장을 찾지 못했습니다.'));
    } finally {
      setBusy(false);
    }
  };
  const toggle = () => {
    if (open) return setOpen(false);
    setOpen(true);
    if (quote === null) void ask(false);
    else if (quote.status === 'pending') onQuote(quote); // 찾는 중이던 것 — 폴링이 이어 읽는다
  };

  return (
    <li className={`pc-risk${ok ? '' : ' is-quiet'}`}>
      <span className="pc-kind">
        <KindIcon kind={kind} />
        {KINDS[kind] ?? kind}
      </span>
      <div className="pc-risk-b">
        <span className="pc-risk-text ch-wrap">{asText(r.line)}</span>
        {ok && src && <span className="pc-src">{src}</span>}
        {ok && actions.includes('quote') && (
          <button
            type="button"
            className="pc-link"
            aria-expanded={open}
            disabled={frozen === 'old' && !open}
            title={frozen === 'old' && !open ? STALE_HINT : undefined}
            onClick={toggle}
          >
            {open ? '근거 문장 접기' : '근거 문장 보기'}
          </button>
        )}
        {ok && actions.includes('condition') && (
          <button type="button" className="pc-link" onClick={() => void ctx.sendText(`「${pointName}」 기간에 이 날씨를 조건으로 넣어 본 복사본을 만들어 줘: ${asText(r.line)}`)}>
            조건으로 넣어 보기
          </button>
        )}
        {why && <span className="pc-why">{why}</span>}
        {open && (
          <div className="pc-quotes">
            {error ? <p className="ch-error ch-wrap" role="alert">{error}</p> : <Quotes q={quote} busy={busy} frozen={frozen} onRetry={() => void ask(true)} />}
          </div>
        )}
      </div>
    </li>
  );
}

