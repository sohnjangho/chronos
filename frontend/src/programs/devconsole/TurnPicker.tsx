// 요청 고르기 ▾: 최근 30개 요청을 날짜로 묶어 보이고, 요청 글·사용자 이름으로 찾는다. 열 때마다 목록을 다시 읽는다.
import { useEffect, useMemo, useRef, useState } from 'react';
import Badge from '../../shared/ui/Badge';
import type { Turn } from './devApi';
import { dayGroup, hourMinute, status, tokens } from './format';

interface Props {
  turns: Turn[] | null;
  current: Turn | null;
  onOpen(): void;
  onPick(id: number): void;
}

function groupByDay(turns: Turn[]): [string, Turn[]][] {
  const out = new Map<string, Turn[]>();
  for (const t of turns) {
    const day = dayGroup(t.started_at);
    out.set(day, [...(out.get(day) ?? []), t]);
  }
  return [...out];
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

export default function TurnPicker({ turns, current, onOpen, onPick }: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
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
    const list = turns ?? [];
    return q ? list.filter((t) => `${t.request} ${t.user_name}`.toLowerCase().includes(q)) : list;
  }, [turns, query]);

  /** 열 때마다 목록을 다시 읽고 찾기 글을 비운다. */
  const toggle = () => {
    if (!open) {
      onOpen();
      setQuery('');
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

  return (
    <div ref={root} className="dc-picker" onKeyDown={(e) => open && e.key === 'Escape' && close()}>
      <button ref={trigger} type="button" className="dc-pick-btn" aria-haspopup="dialog" aria-expanded={open} onClick={toggle} title={current?.request}>
        <span className="dc-ellipsis">{current ? `요청: ${current.request || '(글 없음)'}` : '요청 고르기'}</span>
        <span aria-hidden="true">▾</span>
      </button>
      {open && (
        <div className="dc-pick-pop" role="dialog" aria-label="요청 고르기">
          <input
            type="search"
            className="dc-pick-search"
            aria-label="요청 찾기"
            placeholder="요청 글·사용자 이름으로 찾기"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            autoFocus
          />
          <p className="dc-muted">{`최근 ${turns?.length ?? 0}개 요청${query.trim() ? ` 중 ${found.length}개` : ''}`}</p>
          <div className="dc-pick-list">
            {turns === null && <p className="dc-muted">불러오는 중…</p>}
            {turns?.length === 0 && <p className="dc-muted">아직 기록된 요청이 없습니다.</p>}
            {turns !== null && turns.length > 0 && found.length === 0 && <p className="dc-muted">찾는 요청이 없습니다.</p>}
            {groupByDay(found).map(([day, list]) => (
              <section key={day}>
                <h4 className="dc-pick-day">{day}</h4>
                <ul>
                  {list.map((t) => (
                    <Choice key={t.turn_id} t={t} current={t.turn_id === current?.turn_id} onPick={() => pick(t.turn_id)} />
                  ))}
                </ul>
              </section>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
