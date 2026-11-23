// 요청 고르기 ▾: 최근 30개 요청을 날짜로 묶어 보이고, 요청 글·사용자 이름으로 찾는다. 열 때마다 목록을 다시 읽는다.
// Task 108: 실행 추적 탭에서는 종류 「대화 턴 | 연락」 — 연락은 최근 연락 기록(문자·카카오톡·통화)을 날짜로 묶고 이름·협력사·상태로 찾는다.
import { useEffect, useMemo, useRef, useState } from 'react';
import Badge from '../../shared/ui/Badge';
import { devApi, type OutreachList, type OutreachRow, type Turn } from './devApi';
import { dayGroup, hourMinute, status, tokens } from './format';
import { channelOf, starterOf, statusOf, whoOf } from './outreachText';

interface Props {
  turns: Turn[] | null;
  current: Turn | null;
  onOpen(): void;
  onPick(id: number): void;
  /** 실행 추적 탭에서만: 연락 기록 고르기. */
  outreach?: { current: OutreachRow | null; onPick(row: OutreachRow): void };
}

type Kind = 'turn' | 'outreach';

function groupByDay<T>(items: T[], at: (x: T) => string): [string, T[]][] {
  const out = new Map<string, T[]>();
  for (const t of items) {
    const day = dayGroup(at(t));
    out.set(day, [...(out.get(day) ?? []), t]);
  }
  return [...out];
}

const outreachText = (r: OutreachRow) =>
  `${whoOf(r)} ${statusOf(r.status).label} ${channelOf(r)} ${starterOf(r)} ${r.schedule_name ?? ''}`.toLowerCase();

function ContactChoice({ r, current, onPick }: { r: OutreachRow; current: boolean; onPick(): void }) {
  const s = statusOf(r.status);
  return (
    <li>
      <button type="button" className="dc-pick-item" aria-current={current || undefined} onClick={onPick}>
        <span className="dc-pick-req">{whoOf(r)}</span>
        <span className="dc-pick-meta">
          <Badge tone={s.tone}>{s.label}</Badge>
          <span>{`${channelOf(r)} · ${starterOf(r)} · ${hourMinute(r.at)} · 사건 ${r.events}`}</span>
        </span>
      </button>
    </li>
  );
}

/** 연락 기록 목록(날짜 묶음 · 찾기 · 상한 밖 표시). */
function OutreachChoices({ list, query, current, onPick }: { list: OutreachList | null; query: string; current: OutreachRow | null; onPick(r: OutreachRow): void }) {
  const q = query.trim().toLowerCase();
  const found = (list?.items ?? []).filter((r) => !q || outreachText(r).includes(q));
  return (
    <>
      <p className="dc-muted">{`최근 ${list?.items.length ?? 0}개 연락${q ? ` 중 ${found.length}개` : ''}`}</p>
      <div className="dc-pick-list">
        {list === null && <p className="dc-muted">불러오는 중…</p>}
        {list?.items.length === 0 && <p className="dc-muted">아직 연락 기록이 없습니다.</p>}
        {list !== null && list.items.length > 0 && found.length === 0 && <p className="dc-muted">찾는 연락이 없습니다.</p>}
        {groupByDay(found, (r) => r.at).map(([day, rows]) => (
          <section key={day}>
            <h4 className="dc-pick-day">{day}</h4>
            <ul>
              {rows.map((r) => (
                <ContactChoice key={`${r.kind}/${r.id}`} r={r} current={current?.kind === r.kind && current.id === r.id} onPick={() => onPick(r)} />
              ))}
            </ul>
          </section>
        ))}
        {list?.more && <p className="dc-muted">{`더 오래된 기록이 있습니다 — 최근 ${list.limit}개만 보입니다.`}</p>}
      </div>
    </>
  );
}

function KindSwitch({ kind, onKind }: { kind: Kind; onKind(k: Kind): void }) {
  return (
    <div className="dc-pick-filters" role="radiogroup" aria-label="기록 종류">
      {(
        [
          ['turn', '대화 턴'],
          ['outreach', '연락'],
        ] as const
      ).map(([id, label]) => (
        <button key={id} type="button" role="radio" className={`dc-mode-btn${kind === id ? ' is-on' : ''}`} aria-checked={kind === id} onClick={() => onKind(id)}>
          {label}
        </button>
      ))}
    </div>
  );
}

function Choice({ t, current, onPick }: { t: Turn; current: boolean; onPick(): void }) {
  const s = status(t.status);
  return (
    <li>
      <button type="button" className="dc-pick-item" aria-current={current || undefined} onClick={onPick}>
        <span className="dc-pick-req">{t.request || '(글 없음)'}</span>
        <span className="dc-pick-meta">
          <Badge tone={s.tone}>{s.label}</Badge>
          <span>{`${t.user_name} · ${hourMinute(t.started_at)} · 토큰 ${tokens(t.tokens)} · 모델 호출 ${t.llm_calls}`}</span>
        </span>
      </button>
    </li>
  );
}

type StatusFilter = 'all' | 'failed' | 'running';

interface TurnChoicesProps {
  turns: Turn[] | null;
  found: Turn[];
  query: string;
  statusFilter: StatusFilter;
  onFilter(f: StatusFilter): void;
  current: Turn | null;
  onPick(id: number): void;
}

function TurnChoices({ turns, found, query, statusFilter, onFilter, current, onPick }: TurnChoicesProps) {
  return (
    <>
      <div className="dc-pick-filters" role="radiogroup" aria-label="요청 상태 필터">
        {(
          [
            ['all', '전체'],
            ['failed', '실패·중단'],
            ['running', '실행 중'],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            role="radio"
            className={`dc-mode-btn${statusFilter === id ? ' is-on' : ''}`}
            aria-checked={statusFilter === id}
            onClick={() => onFilter(id)}
          >
            {label}
          </button>
        ))}
      </div>
      <p className="dc-muted">{`최근 ${turns?.length ?? 0}개 요청${query.trim() || statusFilter !== 'all' ? ` 중 ${found.length}개` : ''}`}</p>
      <div className="dc-pick-list">
        {turns === null && <p className="dc-muted">불러오는 중…</p>}
        {turns?.length === 0 && <p className="dc-muted">아직 기록된 요청이 없습니다.</p>}
        {turns !== null && turns.length > 0 && found.length === 0 && <p className="dc-muted">찾는 요청이 없습니다.</p>}
        {groupByDay(found, (t) => t.started_at).map(([day, list]) => (
          <section key={day}>
            <h4 className="dc-pick-day">{day}</h4>
            <ul>
              {list.map((t) => (
                <Choice key={t.turn_id} t={t} current={t.turn_id === current?.turn_id} onPick={() => onPick(t.turn_id)} />
              ))}
            </ul>
          </section>
        ))}
      </div>
    </>
  );
}

export default function TurnPicker({ turns, current, onOpen, onPick, outreach }: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [kind, setKind] = useState<Kind>('turn');
  const [contacts, setContacts] = useState<OutreachList | null>(null);
  const showing: Kind = outreach ? kind : 'turn';
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => !root.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener('pointerdown', away);
    return () => document.removeEventListener('pointerdown', away);
  }, [open]);

  const found = useMemo(() => {
    const q = query.trim().toLowerCase();
    let list = turns ?? [];
    if (statusFilter === 'failed') {
      list = list.filter((t) => t.status === 'failed' || t.status === 'stopped');
    } else if (statusFilter === 'running') {
      list = list.filter((t) => t.status === 'running');
    }
    return q ? list.filter((t) => `${t.request} ${t.user_name}`.toLowerCase().includes(q)) : list;
  }, [turns, query, statusFilter]);

  /** 연락 목록은 그 종류를 고를 때마다 다시 읽는다. */
  const loadContacts = () => {
    setContacts(null);
    devApi.outreachList().then(setContacts, () => setContacts({ items: [], more: false, limit: 0 }));
  };
  const switchKind = (k: Kind) => {
    setKind(k);
    setQuery('');
    if (k === 'outreach') loadContacts();
  };
  /** 열 때마다 목록을 다시 읽고 찾기 글을 비운다(연락을 보고 있었으면 연락 목록으로 연다). */
  const toggle = () => {
    if (!open) {
      onOpen();
      setQuery('');
      setStatusFilter('all');
      setKind(outreach?.current ? 'outreach' : 'turn');
      if (outreach?.current) loadContacts();
    }
    setOpen(!open);
  };
  /** 닫고 초점을 [요청: …] 단추로 돌린다(Esc·고르기). */
  const close = () => {
    setOpen(false);
    trigger.current?.focus();
  };
  const pick = (id: number) => {
    close();
    onPick(id);
  };
  const pickContact = (r: OutreachRow) => {
    close();
    outreach?.onPick(r);
  };
  const shownContact = outreach?.current ?? null;
  const triggerText = shownContact
    ? `연락: ${whoOf(shownContact)} · ${channelOf(shownContact)}`
    : current
      ? `요청: ${current.request || '(글 없음)'}`
      : '요청 고르기';

  return (
    <div ref={root} className="dc-picker" onKeyDown={(e) => open && e.key === 'Escape' && close()}>
      <button ref={trigger} type="button" className="dc-pick-btn" aria-haspopup="dialog" aria-expanded={open} onClick={toggle} title={triggerText}>
        <span className="dc-ellipsis">{triggerText}</span>
        <span aria-hidden="true">▾</span>
      </button>
      {open && (
        <div className="dc-pick-pop" role="dialog" aria-label="요청 고르기">
          {outreach && <KindSwitch kind={showing} onKind={switchKind} />}
          <input
            type="search"
            className="dc-pick-search"
            aria-label={showing === 'turn' ? '요청 찾기' : '연락 찾기'}
            placeholder={showing === 'turn' ? '요청 글·사용자 이름으로 찾기' : '이름·협력사·상태·현장으로 찾기'}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            autoFocus
          />
          {showing === 'outreach' ? (
            <OutreachChoices list={contacts} query={query} current={shownContact} onPick={pickContact} />
          ) : (
            <TurnChoices turns={turns} found={found} query={query} statusFilter={statusFilter} onFilter={setStatusFilter} current={current} onPick={pick} />
          )}
        </div>
      )}
    </div>
  );
}
