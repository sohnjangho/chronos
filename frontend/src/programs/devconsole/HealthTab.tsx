// 시스템 진단(시안 A — 2026-11-24 PM 결정): 맨 위 판정 한 줄 + 개수 칩(거르개) · 찾기 · 접속/기기/실행 중 턴 · 마지막 점검 · 「다시 점검」,
// 「먼저 볼 것」(실패 → 확인 필요 → 모름, 줄마다 할 일, 누르면 지금 상태 · 영향 · 기계 출력), 그 아래 영역 4묶음 2열에 한 항목 한 줄.
// 서버 응답(/api/devconsole/health)은 그대로 — 대응표는 healthChecks.ts. 콘솔은 진단을 다시 돌리거나 제공사를 부르지 않는다(읽기만).
// 실행 중 턴의 「강제 중단」은 예전 그대로(/api/devconsole/turns/{id}/stop).
import { type ReactNode, useCallback, useEffect, useMemo, useState } from 'react';
import { ApiError } from '../../shared/api';
import Badge from '../../shared/ui/Badge';
import { devApi, type HealthOut } from './devApi';
import { AREAS, buildChecks, type Check, type CheckState, firstLook, STATES } from './healthChecks';
import { Dot, GroupRow, PinnedRow, timeOf, TONE, TurnsRow } from './HealthRows';

type Filter = CheckState | 'all';
type Area = (typeof AREAS)[number] & { rows: Check[]; all: Check[] };

function haystack(c: Check): string {
  return [c.name, c.tech ?? '', c.summary, c.todo ?? '', ...c.fields.flatMap((g) => g.rows.flat())].join(' ').toLowerCase();
}

/** 맨 위 요약 줄: 판정 · 상태 개수 칩(누르면 거름) · 접속/기기/실행 중 턴 · 찾기. */
function SummaryStrip({ graded, filter, onFilter, health, query, onQuery }: {
  graded: Check[]; filter: Filter; onFilter(f: Filter): void; health: HealthOut; query: string; onQuery(q: string): void;
}) {
  const count = (s: CheckState) => graded.filter((c) => c.state === s).length;
  const fails = count('fail');
  const toLook = count('check') + count('unknown');
  const [tone, text]: [CheckState, string] = fails ? ['fail', `${fails}개가 멈췄습니다`] : toLook ? ['check', `확인할 것 ${toLook}개`] : ['ok', '모두 정상'];
  const p = health.presence;
  const live = [p ? `접속 중 ${p.online_users}명 · 기기 ${p.online_devices}대` : null, `실행 중 턴 ${health.active_turns.length}건`].filter(Boolean).join(' · ');
  return (
    <div className="dc-hl-strip" role="group" aria-label="요약">
      <span className="dc-hl-verdict">
        <Dot state={tone} />
        {text}
      </span>
      <div className="dc-chip-bar" role="group" aria-label="상태로 거르기">
        <button type="button" className={`dc-hl-chip${filter === 'all' ? ' is-on' : ''}`} aria-pressed={filter === 'all'} onClick={() => onFilter('all')}>
          전체 <b>{graded.length}</b>
        </button>
        {STATES.map((s) => (
          <button key={s.id} type="button" className={`dc-hl-chip${filter === s.id ? ' is-on' : ''}`} aria-pressed={filter === s.id} onClick={() => onFilter(s.id)}>
            <Dot state={s.id} />
            {s.label} <b>{count(s.id)}</b>
          </button>
        ))}
      </div>
      <span className="dc-hl-grow" />
      <span className="dc-muted dc-hl-live">{live}</span>
      <input type="search" className="dc-search" aria-label="점검 항목 찾기" placeholder="점검 항목 찾기 (예: 문자, 음성)" value={query} onChange={(e) => onQuery(e.target.value)} />
    </div>
  );
}

/** 영역 묶음 하나: 머리(이름 · 문제 개수 · 항목 수)와 한 항목 한 줄. 지금 접속 · 실행 중 묶음은 실행 중 턴 줄([강제 중단])을 붙인다. */
function AreaGroup({ a, now, isOpen, onToggle, turns }: {
  a: Area; now: Date; isOpen(key: string): boolean; onToggle(key: string): void; turns: ReactNode;
}) {
  const bad = STATES.filter((s) => s.id !== 'ok').map((s) => [s, a.all.filter((c) => c.state === s.id).length] as const).filter(([, k]) => k > 0);
  return (
    <section className="dc-hl-group" aria-label={a.label}>
      <header>
        <h3>{a.label}</h3>
        {bad.map(([s, k]) => (
          <Badge key={s.id} tone={TONE[s.id]} className={s.id === 'unknown' ? 'dc-hl-unknown' : undefined}>{`${s.label} ${k}`}</Badge>
        ))}
        <span className="dc-muted dc-hl-n">{`${a.all.length}개`}</span>
      </header>
      <ul className="dc-hl-list">
        {a.rows.map((c) => (
          <GroupRow key={c.id} c={c} now={now} open={isOpen(`grp:${c.id}`)} onToggle={() => onToggle(`grp:${c.id}`)} />
        ))}
        {turns}
      </ul>
    </section>
  );
}

function useHealth() {
  const [data, setData] = useState<{ health: HealthOut; at: Date } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [stoppingId, setStoppingId] = useState<number | null>(null);
  const load = useCallback(async () => {
    setBusy(true);
    try {
      const health = await devApi.health();
      setData({ health, at: new Date() });
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '시스템 진단 정보를 불러오지 못했습니다.');
    } finally {
      setBusy(false);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  async function stopTurn(chatId: number) {
    setStoppingId(chatId);
    try {
      await devApi.stopTurn(chatId);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '실행 중단에 실패했습니다.');
    } finally {
      setStoppingId(null);
    }
  }
  return { data, error, busy, stoppingId, load, stopTurn };
}

export default function HealthTab() {
  const { data, error, busy, stoppingId, load, stopTurn } = useHealth();
  const [filter, setFilter] = useState<Filter>('all');
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState<Set<string>>(() => new Set());
  const checks = useMemo(() => (data ? buildChecks(data.health, data.at) : []), [data]);
  const toggle = (key: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  const q = query.trim().toLowerCase();
  const shown = (c: Check) => (filter === 'all' || c.state === filter) && (!q || haystack(c).includes(q));
  const pinned = firstLook(checks).filter(shown);
  const turnsCheck = checks.find((c) => c.id === 'active_turns');
  const showTurns = !!turnsCheck && shown(turnsCheck);
  const areas: Area[] = AREAS.map((a) => ({ ...a, rows: checks.filter((c) => c.area === a.id && c.id !== 'active_turns' && shown(c)), all: checks.filter((c) => c.area === a.id) }))
    .filter((a) => a.rows.length > 0 || (a.id === 'live' && showTurns));

  return (
    <div className="dc-scroll dc-hl">
      <div className="dc-hl-head">
        <div>
          <h2 className="dc-cat-h2">시스템 진단</h2>
          <p className="dc-muted">AI · 검색, 자료, 바깥 연락이 지금 제대로 도는지 봅니다. 문제가 있는 것부터 위에 둡니다.</p>
        </div>
        <div className="dc-hl-actions">
          {data && <span className="dc-muted">{`마지막 점검 ${timeOf(data.at)}`}</span>}
          <button type="button" className="dc-btn" disabled={busy} onClick={() => void load()}>
            {busy ? '점검 중…' : '다시 점검'}
          </button>
        </div>
      </div>
      {error && (
        <p className="dc-error" role="alert">
          {error}
        </p>
      )}
      {!data && !error && <p className="dc-empty">시스템 상태를 점검하는 중…</p>}
      {data && <SummaryStrip graded={checks.filter((c) => c.state !== 'info')} filter={filter} onFilter={setFilter} health={data.health} query={query} onQuery={setQuery} />}
      {pinned.length > 0 && (
        <section className="dc-hl-pinned" aria-label="먼저 볼 것">
          <header>
            <Badge tone="danger">{`먼저 볼 것 ${pinned.length}`}</Badge>
            <span className="dc-muted">실패 → 확인 필요 → 모름 순서</span>
          </header>
          <ul className="dc-hl-list">
            {pinned.map((c) => (
              <PinnedRow key={c.id} c={c} open={open.has(`pin:${c.id}`)} onToggle={() => toggle(`pin:${c.id}`)} />
            ))}
          </ul>
        </section>
      )}
      {data && areas.length === 0 && <p className="dc-empty">맞는 점검 항목이 없습니다.</p>}
      {data && areas.length > 0 && (
        <div className="dc-hl-groups" role="group" aria-label="영역 묶음">
          {areas.map((a) => (
            <AreaGroup key={a.id} a={a} now={data.at} isOpen={(k) => open.has(k)} onToggle={toggle}
              turns={a.id === 'live' && showTurns ? <TurnsRow turns={data.health.active_turns} stoppingId={stoppingId} onStop={(id) => void stopTurn(id)} /> : null} />
          ))}
        </div>
      )}
    </div>
  );
}
