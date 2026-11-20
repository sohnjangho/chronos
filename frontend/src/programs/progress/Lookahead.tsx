// 앞으로 3주(서버가 정한 Data Date ~ +20일): 시작 예정 · 종료 예정 · 선행 미완(막힌 시작).
// 막힌 까닭은 서버 글 그대로("선행 미완료: A, C · 선행 미착수: B").
import { md } from './format';
import type { ProgressData } from './progressApi';

interface Item {
  key: string;
  date: string;
  text: string;
  reason?: string;
}

function items(la: ProgressData['lookahead']): Item[] {
  const blocked = new Map(la.blocked.map((b) => [b.id, b.reason]));
  const starts = la.starts.map((s) => ({ key: `s-${s.id}`, date: s.date, text: `${s.id} ${s.name} 시작`, reason: blocked.get(s.id) }));
  const finishes = la.finishes.map((f) => ({ key: `f-${f.id}`, date: f.date, text: `${f.id} ${f.name} 종료` }));
  // 날짜 글(YYYY-MM-DD)의 차례로만 섞는다. 같은 날이면 서버 차례(시작 먼저).
  return [...starts, ...finishes].sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
}

function Tile({ n, label, warn }: { n: number; label: string; warn?: boolean }) {
  return (
    <div className={`pg-tile${warn && n > 0 ? ' is-warn' : ''}`}>
      <div className="pg-tile-n">{n}</div>
      <div className="pg-tile-l">{label}</div>
    </div>
  );
}

export default function Lookahead({ data }: { data: ProgressData }) {
  const la = data.lookahead;
  const list = items(la);
  return (
    <section className="pg-card pg-low-card" aria-label="앞으로 3주">
      <div className="pg-card-head">
        <h3 className="pg-card-title">앞으로 3주</h3>
        <span className="pg-muted">{`${md(la.from)} ~ ${md(la.to)}`}</span>
      </div>
      <div className="pg-tiles">
        <Tile n={la.starts.length} label="시작 예정" />
        <Tile n={la.finishes.length} label="종료 예정" />
        <Tile n={la.blocked.length} label="선행 미완" warn />
      </div>
      <ul className="pg-card-body pg-la-list" aria-label="앞으로 3주 작업">
        {list.length === 0 && <li className="pg-muted">앞으로 3주 안에 시작·종료할 작업이 없습니다.</li>}
        {list.map((it) => (
          <li key={it.key}>
            <span className="pg-la-date">{md(it.date)}</span>
            <span className="pg-la-text" title={it.text}>{it.text}</span>
            {it.reason && <span className="pg-la-reason" title={it.reason}>{it.reason}</span>}
          </li>
        ))}
      </ul>
    </section>
  );
}
