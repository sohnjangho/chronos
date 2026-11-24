// 업데이트 내역(시안 U1 — 2026-11-24 PM 결정): 실서버에 올린 판마다 카드 하나(때 · 이름 · 짧은 커밋 · 「지금 실서버 판」 · 알림 띠 ·
// 새 기능 / 고침 / 안전 세 칸), 새것이 위, 날짜 묶음, 갈래 칩 · 찾기. 기록은 저장소의 deploy/updates.jsonl(서버가 읽어 준다).
// 때는 서울 시각으로 보인다(기록이 +09:00 으로 적힌다).
import { useEffect, useState } from 'react';
import { ApiError } from '../../shared/api';
import { devApi, type UpdateEntry, type UpdateItem, type UpdatesOut } from './devApi';

type Kind = 'added' | 'fixed' | 'safety';
const KINDS: { id: Kind; label: string }[] = [
  { id: 'added', label: '새 기능' },
  { id: 'fixed', label: '고침' },
  { id: 'safety', label: '안전' },
];
const TZ = 'Asia/Seoul';
const dayOf = (iso: string) => new Date(iso).toLocaleDateString('ko-KR', { timeZone: TZ, month: 'long', day: 'numeric', weekday: 'short' });
const timeOf = (iso: string) => new Date(iso).toLocaleTimeString('ko-KR', { timeZone: TZ, hour: 'numeric', minute: '2-digit' });

/** 짧은 커밋 비교: 한쪽이 다른 쪽으로 시작하면 같은 판(둘 다 7자 이상 — git 기본 짧은 꼴). */
const sameCommit = (a: string | null, b: string) =>
  a !== null && a.length >= 7 && b.length >= 7 && (a.startsWith(b) || b.startsWith(a));

const itemText = (i: UpdateItem) => `${i.text} ${i.note ?? ''}`.toLowerCase();

/** 찾기: 이름 · 커밋 · 알림이 맞으면 판 전체, 아니면 맞는 항목만. 하나도 없으면 null. */
function narrow(e: UpdateEntry, q: string, kind: Kind | 'all'): UpdateEntry | null {
  if (kind !== 'all' && e[kind].length === 0) return null;
  if (!q) return e;
  if (`${e.title} ${e.commit} ${e.notice ?? ''}`.toLowerCase().includes(q)) return e;
  const out = { ...e, added: e.added.filter((i) => itemText(i).includes(q)), fixed: e.fixed.filter((i) => itemText(i).includes(q)), safety: e.safety.filter((i) => itemText(i).includes(q)) };
  const any = kind === 'all' ? out.added.length + out.fixed.length + out.safety.length : out[kind].length;
  return any > 0 ? out : null;
}

function Card({ e, live, kind }: { e: UpdateEntry; live: boolean; kind: Kind | 'all' }) {
  const counts = KINDS.filter((k) => e[k.id].length > 0).map((k) => `${k.label} ${e[k.id].length}`).join(' · ');
  const cols = kind === 'all' ? KINDS : KINDS.filter((k) => k.id === kind);
  return (
    <article className={`dc-up-card${live ? ' is-live' : ''}`} aria-label={`${timeOf(e.at)} ${e.title}`}>
      <div className="dc-up-head">
        <span className="dc-up-time">{timeOf(e.at)}</span>
        <h4 className="dc-up-title">{e.title}</h4>
        <code>{e.commit}</code>
        {live && <span className="dc-up-live">지금 실서버 판</span>}
        <span className="dc-up-grow" />
        <span className="dc-muted">{counts || '바뀐 점 기록 없음'}</span>
      </div>
      {e.notice && (
        <p className="dc-up-notice" role="note">
          {e.notice}
        </p>
      )}
      <div className={`dc-up-kinds${cols.length === 1 ? ' is-one' : ''}`}>
        {cols.map((k) => (
          <div key={k.id} className="dc-up-kind">
            <h5 className={`is-${k.id}`}>
              <span className="dc-up-dot" aria-hidden="true" />
              {k.label}
            </h5>
            {e[k.id].length === 0 ? (
              <p className="dc-muted">없음</p>
            ) : (
              <ul aria-label={k.label}>
                {e[k.id].map((i, n) => (
                  <li key={n}>
                    {i.text}
                    {i.note && <small>{i.note}</small>}
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>
    </article>
  );
}

export default function UpdatesTab() {
  const [data, setData] = useState<UpdatesOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [kind, setKind] = useState<Kind | 'all'>('all');
  const [query, setQuery] = useState('');

  useEffect(() => {
    let live = true;
    devApi
      .updates()
      .then((d) => live && setData(d))
      .catch((e: unknown) => live && setError(e instanceof ApiError ? e.message : '업데이트 내역을 불러오지 못했습니다.'));
    return () => {
      live = false;
    };
  }, []);

  const entries = data?.entries ?? [];
  const q = query.trim().toLowerCase();
  const shown = entries.map((e) => narrow(e, q, kind)).filter((e): e is UpdateEntry => e !== null);
  const days: { day: string; list: UpdateEntry[] }[] = [];
  for (const e of shown) {
    const day = dayOf(e.at);
    if (days.at(-1)?.day === day) days.at(-1)!.list.push(e);
    else days.push({ day, list: [e] });
  }
  const running = data?.running_commit ?? null;
  const known = entries.some((e) => sameCommit(running, e.commit));

  return (
    <div className="dc-scroll dc-up">
      <div className="dc-up-top">
        <div>
          <h2 className="dc-cat-h2">업데이트 내역</h2>
          <p className="dc-muted">실서버에 새 판을 올릴 때마다 무엇이 바뀌었는지 적습니다. 새것이 위.</p>
        </div>
        <div className="dc-up-tools">
          <div className="dc-chip-bar" role="group" aria-label="갈래로 거르기">
            <button type="button" className={`dc-hl-chip${kind === 'all' ? ' is-on' : ''}`} aria-pressed={kind === 'all'} onClick={() => setKind('all')}>
              전체
            </button>
            {KINDS.map((k) => (
              <button key={k.id} type="button" className={`dc-hl-chip${kind === k.id ? ' is-on' : ''}`} aria-pressed={kind === k.id} onClick={() => setKind(k.id)}>
                {`${k.label} ${entries.reduce((n, e) => n + e[k.id].length, 0)}`}
              </button>
            ))}
          </div>
          <input type="search" className="dc-search" aria-label="바뀐 점 찾기" placeholder="바뀐 점 찾기 (예: 전화, 로그인)" value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
      </div>

      {error && (
        <p className="dc-error" role="alert">
          {error}
        </p>
      )}
      {!data && !error && <p className="dc-empty">업데이트 내역을 읽는 중…</p>}
      {data && entries.length === 0 && <p className="dc-empty">아직 기록된 판이 없습니다. 실서버를 다시 시작할 때 한 줄씩 붙습니다.</p>}
      {data && entries.length > 0 && shown.length === 0 && <p className="dc-empty">맞는 판이 없습니다.</p>}

      {days.map((d) => (
        <section key={d.day} className="dc-up-day" aria-label={d.day}>
          <h3 className="dc-up-dayhead">{`${d.day} · ${d.list.length}판`}</h3>
          <div className="dc-up-feed">
            {d.list.map((e) => (
              <Card key={`${e.at}-${e.commit}`} e={e} live={sameCommit(running, e.commit)} kind={kind} />
            ))}
          </div>
        </section>
      ))}
      {data && shown.length > 0 && <p className="dc-up-end">이보다 앞선 판은 이 기록을 만들기 전이라 없습니다.</p>}

      {data && (
        <p className="dc-up-src">
          기록 파일 <code>deploy/updates.jsonl</code> · 실서버를 다시 시작할 때 한 판이 한 줄로 붙습니다(때 · 커밋 · 이름 · 바뀐 점). 「지금 실서버 판」은 서버가 켤 때 읽은 커밋과 맞는 줄입니다.
          {running === null ? ' 지금 실서버 커밋을 읽지 못했습니다.' : known ? '' : ` 지금 실서버 커밋 ${running} 은 기록에 없습니다.`}
        </p>
      )}
    </div>
  );
}
