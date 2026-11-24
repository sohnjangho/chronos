// 「관리 포인트가 바뀌었습니다」 카드(계획 5 Task 6 — points.check·지연 분석의 card{kind:"points_changed"}, 서버
// backend/app/points/card.py payload). PM 승인 시안 shots/mock-card/card.html·contact.html 꼴.
// - 새 포인트(new = added + became_critical)·여유가 준 포인트(tightened): 여유 n일 → m일(before_tf 키가 없으면 「여유 m일」만),
//   크리티컬 표시, 포인트마다 바깥 위험 줄(출처·기준 시각·고른 까닭). 「바깥 자료 없음」(none) 줄은 본문에 그대로, 숫자·단추 없음.
// - 건너뛴 자료(skipped)는 카드 아래 「건너뛴 자료 n개 ▸」로 접어 둔다(처음엔 닫힘, PM 11-24).
// - [근거 문장 보기]: 아직 안 눌렀으면 POST(서버가 뒤에서 찾음) → 찾는 중이면 GET 으로만 다시 읽는다(채우기를 다시 부르지 않음).
//   실패(멈춘 찾기 포함)면 「다시 찾기」(retry). [조건으로 넣어 보기]는 서버가 허락한 줄(날씨)에만.
// - [담당자에게 확인 연락]: 그 포인트 안에서 담당 협력사 연락처(번호 없음)를 고르고 글을 미리 본 뒤 [초안 만들기] → 기존 초안 카드.
//   보내지 않는다 — 보내기는 초안 카드의 [보내기]·연락처 창에서 사람이.
// - 바깥 위험을 찾는 중(risk_status looking)이거나 근거 문장을 찾는 중이면 POLL_MS 마다 GET …/points 를 읽어 바꾼다(읽는 중이면
//   그 차례는 건너뜀). 다른 버전이 오거나 404(가정이 사라짐)면 「지난 버전 카드」로 멈추고, POLL_CAP_MS 가 지나면 멈춘다.
//   멈춘 카드는 「지금 포인트 보기」로 지금 포인트 목록을 아래에 보인다. 지난 버전 카드에서는 근거 문장을 새로 찾지 않는다.
// - 현장 관리자(role field)에게는 연락 단추를 보이지 않는다(서버도 403). 만든 초안 카드는 대화를 다시 열어도 그 자리에(이 탭 안).
import { useEffect, useRef, useState } from 'react';
import { useSession } from '../../../os/session';
import { ApiError } from '../../../shared/api';
import Badge from '../../../shared/ui/Badge';
import Button from '../../../shared/ui/Button';
import type { Json } from '../thread';
import { asList, asNum, asObj, asText, Card, type CardCtx, type CardProps } from './Card';
import OutreachCallDraftCard from './OutreachCallDraftCard';
import OutreachDraftCard from './OutreachDraftCard';
import ContactPicker from './PointContact';
import { KindIcon, KINDS, RiskRow, type Frozen } from './PointRisks';
import { FrozenLine } from './PointsList';
import { errorText, getPoints, monthDay, retryRisks, type QuoteState } from './pointsApi';
import './pointsCards.css';

export const POLL_MS = 3000;
/** 이만큼 넘게 다시 읽었으면 멈춘다(서버의 멈춘 찾기 판정 15분과 같음). */
export const POLL_CAP_MS = 15 * 60_000;

/** 만든 초안 카드(일정·버전·가정·작업 → 카드). 대화를 닫았다 열어도 같은 탭 안에서는 그 자리에 다시 보인다. */
const drafts = new Map<string, Json>();

const quoteKey = (aid: string, kind: string) => `${aid}/${kind}`;
const span = (es: unknown, ef: unknown) => (monthDay(es) && monthDay(ef) && es !== ef ? `${monthDay(es)} ~ ${monthDay(ef)}` : monthDay(es) || monthDay(ef));
const isPending = (q: QuoteState | null | undefined) => q?.status === 'pending';

/** 카드 상태: 서버 카드(폴링이 바꿈)·누른 근거 문장 상태·멈춤. */
interface Live {
  card: Json;
  quotes: Record<string, QuoteState>;
  frozen: Frozen;
}

/** 날짜 · 실외 작업(건설 일정에서 날씨를 찾은 — 바깥 작업 — 포인트만) · 담당 협력사(서버 responsible, 없으면 뺌). */
function metaLine(item: Json, outdoor: boolean): string {
  const owners = asList(item.responsible).map(asText).filter(Boolean);
  return [span(item.es, item.ef), outdoor && '실외 작업', owners.length > 0 && `담당 ${owners.join(', ')}`].filter(Boolean).join(' · ');
}

function PointBlock({ item, outdoor, live, sid, whatIf, draftKey, ctx, onQuote }: {
  item: Json;
  outdoor: boolean;
  live: Live;
  sid: number | null;
  whatIf: boolean;
  draftKey: string;
  ctx: CardCtx;
  onQuote(key: string, q: QuoteState): void;
}) {
  const field = useSession((s) => s.session?.user.role === 'field');
  const [contact, setContact] = useState(false);
  const [draft, setDraft] = useState<Json | null>(() => drafts.get(draftKey) ?? null);
  const name = asText(item.name) || asText(item.activity_id);
  const aid = asText(item.activity_id);
  const tf = asNum(item.tf);
  const before = asNum(item.before_tf);
  const critical = item.critical === true;
  const actions = asList(item.actions).map(asText).filter((a) => !(field && a === 'contact'));
  const risks = asList(item.risks).map(asObj);
  return (
    <div className={`pc-point ${critical ? 'is-critical' : 'is-near'}`} role="group" aria-label={name}>
      <div className="pc-point-h">
        <b className="ch-wrap">{name}</b>
        {critical ? <Badge tone="danger">크리티컬</Badge> : <Badge tone="warning">크리티컬 직전</Badge>}
        {tf !== null && (
          <span className="pc-float">
            여유 {before !== null && <span className="is-was">{`${before}일`}</span>}
            {before !== null && ' → '}
            <span className="is-now">{`${tf}일`}</span>
          </span>
        )}
      </div>
      {metaLine(item, outdoor) && <p className="ch-meta ch-wrap">{metaLine(item, outdoor)}</p>}
      {risks.length > 0 && (
        <ul className="pc-risks">
          {risks.map((r, i) => {
            const key = quoteKey(asText(r.activity_id), asText(r.kind));
            const q = live.quotes[key] ?? (Object.keys(asObj(r.quote)).length ? (r.quote as unknown as QuoteState) : null);
            return <RiskRow key={`${key}-${i}`} r={r} quote={q} whatIf={whatIf} sid={sid} ctx={ctx} pointName={name} frozen={live.frozen} onQuote={(s) => onQuote(key, s)} />;
          })}
        </ul>
      )}
      {contact && sid !== null && (
        <ContactPicker sid={sid} aid={aid} name={name} whatIf={whatIf} onClose={() => setContact(false)} onDraft={(c) => { drafts.set(draftKey, c); setDraft(c); setContact(false); }} />
      )}
      {draft && (asText(draft.kind) === 'outreach_call_draft' ? <OutreachCallDraftCard data={draft} ctx={ctx} /> : <OutreachDraftCard data={draft} ctx={ctx} />)}
      {!contact && sid !== null && (actions.includes('contact') || actions.includes('recovery')) && (
        <div className="ch-actions">
          {actions.includes('contact') && (
            <Button variant="primary" onClick={() => setContact(true)}>
              담당자에게 확인 연락
            </Button>
          )}
          {actions.includes('recovery') && <Button onClick={() => void ctx.sendText(`「${name}」 일정을 지킬 만회 계획을 만들어 줘`)}>만회안 보기</Button>}
        </div>
      )}
    </div>
  );
}

function removedLine(r: Json): string {
  const name = asText(r.name) || asText(r.activity_id);
  const label = asText(r.label);
  const before = asNum(r.before_tf);
  const tf = asNum(r.tf);
  const floats = asText(r.reason) === 'relief' && before !== null && tf !== null ? ` (여유 ${before}일 → ${tf}일)` : '';
  return `${name}${label ? ` — ${label}` : ''}${floats}`;
}

/** 서버 카드 + 폴링. 바깥 위험을 찾는 중이거나 누른 근거 문장을 찾는 중이면 GET 으로 다시 읽는다(같은 버전일 때만 바꾼다).
 *  다른 버전·404 → old, POLL_CAP_MS 넘음 → cap 으로 멈춘다. 앞 읽기가 안 끝났으면 그 차례는 건너뛴다. */
function useLive(data: Json): [Live, (key: string, q: QuoteState) => void, (card: Json) => void] {
  const [live, setLive] = useState<Live>({ card: data, quotes: {}, frozen: null });
  const inFlight = useRef(false);
  const sid = asNum(data.schedule_id);
  const version = asNum(data.version);
  const whatIf = data.what_if === true;
  const looking = asText(live.card.risk_status) === 'looking';
  const waiting = live.frozen === null && (looking || Object.values(live.quotes).some(isPending));

  useEffect(() => {
    if (!waiting || sid === null) return;
    let alive = true;
    const since = Date.now();
    const freeze = (frozen: Frozen) => alive && setLive((s) => ({ ...s, frozen }));
    const timer = setInterval(() => {
      if (Date.now() - since >= POLL_CAP_MS) return freeze('cap');
      if (inFlight.current) return;
      inFlight.current = true;
      getPoints(sid, whatIf)
        .then((r) => {
          if (!alive) return;
          if (r.version !== version) return freeze('old');
          setLive((s) => {
            const quotes = { ...s.quotes };
            for (const [k, q] of Object.entries(r.quotes ?? {})) if (q && k in quotes) quotes[k] = q;
            return { ...s, card: r.card && r.card.version === version ? r.card : s.card, quotes };
          });
        })
        .catch((e) => e instanceof ApiError && e.status === 404 && freeze('old')) // 그 밖은 다음 차례에 다시 읽는다
        .finally(() => {
          inFlight.current = false;
        });
    }, POLL_MS);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [waiting, sid, version, whatIf]);

  return [
    live,
    (key, q) => setLive((s) => ({ ...s, quotes: { ...s.quotes, [key]: q } })),
    (next) => next.version === version && setLive((s) => ({ ...s, card: next })),
  ];
}

/** 머리 두 줄: 무엇이 바꿨는지(trigger — 지연 {latest, delay_ids} · 버전 {from, to}, 없으면 버전 n) · 가정 · 기준. */
function headline(c: Json, changed: number): [string, string] {
  const t = asObj(c.trigger);
  const last = asObj(t.latest);
  const days = asNum(last.days);
  const more = asList(t.delay_ids).length - 1;
  const basis = asObj(c.basis);
  const cause = t.kind === 'delay' && days !== null ? `${asText(last.name) || asText(last.activity_id)} +${days}일` : '';
  const version = t.kind === 'version' && asNum(t.from) !== null && asNum(t.to) !== null ? `버전 ${asNum(t.from)} → ${asNum(t.to)}` : asNum(c.version) !== null && `버전 ${asNum(c.version)}`;
  const meta = [
    cause,
    c.what_if === true ? '지연 가정(저장 전)' : version,
    asNum(basis.tf_days) !== null && asNum(basis.window_weeks) !== null && `기준: 여유 ${asNum(basis.tf_days)}일 이하, 앞으로 ${asNum(basis.window_weeks)}주`,
  ].filter(Boolean).join(' · ');
  const why = cause ? `${days}일 지연${more > 0 ? ` 외 ${more}건` : ''}으로 ` : '';
  return [`${why}관리 포인트 ${changed}곳이 바뀌었습니다`, meta];
}

/** 바깥 위험 찾기 상태 줄: 찾는 중 · 실패(서버가 허락하면 「다시 찾기」 → 조회와 같은 꼴을 받아 카드를 바꾸고 폴링이 이어 읽는다). */
function RiskState({ c, frozen, onCard }: { c: Json; frozen: Frozen; onCard(card: Json): void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const status = asText(c.risk_status);
  const sid = asNum(c.schedule_id);
  const retry = async () => {
    if (sid === null || busy) return;
    setBusy(true);
    setError('');
    try {
      const r = await retryRisks(sid, c.what_if === true);
      if (r.card) onCard(r.card);
    } catch (e) {
      setError(errorText(e, '다시 찾지 못했습니다.'));
    } finally {
      setBusy(false);
    }
  };
  if (status === 'looking' && frozen) return null; // 멈춘 카드 — 아래 한 줄이 말한다
  if (status === 'looking')
    return (
      <p className="pc-wait" role="status">
        <span className="pc-spin" aria-hidden="true" />
        {asText(c.risk_message) || '바깥 위험 찾는 중'}
      </p>
    );
  if (status !== 'failed') return null;
  return (
    <p className="pc-fail ch-wrap">
      {asText(c.risk_message) || '바깥 위험을 찾지 못했습니다'}
      {c.risk_retry === true && sid !== null && frozen !== 'old' && (
        <button type="button" className="pc-link" aria-label="바깥 위험 다시 찾기" disabled={busy} onClick={() => void retry()}>
          다시 찾기
        </button>
      )}
      {error && <span className="ch-error" role="alert">{error}</span>}
    </p>
  );
}

export default function PointsChangedCard({ data, ctx }: CardProps) {
  const [live, setQuote, setCard] = useLive(data);
  const c = live.card;
  const sid = asNum(c.schedule_id);
  const whatIf = c.what_if === true;
  const fresh = asList(c.new).map(asObj);
  const tightened = asList(c.tightened).map(asObj);
  const removed = asList(c.removed).map(asObj);
  const skipped = asList(c.skipped).map(asObj);
  const more = asNum(c.more) ?? 0;
  const [sum, meta] = headline(c, fresh.length + more + tightened.length);
  // 날씨는 바깥 작업으로 고른 포인트만 찾는다(찾았든 건너뛰었든) — 건설 일정에서만 「실외 작업」
  const weathered = new Set(
    [...fresh.flatMap((p) => asList(p.risks).map(asObj)), ...skipped].filter((r) => r.kind === 'weather').map((r) => asText(r.activity_id)),
  );
  const outdoor = (item: Json) => c.domain === 'construction' && weathered.has(asText(item.activity_id));
  const block = (item: Json, i: number) => (
    <PointBlock
      key={`${asText(item.activity_id)}-${i}`}
      item={item}
      outdoor={outdoor(item)}
      live={live}
      sid={sid}
      whatIf={whatIf}
      draftKey={`${sid}/${asText(c.version)}/${String(whatIf)}/${asText(item.activity_id)}`}
      ctx={ctx}
      onQuote={setQuote}
    />
  );
  return (
    <Card title="관리 포인트" extra={<Badge tone="warning">바뀜</Badge>}>
      <p className="ch-card-title ch-wrap">관리 포인트가 바뀌었습니다</p>
      <p className="ch-wrap">
        <span className="pc-sum">{sum}</span> {meta && <span className="ch-meta">{meta}</span>}
      </p>
      {live.frozen && <FrozenLine frozen={live.frozen} sid={sid} />}
      <RiskState c={c} frozen={live.frozen} onCard={setCard} />
      {fresh.length > 0 && <div className="pc-sec">{`새로 들어온 포인트 ${fresh.length + more}`}</div>}
      {fresh.map(block)}
      {more > 0 && <p className="ch-meta">{`그 밖에 ${more}곳 더 — 주의할 일정·일정판에서 볼 수 있습니다`}</p>}
      {tightened.length > 0 && <div className="pc-sec">{`여유가 준 포인트 ${tightened.length}`}</div>}
      {tightened.map(block)}
      {removed.length > 0 && (
        <div className="pc-removed">
          <span className="pc-sec">{`빠진 포인트 ${removed.length}`}</span>
          <ul>
            {removed.map((r, i) => (
              <li key={i} className="ch-wrap">{removedLine(r)}</li>
            ))}
          </ul>
        </div>
      )}
      {skipped.length > 0 && (
        <details className="pc-skip">
          <summary>{`건너뛴 자료 ${skipped.length}개`}</summary>
          <ul>
            {skipped.map((s, i) => (
              <li key={i}>
                <KindIcon kind={asText(s.kind)} />
                <span className="ch-wrap">{`${KINDS[asText(s.kind)] ?? asText(s.kind)} · ${asText(s.name)} — ${asText(s.line)}`}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </Card>
  );
}
