// 「확인할 연락처」(Task 85): 통화·문자에서 받은 새 연락처 제안과 언어 바꿈 제안. 번호는 가린 꼴만 보인다 —
// 받아들이면 서버가 제안에 적힌 번호로 지금 프로젝트에 사람을 만든다(주소록 양식과 같은 검사). 일정 없는 제안(모르는 번호)도 여기 든다.
import { useCallback, useEffect, useState } from 'react';
import { api, ApiError } from '../../shared/api';
import { kstShort } from '../../shared/outreach/labels';
import Button from '../../shared/ui/Button';
import { LANGUAGES, type CompanyGroup, type PersonDetail } from './contactsApi';
import './inbound.css';

export interface Proposal {
  id: number;
  kind: 'new' | 'language';
  /** null = 모르는 번호에서 온 것(받으면 지금 프로젝트에) */
  schedule_id: number | null;
  name: string;
  role_title: string;
  company_name: string;
  number_masked: string | null;
  language: string | null;
  contact_id: number | null;
  contact_name: string | null;
  source: 'sms' | 'call' | null;
  created_at: string;
}

/** 협력사 고르기 값: 있는 협력사 id 또는 새 협력사(이름). */
export type CompanyPick = { id: number } | { id: 'new'; name: string };
export const companyBody = (p: CompanyPick) => (p.id === 'new' ? { company_name: p.name.trim() } : { company_id: p.id });

const base = (sid: number) => `/api/schedules/${sid}/contacts/proposals`;
const post = (body?: unknown): RequestInit => ({ method: 'POST', ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
export const getProposals = (sid: number) => api<Proposal[]>(base(sid));
export const acceptProposal = (sid: number, id: number, body: object) => api<PersonDetail>(`${base(sid)}/${id}/accept`, post(body));
export const rejectProposal = (sid: number, id: number) => api<unknown>(`${base(sid)}/${id}/reject`, post());

export function useProposals(sid: number) {
  const [items, setItems] = useState<Proposal[]>([]);
  const [n, setN] = useState(0);
  useEffect(() => {
    let live = true;
    getProposals(sid).then(
      (r) => live && setItems(Array.isArray(r) ? r : []),
      () => live && setItems([]),
    );
    return () => {
      live = false;
    };
  }, [sid, n]);
  return { items, reload: useCallback(() => setN((x) => x + 1), []) };
}

const message = (e: unknown) => (e instanceof ApiError ? e.message : '요청을 처리할 수 없습니다.');
const languageName = (code: string | null) => LANGUAGES.find((l) => l.key === code)?.label ?? code ?? '';
const sourceText = (p: Proposal) => (p.source === 'call' ? '통화에서' : p.source === 'sms' ? '문자에서' : '');

/** 협력사 칸: 이 프로젝트의 협력사 또는 「새 협력사」(이름 칸이 열림). */
export function CompanyChoice({ companies, value, onChange, disabled }: {
  companies: CompanyGroup[];
  value: CompanyPick;
  onChange: (p: CompanyPick) => void;
  disabled?: boolean;
}) {
  return (
    <>
      <label className="ct-fld-label">
        <span className="ct-label">협력사</span>
        <select
          className="ct-input"
          aria-label="협력사"
          value={String(value.id)}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value === 'new' ? { id: 'new', name: '' } : { id: Number(e.target.value) })}
        >
          {companies.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
          <option value="new">새 협력사…</option>
        </select>
      </label>
      {value.id === 'new' && (
        <label className="ct-fld-label">
          <span className="ct-label">새 협력사 이름</span>
          <input className="ct-input" aria-label="새 협력사 이름" maxLength={100} value={value.name} disabled={disabled} onChange={(e) => onChange({ id: 'new', name: e.target.value })} />
        </label>
      )}
    </>
  );
}

/** 처음 고른 협력사: 제안의 협력사 이름과 같은 협력사가 있으면 그것, 이름이 있으면 새 협력사, 아니면 첫 협력사. */
export function firstPick(companies: CompanyGroup[], name: string): CompanyPick {
  const same = companies.find((c) => c.name.trim() === name.trim());
  if (same) return { id: same.id };
  if (name.trim() || companies.length === 0) return { id: 'new', name };
  return { id: companies[0].id };
}

/** 받기·버리기 길은 지금 프로젝트의 것(일정 없는 제안도 지금 프로젝트로 받는다). */
type Shown = Proposal & { scheduleOf: number };

function NewCard({ p, companies, busy, act }: { p: Shown; companies: CompanyGroup[]; busy: boolean; act: (run: () => Promise<unknown>, done: string) => void }) {
  const [name, setName] = useState(p.name);
  const [role, setRole] = useState(p.role_title);
  const [pick, setPick] = useState<CompanyPick>(() => firstPick(companies, p.company_name));
  return (
    <article className="ct-ib-card" aria-label={`${p.name || '이름 모름'} 제안`}>
      <div className="ct-ib-meta">
        <span className="ct-tag">새 연락처</span>
        <span className="ct-num">{p.number_masked ?? '번호 없음'}</span>
        <span>{sourceText(p)}</span>
        {p.schedule_id === null && <span className="ct-tag is-warn">모르는 번호 — 받으면 이 프로젝트에</span>}
        <span>{kstShort(p.created_at)}</span>
      </div>
      <p className="ct-ib-text">{[p.name || '이름 모름', p.role_title, p.company_name].filter(Boolean).join(' · ')}</p>
      <div className="ct-ib-fields">
        <label className="ct-fld-label">
          <span className="ct-label">이름</span>
          <input className="ct-input" aria-label="이름" maxLength={100} value={name} disabled={busy} onChange={(e) => setName(e.target.value)} />
        </label>
        <label className="ct-fld-label">
          <span className="ct-label">담당</span>
          <input className="ct-input" aria-label="담당" maxLength={100} value={role} disabled={busy} onChange={(e) => setRole(e.target.value)} />
        </label>
        <CompanyChoice companies={companies} value={pick} onChange={setPick} disabled={busy} />
      </div>
      <div className="ct-actions">
        <Button variant="primary" disabled={busy} onClick={() => act(() => acceptProposal(p.scheduleOf, p.id, { name, role_title: role, ...companyBody(pick) }), `주소록에 넣었습니다 — ${name}`)}>
          주소록에 넣기
        </Button>
        <Button disabled={busy} onClick={() => act(() => rejectProposal(p.scheduleOf, p.id), '버렸습니다.')}>
          버리기
        </Button>
      </div>
    </article>
  );
}

function LanguageCard({ p, busy, act }: { p: Shown; busy: boolean; act: (run: () => Promise<unknown>, done: string) => void }) {
  const who = p.contact_name ?? '그 사람';
  return (
    <article className="ct-ib-card" aria-label={`${who} 언어 바꾸기`}>
      <div className="ct-ib-meta">
        <span className="ct-tag">언어 바꾸기</span>
        <span>{sourceText(p)}</span>
        <span>{kstShort(p.created_at)}</span>
      </div>
      <p className="ct-ib-text">{`${who}의 언어를 ${languageName(p.language)}(으)로 바꾸자는 제안입니다. 상대가 그 언어로 답했습니다.`}</p>
      <div className="ct-actions">
        <Button variant="primary" disabled={busy} onClick={() => act(() => acceptProposal(p.scheduleOf, p.id, {}), `${who}의 언어를 바꿨습니다.`)}>
          언어 바꾸기
        </Button>
        <Button disabled={busy} onClick={() => act(() => rejectProposal(p.scheduleOf, p.id), '버렸습니다.')}>
          버리기
        </Button>
      </div>
    </article>
  );
}

/** 오른쪽 칸의 「확인할 연락처」. 받기·버리기 뒤에도 이 칸에 남아(다른 제안을 이어서) 결과 한 줄을 보이고 목록을 다시 읽는다. */
export function ProposalsPane({ scheduleId, items, companies, onChanged, onOpenPerson }: {
  scheduleId: number;
  items: Proposal[];
  companies: CompanyGroup[];
  onChanged: () => void;
  onOpenPerson: (id: number) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<{ ok: boolean; text: string; person: number | null } | null>(null);
  const act = (run: () => Promise<unknown>, done: string) => {
    setBusy(true);
    setNote(null);
    run().then(
      (r) => setNote({ ok: true, text: done, person: r && typeof (r as PersonDetail).id === 'number' ? (r as PersonDetail).id : null }),
      (e: unknown) => setNote({ ok: false, text: message(e), person: null }),
    ).finally(() => {
      setBusy(false);
      onChanged();
    });
  };
  const shown: Shown[] = items.map((p) => ({ ...p, scheduleOf: scheduleId }));
  const fresh = shown.filter((p) => p.kind !== 'language');
  const langs = shown.filter((p) => p.kind === 'language');
  return (
    <section className="ct-ib-pane" aria-label="확인할 연락처">
      <div className="ct-ib-head">
        <h2 className="ct-ib-title">{`확인할 연락처 ${items.length}`}</h2>
      </div>
      <p className="ct-hint">통화·문자에서 받은 새 연락처와 언어 바꿈 제안입니다. 확인한 것만 이 프로젝트의 주소록에 들어갑니다.</p>
      {note && (
        <p className={note.ok ? 'ct-ib-done' : 'ct-error'} role={note.ok ? 'status' : 'alert'}>
          {note.text}
          {note.person !== null && (
            <button type="button" className="ct-link" onClick={() => onOpenPerson(note.person as number)}>
              사람 보기
            </button>
          )}
        </p>
      )}
      {items.length === 0 && <p className="ct-muted">확인할 제안이 없습니다.</p>}
      {fresh.length > 0 && (
        <div className="ct-ib-sec">
          <h3 className="ct-ib-sec-title">{`새 연락처 ${fresh.length}`}</h3>
          {fresh.map((p) => <NewCard key={p.id} p={p} companies={companies} busy={busy} act={act} />)}
        </div>
      )}
      {langs.length > 0 && (
        <div className="ct-ib-sec">
          <h3 className="ct-ib-sec-title">{`언어 바꾸기 ${langs.length}`}</h3>
          {langs.map((p) => <LanguageCard key={p.id} p={p} busy={busy} act={act} />)}
        </div>
      )}
    </section>
  );
}
