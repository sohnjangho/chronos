// 바뀜 기록: 보드 아래 얇은 띠(최근 몇 개 — 가정은 점선 「미리 보기」)와 「모두 보기」(버전마다 묶고 찾기). 들어옴·빠짐(까닭)·여유 줄어듦은
// 서버가 버전을 저장할 때 적은 차이 그대로다.
import { useState } from 'react';
import Badge from '../../shared/ui/Badge';
import { stamp } from './format';
import type { History, HistoryEntry } from './pointsApi';

const STRIP_MAX = 4;

function stripText(e: HistoryEntry): string {
  const came = e.new.length + e.more;
  const parts = [`들어옴 ${came}`, `빠짐 ${e.removed.length}`];
  if (e.tightened.length > 0) parts.push(`여유 줄어듦 ${e.tightened.length}`);
  return `${e.note ? `${e.note} · ` : ''}${parts.join(' · ')}`;
}

const changed = (e: HistoryEntry) => e.new.length + e.more + e.removed.length + e.tightened.length > 0;

export function HistoryStrip({ hist, open, onToggle }: { hist: History; open: boolean; onToggle(): void }) {
  const items = [...(hist.preview && changed(hist.preview) ? [hist.preview] : []), ...hist.versions.filter(changed)].slice(0, STRIP_MAX);
  return (
    <div className="pt-strip" role="group" aria-label="바뀜 기록">
      <b>바뀜 기록</b>
      <div className="pt-strip-items">
        {items.length === 0 && <span className="pt-muted">기록한 바뀜이 없습니다.</span>}
        {items.map((e) => (
          <span key={`${e.what_if}-${e.version}`} className={`pt-strip-item${e.what_if ? ' is-whatif' : ''}`} title={stripText(e)}>
            <Badge tone={e.what_if ? 'neutral' : 'info'}>{e.what_if ? '미리 보기' : `버전 ${e.version}`}</Badge>
            {stripText(e)}
          </span>
        ))}
      </div>
      <button type="button" className="pt-link" aria-expanded={open} onClick={onToggle}>
        {open ? '보드로' : '모두 보기'}
      </button>
    </div>
  );
}

function entryLines(e: HistoryEntry): { key: string; text: string; tone: string }[] {
  const tf = (b: number | undefined, t: number | undefined) => (b !== undefined && t !== undefined ? ` · 여유 ${b}일 → ${t}일` : t !== undefined ? ` · 여유 ${t}일` : '');
  return [
    ...e.new.map((c) => ({ key: `n-${c.activity_id}`, tone: 'is-in', text: `들어옴 · ${c.name}${c.became_critical ? ' · 크리티컬이 됨' : ''}${tf(c.before_tf, c.tf)}` })),
    ...(e.more > 0 ? [{ key: 'more', tone: 'is-in', text: `들어옴 · 그 밖 ${e.more}곳` }] : []),
    ...e.tightened.map((c) => ({ key: `t-${c.activity_id}`, tone: 'is-tight', text: `여유 줄어듦 · ${c.name}${tf(c.before_tf, c.tf)}` })),
    ...e.removed.map((r) => ({ key: `r-${r.activity_id}`, tone: 'is-out', text: `빠짐 · ${r.name} — ${r.label}${tf(r.before_tf, r.tf)}` })),
  ];
}

/** 「모두 보기」: 버전마다 묶은 바뀜 기록(찾기). 가정(미리 보기)은 점선. */
export function HistoryAll({ hist }: { hist: History }) {
  const [query, setQuery] = useState('');
  const q = query.trim().toLowerCase();
  const entries = [...(hist.preview ? [hist.preview] : []), ...hist.versions];
  const shown = entries
    .map((e) => ({ e, lines: entryLines(e).filter((l) => !q || l.text.toLowerCase().includes(q)) }))
    .filter(({ e, lines }) => !q || lines.length > 0 || e.note.toLowerCase().includes(q));
  return (
    <div className="pt-hist">
      <div className="pt-hist-find">
        <input type="search" className="pt-input" aria-label="바뀜 기록 찾기" placeholder="작업 이름·까닭으로 찾기" value={query} onChange={(e) => setQuery(e.target.value)} />
        <span className="pt-muted">{`버전 ${hist.versions.length}개${hist.preview ? ' · 가정 1' : ''}`}</span>
      </div>
      <div className="pt-hist-list">
        {shown.length === 0 && <p className="pt-muted">찾는 기록이 없습니다.</p>}
        {shown.map(({ e, lines }) => (
          <section key={`${e.what_if}-${e.version}`} className={`pt-hist-grp${e.what_if ? ' is-whatif' : ''}`} aria-label={e.what_if ? '미리 보기' : `버전 ${e.version}`}>
            <div className="pt-hist-h">
              <Badge tone={e.what_if ? 'neutral' : 'info'}>{e.what_if ? '미리 보기' : `버전 ${e.version}`}</Badge>
              <span className="pt-muted">{stamp(e.saved_at)}</span>
              {e.note && <b>{e.note}</b>}
              {e.count !== null && <span className="pt-muted">{`포인트 ${e.count}곳(크리티컬 ${e.critical ?? 0})`}</span>}
            </div>
            {!e.recorded ? (
              <p className="pt-muted pt-hist-empty">처음 계산한 버전이라 앞과 견준 기록이 없습니다.</p>
            ) : lines.length === 0 ? (
              <p className="pt-muted pt-hist-empty">관리 포인트는 그대로입니다.</p>
            ) : (
              <ul>
                {lines.map((l) => (
                  <li key={l.key} className={l.tone}>
                    {l.text}
                  </li>
                ))}
              </ul>
            )}
          </section>
        ))}
      </div>
    </div>
  );
}
