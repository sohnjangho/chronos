// 「모르는 번호 · 대표번호」(Task 85 · 96 후속): 주소록에 없는 번호와 주고받은 문자·통화(일정 없는 줄)와 이 일정의 대표번호(주소록의
// 여러 사람이 쓰는 번호 — 한 사람으로 정하지 못한 받은 통화)를 번호로 묶은 것. 번호는 가린 꼴과 peer_key 만 —
// 묶음·주소록에 넣기·차단은 peer_key 로 가리키고 전체 번호는 서버가 찾는다(화면에 내려오지 않는다). 차단은 관리자만(설정의 차단 목록과 같은 길).
import { useCallback, useEffect, useState } from 'react';
import { api, ApiError } from '../../shared/api';
import { kstShort } from '../../shared/outreach/labels';
import type { OutreachEvent } from '../../shared/outreach/outreachApi';
import Button from '../../shared/ui/Button';
import type { CompanyGroup, PersonDetail } from './contactsApi';
import { CompanyChoice, companyBody, firstPick, type CompanyPick } from './Proposals';
import PeerLineItem from './UnknownLine';
import './inbound.css';

export interface UnknownPeer {
  peer_key: string;
  number_masked: string;
  last_at: string;
  messages: number;
  calls: number;
  last_line: string;
  last_kind: 'message' | 'call';
  last_direction: string;
  blocked: boolean;
  known: boolean;
  shared: boolean;
}

export interface PeerLine {
  kind: 'message' | 'call';
  id: number;
  direction: string;
  at: string;
  text: string;
  status: string;
  message_kind: string | null;
  events: OutreachEvent[];
  caller_class: string | null;
  fail_reason: string | null;
  duration_s: number | null;
}

export interface UnknownDetail {
  peer_key: string;
  number_masked: string;
  blocked: boolean;
  known: boolean;
  lines: PeerLine[];
}

const post = (body: unknown): RequestInit => ({ method: 'POST', body: JSON.stringify(body) });
/** 지금 일정을 붙여 묻는다 — 서버가 그 일정의 대표번호 통화를 함께 준다(다른 일정의 것은 없다). */
export const getUnknown = (sid: number) => api<UnknownPeer[]>(`/api/outreach/unknown?schedule_id=${sid}`);
export const getUnknownPeer = (key: string, sid: number) => api<UnknownDetail>(`/api/outreach/unknown/${key}?schedule_id=${sid}`);
export const addPeer = (sid: number, key: string, body: object) => api<PersonDetail>(`/api/schedules/${sid}/outreach/unknown/${key}/contact`, post(body));
/** 설정의 차단 목록 길(관리자만) — 번호 대신 peer_key. */
export const blockPeer = (key: string, reason: string) => api<unknown>('/api/notify/blocked', post({ peer_key: key, reason }));

export function useUnknown(scheduleId: number) {
  const [items, setItems] = useState<UnknownPeer[]>([]);
  const [n, setN] = useState(0);
  useEffect(() => {
    let live = true;
    getUnknown(scheduleId).then(
      (r) => live && setItems(Array.isArray(r) ? r : []),
      () => live && setItems([]),
    );
    return () => {
      live = false;
    };
  }, [n, scheduleId]);
  return { items, reload: useCallback(() => setN((x) => x + 1), []) };
}

const SEARCH_FROM = 7;
const digits = (s: string) => s.replace(/\D/g, '');
const lastText = (p: UnknownPeer) => {
  const text = p.last_kind === 'call' ? `전화${p.last_line ? ` — ${p.last_line}` : ''}` : p.last_line;
  return p.last_direction === 'out' ? `보냄: ${text}` : text;
};

/** 주소록 아래의 묶음(접기 · 7개부터 찾기). 번호를 누르면 오른쪽 칸에 그 번호의 줄. */
export function UnknownGroup({ items, current, onOpen }: { items: UnknownPeer[]; current: string | null; onOpen: (key: string) => void }) {
  const [open, setOpen] = useState(true);
  const [query, setQuery] = useState('');
  if (items.length === 0) return null;
  const q = query.trim().toLowerCase();
  const shown = q ? items.filter((p) => (digits(q) && digits(p.number_masked).includes(digits(q))) || p.last_line.toLowerCase().includes(q)) : items;
  return (
    <section role="group" aria-label={`모르는 번호 · 대표번호 ${items.length}`} className="ct-group ct-ib-unknown">
      <div className="ct-co">
        <button type="button" className="ct-co-toggle" aria-expanded={open} aria-label={`모르는 번호 · 대표번호 ${items.length}개`} onClick={() => setOpen((o) => !o)}>
          <span className="ct-caret" aria-hidden="true">{open ? '▾' : '▸'}</span>
          <span className="ct-co-name ct-ellipsis">모르는 번호 · 대표번호</span>
          <span className="ct-co-count">{`${items.length}개`}</span>
        </button>
      </div>
      {open && items.length >= SEARCH_FROM && (
        <div className="ct-ib-find">
          <input type="search" className="ct-input" aria-label="모르는 번호 찾기" placeholder="끝자리·글 찾기" value={query} onChange={(e) => setQuery(e.target.value)} />
          <span className="ct-muted">{`${shown.length} / ${items.length}`}</span>
        </div>
      )}
      {open && (
        <ul className="ct-people">
          {shown.map((p) => (
            <li key={p.peer_key} className="ct-li">
              <button type="button" className="ct-row" aria-current={p.peer_key === current ? 'true' : undefined} onClick={() => onOpen(p.peer_key)}>
                <span className="ct-row-top">
                  <span className="ct-name ct-num ct-ellipsis">{p.number_masked}</span>
                  <span className="ct-ib-when">{kstShort(p.last_at)}</span>
                </span>
                <span className="ct-row-sub">
                  <span className="ct-role ct-ellipsis">{lastText(p)}</span>
                  {p.shared && <span className="ct-tag">대표번호</span>}
                  {p.calls > 0 && <span className="ct-tag">{`전화 ${p.calls}`}</span>}
                  {p.blocked && <span className="ct-tag is-bad">차단됨</span>}
                  {p.known && <span className="ct-tag">주소록에 있음</span>}
                </span>
              </button>
            </li>
          ))}
          {shown.length === 0 && <li className="ct-muted ct-none">찾는 번호가 없습니다.</li>}
        </ul>
      )}
    </section>
  );
}

const reason = (e: unknown) => (e instanceof ApiError ? e.message : '요청을 처리할 수 없습니다.');

function AddForm({ scheduleId, peerKey, companies, onDone, onCancel }: {
  scheduleId: number;
  peerKey: string;
  companies: CompanyGroup[];
  onDone: (p: PersonDetail) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState('');
  const [role, setRole] = useState('');
  const [pick, setPick] = useState<CompanyPick>(() => firstPick(companies, ''));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = () => {
    setBusy(true);
    setError(null);
    addPeer(scheduleId, peerKey, { name: name.trim(), role_title: role.trim(), ...companyBody(pick) }).then(onDone, (e: unknown) => {
      setError(reason(e));
      setBusy(false);
    });
  };
  return (
    <form className="ct-ib-form" aria-label="주소록에 넣기" onSubmit={(e) => (e.preventDefault(), submit())}>
      <p className="ct-hint">이 번호로 지금 프로젝트의 주소록에 사람을 만듭니다. 번호는 서버가 넣습니다.</p>
      <div className="ct-ib-fields">
        <label className="ct-fld-label">
          <span className="ct-label">이름</span>
          <input className="ct-input" aria-label="이름" maxLength={100} autoFocus value={name} disabled={busy} onChange={(e) => setName(e.target.value)} />
        </label>
        <label className="ct-fld-label">
          <span className="ct-label">담당</span>
          <input className="ct-input" aria-label="담당" maxLength={100} value={role} disabled={busy} onChange={(e) => setRole(e.target.value)} />
        </label>
        <CompanyChoice companies={companies} value={pick} onChange={setPick} disabled={busy} />
      </div>
      {error && (
        <p className="ct-error" role="alert">
          {error}
        </p>
      )}
      <div className="ct-actions">
        <span className="ct-gap" />
        <Button onClick={onCancel} disabled={busy}>
          취소
        </Button>
        <Button type="submit" variant="primary" disabled={busy || !name.trim()}>
          넣기
        </Button>
      </div>
    </form>
  );
}

function BlockAsk({ number, onBlock, onCancel }: { number: string; onBlock: (reason: string) => Promise<void>; onCancel: () => void }) {
  const [why, setWhy] = useState('');
  const [busy, setBusy] = useState(false);
  return (
    <div className="ct-confirm" role="group" aria-label="차단 확인">
      <p className="ct-confirm-text">{`${number}을(를) 차단합니다. 걸려 오는 전화와 들어오는 문자를 받지 않습니다(모든 프로젝트). 설정 → 알림 연결에서 풀 수 있습니다.`}</p>
      <label className="ct-fld-label">
        <span className="ct-label">까닭</span>
        <input className="ct-input" aria-label="까닭" maxLength={200} autoFocus value={why} disabled={busy} onChange={(e) => setWhy(e.target.value)} />
      </label>
      <div className="ct-actions">
        <span className="ct-gap" />
        <Button onClick={onCancel} disabled={busy}>
          취소
        </Button>
        <Button variant="danger" disabled={busy} onClick={() => (setBusy(true), void onBlock(why.trim()).finally(() => setBusy(false)))}>
          차단하기
        </Button>
      </div>
    </div>
  );
}

/** 오른쪽 칸: 한 모르는 번호의 줄(오래된 것부터) · [주소록에 넣기] · [차단](관리자). */
export function UnknownPane({ scheduleId, peerKey, companies, isAdmin, onChanged, onOpenPerson }: {
  scheduleId: number;
  peerKey: string;
  companies: CompanyGroup[];
  isAdmin: boolean;
  onChanged: () => void;
  onOpenPerson: (id: number) => void;
}) {
  const [detail, setDetail] = useState<UnknownDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [doing, setDoing] = useState<'add' | 'block' | null>(null);
  const [note, setNote] = useState<{ text: string; person: number | null } | null>(null);
  const [n, setN] = useState(0);
  useEffect(() => {
    let live = true;
    getUnknownPeer(peerKey, scheduleId).then(
      (d) => live && (setDetail(d), setError(null)),
      (e: unknown) => live && setError(reason(e)),
    );
    return () => {
      live = false;
    };
  }, [peerKey, n, scheduleId]);
  const refresh = () => (setN((x) => x + 1), onChanged());
  const block = (why: string) =>
    blockPeer(peerKey, why).then(
      () => (setDoing(null), setNote({ text: '차단했습니다.', person: null }), refresh()),
      (e: unknown) => setNote({ text: reason(e), person: null }),
    );
  if (error) return <p className="ct-error ct-pad" role="alert">{error}</p>;
  if (!detail) return <p className="ct-muted ct-pad">읽는 중…</p>;
  return (
    <section className="ct-ib-pane" aria-label={`모르는 번호 ${detail.number_masked}`}>
      <div className="ct-ib-head">
        <h2 className="ct-ib-title ct-num">{detail.number_masked}</h2>
        {detail.blocked && <span className="ct-tag is-bad">차단됨</span>}
        {detail.known && <span className="ct-tag">주소록에 있음</span>}
        <div className="ct-ib-acts">
          {!detail.known && <Button onClick={() => setDoing('add')} disabled={doing !== null}>주소록에 넣기</Button>}
          {isAdmin && !detail.blocked && <Button variant="danger" onClick={() => setDoing('block')} disabled={doing !== null}>차단</Button>}
        </div>
      </div>
      {!isAdmin && !detail.blocked && <p className="ct-hint">차단은 관리자만 할 수 있습니다.</p>}
      {note && (
        <p className="ct-ib-done" role="status">
          {note.text}
          {note.person !== null && <button type="button" className="ct-link" onClick={() => onOpenPerson(note.person as number)}>사람 보기</button>}
        </p>
      )}
      {doing === 'add' && (
        <AddForm scheduleId={scheduleId} peerKey={peerKey} companies={companies} onCancel={() => setDoing(null)}
          onDone={(p) => (setDoing(null), setNote({ text: `주소록에 넣었습니다 — ${p.name ?? ''}`, person: typeof p.id === 'number' ? p.id : null }), refresh())} />
      )}
      {doing === 'block' && <BlockAsk number={detail.number_masked} onBlock={block} onCancel={() => setDoing(null)} />}
      <p className="ct-hint">
        {detail.lines.some((l) => l.caller_class === 'shared')
          ? '대표번호 — 이 프로젝트 주소록에서 여러 사람이 이 번호를 씁니다. 받은 통화를 한 사람으로 정하지 않고 여기 모읍니다.'
          : '주소록에 없는 번호와 주고받은 문자·통화입니다. 일정은 알려 주지 않았습니다.'}
      </p>
      <ol className="ct-ib-lines" aria-label="주고받은 줄">
        {detail.lines.map((l) => <PeerLineItem key={`${l.kind}-${l.id}`} l={l} />)}
      </ol>
    </section>
  );
}
