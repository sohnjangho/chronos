// 여러 명에게 한 번에(Task 103) — 다른 화면(스케줄·간트·현장 허브·승인함, Task 104)이 여는 공용 창. 겹화면은 가장 가까운 position 이 있는
// 조상(창 본문)을 덮는다. ① 받는 사람 고르기: 협력사별 묶음 + 찾기, preset.trade 면 그 공종 협력사의 보낼 수 있는 사람을 미리 고름, 보낼 수
// 없는 사람(번호 없음·번호 오류·수신 거부·문자를 받지 못함)은 흐리게 + 까닭, 한 번에 20명까지. ② 내용 확인: 문자 글(카카오톡은 준비됐을 때만
// 문안으로). ③ [n명에게 보내기] → POST …/outreach/batches 하나(useRef 잠금) → 사람별 결과 표(판정 글 그대로 — 「확인 필요」·거절은 「보냄」이
// 아님) + 「묶음 #n · …명 중 …명 회신」. 요청 번호(request_key)는 창마다 하나라, 답을 못 받아 다시 물어도 서버는 다시 보내지 않는다.
// 번호는 서버가 준 가린 꼴만 보인다.
import { useEffect, useMemo, useRef, useState } from 'react';
import { useModalFocus } from '../../os/modalFocus';
import { api, ApiError } from '../api';
import Button from '../ui/Button';
import { outcomeLabel, SEND_UNKNOWN, type Label } from './labels';
import { sendOutcomeUnknown, type Outcome } from './outreachApi';
import './batchSend.css';

export const BATCH_MAX = 20;
/** templateUse = 카카오톡 문안의 쓰는 곳(예 「체크인 요청」, 준비 전이면 문자 글로). trade = 그 공종 협력사의 보낼 수 있는 사람을 미리 고름. */
export interface BatchPreset { body?: string; templateUse?: string; activityId?: string; fieldItemId?: number; approvalId?: number; trade?: string }
export interface BatchSendDialogProps { scheduleId: number; title: string; preset: BatchPreset; onClose(): void }
interface Person {
  id: number; name: string; role_title: string; phone_masked: string; has_phone: boolean; phone_kind: string | null;
  channels: string[]; do_not_contact: boolean; phone_invalid: boolean; hidden: boolean;
}
interface Company { id: number; name: string; trade: string; hidden: boolean; people: Person[] }
interface Template { id: number; use: string; body: string; variables: string[]; usable: boolean }
interface Templates { ready: boolean; reason: string | null; templates: Template[] }
interface Result { contact_id: number; name: string; outcome: Outcome }
interface Sent { batch_id: number; replayed: boolean; results: Result[] }

export const batchLine = (b: { id: number; total: number; replied: number }) => `묶음 #${b.id} · ${b.total}명 중 ${b.replied}명 회신`;
const FULL = '한 번에 20명까지 보낼 수 있습니다';
const ASK_AGAIN = '보냈는지 확인하지 못했습니다 — [결과 다시 받기]는 같은 요청 번호로 다시 묻습니다(이미 받은 요청이면 다시 보내지 않고 결과만 받습니다).';
const REPLAYED = '이미 받은 요청입니다 — 저장된 결과이며 이번에 다시 보내지 않았습니다.';
const TEST_BAND = '시험 모드 — 허용 번호가 아니면 실제로 나가지 않고 기록만 남습니다';

/** 문자로 보낼 수 없는 까닭(카카오톡도 준비 전에는 문자로 나간다). 보낼 수 있으면 null. */
export function unreachable(p: Person): string | null {
  if (!p.has_phone) return '번호 없음';
  if (p.phone_invalid) return '번호 오류';
  if (p.do_not_contact) return '수신 거부';
  if (!p.channels.includes('sms')) return p.phone_kind === 'mobile' ? '문자 받지 않음으로 되어 있음' : '유선 번호라 문자를 받을 수 없음';
  return null;
}

const newKey = () =>
  globalThis.crypto?.randomUUID?.() ?? `k${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`;
const send = (body: unknown) => ({ method: 'POST', body: JSON.stringify(body) });

function useBook(scheduleId: number, templateUse?: string) {
  const [companies, setCompanies] = useState<Company[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [testMode, setTestMode] = useState(false);
  const [templates, setTemplates] = useState<Templates | null>(null);
  useEffect(() => {
    let live = true;
    api<{ companies: Company[] }>(`/api/schedules/${scheduleId}/contacts`)
      .then((b) => live && setCompanies(b.companies.filter((c) => !c.hidden).map((c) => ({ ...c, people: c.people.filter((p) => !p.hidden) }))))
      .catch((e: unknown) => live && setError(e instanceof Error ? e.message : '주소록을 읽지 못했습니다.'));
    api<{ test_mode: boolean }>('/api/notify/status').then((s) => live && setTestMode(s?.test_mode === true)).catch(() => {});
    if (templateUse) api<Templates>('/api/notify/templates').then((t) => live && setTemplates(t)).catch(() => {});
    return () => { live = false; };
  }, [scheduleId, templateUse]);
  return { companies, error, testMode, templates };
}

function preselect(companies: Company[], trade?: string): number[] {
  const want = trade?.trim();
  if (!want) return [];
  return companies.filter((c) => c.trade.trim() === want).flatMap((c) => c.people).filter((p) => !unreachable(p)).map((p) => p.id).slice(0, BATCH_MAX);
}

export default function BatchSendDialog({ scheduleId, title, preset, onClose }: BatchSendDialogProps) {
  const ref = useRef<HTMLDivElement>(null);
  const trap = useModalFocus(ref);
  const data = useBook(scheduleId, preset.templateUse);
  const [chosen, setChosen] = useState<number[] | null>(null);
  const [step, setStep] = useState<'pick' | 'confirm'>('pick');
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState<Sent | null>(null);
  const [preNote, setPreNote] = useState<string | null>(null);
  useEffect(() => {
    if (!data.companies || chosen !== null) return;
    const ids = preselect(data.companies, preset.trade);
    setChosen(ids);
    if (ids.length) setPreNote(`공종 「${preset.trade!.trim()}」 협력사 사람 ${ids.length}명을 미리 골랐습니다.`);
  }, [data.companies, chosen, preset.trade]);
  const loaded = chosen !== null;
  useEffect(() => {
    ref.current?.querySelector<HTMLElement>('textarea, input, button:not([disabled])')?.focus({ preventScroll: true });
  }, [step, sent, loaded]);
  const people = useMemo(() => new Map((data.companies ?? []).flatMap((c) => c.people.map((p) => [p.id, { p, c }] as const))), [data.companies]);
  let body;
  if (sent) body = <ResultStep scheduleId={scheduleId} sent={sent} people={people} onClose={onClose} />;
  else if (data.error) body = <Foot note={{ text: data.error, tone: 'bad' }} onClose={onClose} />;
  else if (!data.companies || chosen === null) body = <Foot note={{ text: '주소록을 읽는 중…', tone: 'muted' }} onClose={onClose} />;
  else if (step === 'pick') body = <PickStep companies={data.companies} chosen={chosen} setChosen={setChosen} preNote={preNote} onNext={() => setStep('confirm')} onClose={onClose} />;
  else body = <ConfirmStep scheduleId={scheduleId} preset={preset} chosen={chosen} people={people} testMode={data.testMode} templates={data.templates} busy={busy} setBusy={setBusy} onBack={() => setStep('pick')} onSent={setSent} />;
  return (
    <div className="bs-scrim">
      <div ref={ref} className="bs-dialog" role="dialog" aria-modal="true" aria-label={title}
        onKeyDown={(e) => {
          if (e.key === 'Escape') { e.stopPropagation(); if (!busy) onClose(); }
          trap(e);
        }}>
        <h2 className="bs-title">{title}</h2>
        {body}
      </div>
    </div>
  );
}

const Foot = ({ note, onClose }: { note: Label; onClose(): void }) => (
  <><p className={`bs-note bs-wait is-${note.tone}`}>{note.text}</p><div className="bs-foot"><Button onClick={onClose}>닫기</Button></div></>
);

type PeopleMap = Map<number, { p: Person; c: Company }>;
interface PickProps { companies: Company[]; chosen: number[]; setChosen(ids: number[]): void; preNote: string | null; onNext(): void; onClose(): void }

function PickStep({ companies, chosen, setChosen, preNote, onNext, onClose }: PickProps) {
  const [query, setQuery] = useState('');
  const picked = new Set(chosen);
  const full = chosen.length >= BATCH_MAX;
  const q = query.trim().toLowerCase();
  const shown = companies
    .map((c) => ({ c, people: c.people.filter((p) => !q || [p.name, p.role_title, c.name, c.trade].some((t) => t.toLowerCase().includes(q))) }))
    .filter((g) => g.people.length > 0);
  const toggle = (ids: number[], on: boolean) =>
    setChosen(on ? [...chosen, ...ids.filter((id) => !picked.has(id))].slice(0, BATCH_MAX) : chosen.filter((id) => !ids.includes(id)));
  return (
    <>
      <div className="bs-top">
        <input type="search" className="bs-search" aria-label="사람 찾기" placeholder="이름·담당·협력사·공종으로 찾기" value={query} onChange={(e) => setQuery(e.target.value)} />
        <p className="bs-count">{`${chosen.length}명 고름 · 한 번에 ${BATCH_MAX}명까지`}</p>
        {preNote && <p className="bs-note is-info">{preNote}</p>}
      </div>
      <div className="bs-scroll">
        {shown.length === 0 && <p className="bs-empty">찾는 사람이 없습니다.</p>}
        {shown.map(({ c, people }) => {
          const open = people.filter((p) => !unreachable(p)).map((p) => p.id);
          const all = open.length > 0 && open.every((id) => picked.has(id));
          return (
            <div key={c.id} role="group" aria-label={`${c.name} · ${c.trade || '공종 없음'} · ${c.people.length}명`} className="bs-co">
              <label className="bs-co-head bs-co-all">
                <input type="checkbox" aria-label={`${c.name} 모두 고르기`} checked={all} disabled={open.length === 0 || (!all && full)}
                  onChange={(e) => toggle(open, e.target.checked)} />
                <span className="bs-co-name">{c.name}</span>
                <span className="bs-co-meta">{`${c.trade || '공종 없음'} · ${c.people.length}명`}</span>
              </label>
              {people.map((p) => <PersonRow key={p.id} p={p} on={picked.has(p.id)} full={full} onToggle={(on) => toggle([p.id], on)} />)}
            </div>
          );
        })}
      </div>
      <div className="bs-foot">
        <Button onClick={onClose}>취소</Button>
        <Button variant="primary" disabled={chosen.length === 0} onClick={onNext}>{`다음 — 내용 확인 (${chosen.length}명)`}</Button>
      </div>
    </>
  );
}

function PersonRow({ p, on, full, onToggle }: { p: Person; on: boolean; full: boolean; onToggle(on: boolean): void }) {
  const why = unreachable(p) ?? (!on && full ? FULL : null);
  const id = `bs-why-${p.id}`;
  return (
    <label className={`bs-person${unreachable(p) ? ' is-off' : ''}`}>
      <input type="checkbox" checked={on} disabled={why !== null} aria-describedby={why ? id : undefined} onChange={(e) => onToggle(e.target.checked)} />
      <span className="bs-person-name">{p.name}</span>
      <span className="bs-person-role">{p.role_title}</span>
      <span className="bs-person-num">{p.phone_masked}</span>
      {why && <span id={id} className="bs-why">{why}</span>}
    </label>
  );
}

interface ConfirmProps {
  scheduleId: number; preset: BatchPreset; chosen: number[]; people: PeopleMap; testMode: boolean; templates: Templates | null;
  busy: boolean; setBusy(b: boolean): void; onBack(): void; onSent(s: Sent): void;
}

function ConfirmStep({ scheduleId, preset, chosen, people, testMode, templates, busy, setBusy, onBack, onSent }: ConfirmProps) {
  const [requestKey] = useState(newKey);
  const [text, setText] = useState(preset.body ?? '');
  const [kakao, setKakao] = useState(false);
  const [vars, setVars] = useState<Record<string, string>>({});
  const [note, setNote] = useState<Label | null>(null);
  const [asked, setAsked] = useState(false); // 답을 못 받은 요청이 있음 — 같은 번호로만 다시 묻고 내용은 잠근다
  const lock = useRef(false);
  const template = templates?.ready ? templates.templates.find((t) => t.usable && t.use === preset.templateUse) ?? null : null;
  const kakaoOff = template ? null : templates?.reason ?? '카카오톡은 채널·문안 승인 뒤 쓸 수 있습니다 — 지금은 문자로 보냅니다';
  const ready = kakao && template ? template.variables.every((v) => (vars[v] ?? '').trim()) : text.trim().length > 0;
  const go = async () => {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    const links = { activity_id: preset.activityId, field_item_id: preset.fieldItemId, approval_id: preset.approvalId };
    const content = kakao && template ? { channel: 'kakao', template_id: template.id, template_vars: vars } : { channel: 'sms', body: text };
    try {
      onSent(await api<Sent>(`/api/schedules/${scheduleId}/outreach/batches`, send({ contact_ids: chosen, ...content, ...links, request_key: requestKey })));
    } catch (e) {
      const unknown = sendOutcomeUnknown(e);
      if (unknown) setAsked(true);
      setNote(unknown ? { text: ASK_AGAIN, tone: 'warn' } : { text: e instanceof ApiError ? e.message : SEND_UNKNOWN, tone: 'bad' });
    } finally {
      lock.current = false;
      setBusy(false);
    }
  };
  const frozen = busy || asked;
  const names = chosen.map((id) => people.get(id)?.p.name ?? `#${id}`).join(' · ');
  return (
    <>
      <div className="bs-scroll bs-confirm">
        {testMode && <p className="bs-note is-warn">{TEST_BAND}</p>}
        <p className="bs-to"><strong>{`받는 사람 ${chosen.length}명`}</strong><span>{names}</span></p>
        {preset.activityId && <p className="bs-link">{`연결할 작업: ${preset.activityId}`}</p>}
        <div className="bs-lanes" role="group" aria-label="보낼 통로">
          <Button aria-pressed={!kakao} disabled={frozen} onClick={() => setKakao(false)}>문자</Button>
          <Button aria-pressed={kakao} disabled={frozen || kakaoOff !== null} title={kakaoOff ?? undefined} onClick={() => setKakao(true)}>카카오톡</Button>
        </div>
        {preset.templateUse && !template && <p className="bs-note is-muted">{`카카오톡 문안 「${preset.templateUse}」은 지금 쓸 수 없어 문자 글로 보냅니다 — ${kakaoOff}`}</p>}
        {kakao && template ? (
          <TemplateFields template={template} vars={vars} setVars={setVars} frozen={frozen} />
        ) : (
          <label className="bs-field">보낼 글
            <textarea aria-label="보낼 글" rows={5} maxLength={1000} value={text} readOnly={frozen} onChange={(e) => setText(e.target.value)} />
          </label>
        )}
      </div>
      <p role="status" className={`bs-note is-${note?.tone ?? 'muted'}`} hidden={!note}>{note?.text}</p>
      <div className="bs-foot">
        <Button disabled={frozen} onClick={onBack}>뒤로</Button>
        <Button variant="primary" disabled={busy || !ready} onClick={go}>{busy ? '보내는 중…' : asked ? '결과 다시 받기' : `${chosen.length}명에게 보내기`}</Button>
      </div>
    </>
  );
}

function TemplateFields({ template, vars, setVars, frozen }: { template: Template; vars: Record<string, string>; setVars(v: Record<string, string>): void; frozen: boolean }) {
  return (
    <div className="bs-template">
      <p className="bs-template-body">{template.body}</p>
      {template.variables.map((v) => (
        <label key={v} className="bs-field">{v}
          <input aria-label={v} value={vars[v] ?? ''} readOnly={frozen} maxLength={200} onChange={(e) => setVars({ ...vars, [v]: e.target.value })} />
        </label>
      ))}
    </div>
  );
}

const COUNTED: [string, (o: Outcome) => boolean][] = [
  ['보냄', (o) => o.code === 'accepted'],
  ['실패', (o) => o.code === 'failed'],
  ['확인 필요', (o) => o.code === 'unsure'],
  ['예약', (o) => o.code === 'scheduled'],
  ['보내지 않음', (o) => !['accepted', 'failed', 'unsure', 'scheduled'].includes(o.code)],
];

function ResultStep({ scheduleId, sent, people, onClose }: { scheduleId: number; sent: Sent; people: PeopleMap; onClose(): void }) {
  const [stats, setStats] = useState<{ total: number; replied: number } | null>(null);
  useEffect(() => {
    let live = true;
    api<{ total: number; replied: number }>(`/api/schedules/${scheduleId}/outreach/batches/${sent.batch_id}`)
      .then((s) => live && setStats(s)).catch(() => {});
    return () => { live = false; };
  }, [scheduleId, sent.batch_id]);
  const summary = COUNTED.map(([name, hit]) => [name, sent.results.filter((r) => hit(r.outcome)).length] as const)
    .filter(([, n]) => n > 0).map(([name, n]) => `${name} ${n}`).join(' · ');
  return (
    <>
      <div className="bs-top">
        <p className="bs-count">{summary}</p>
        {stats && <p className="bs-batch">{batchLine({ id: sent.batch_id, ...stats })}</p>}
        {sent.replayed && <p className="bs-note is-info">{REPLAYED}</p>}
      </div>
      <div className="bs-scroll">
        <table className="bs-table" aria-label="사람별 결과">
          <thead><tr><th>이름</th><th>협력사</th><th>결과</th></tr></thead>
          <tbody>
            {sent.results.map((r) => {
              const label = outcomeLabel(r.outcome);
              return (
                <tr key={r.contact_id}>
                  <td>{r.name}</td>
                  <td>{people.get(r.contact_id)?.c.name ?? ''}</td>
                  <td className={`bs-out is-${label.tone}`}>{label.text}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="bs-foot"><Button variant="primary" onClick={onClose}>닫기</Button></div>
    </>
  );
}
