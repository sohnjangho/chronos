// 왼쪽 분류: 일정 › 전체 · 분야별(개수). 문서·보고서·복사본은 묶음 2·3 이라 두지 않는다.
import { domainLabel, type TreeSchedule } from './exApi';

interface Props {
  schedules: TreeSchedule[];
  /** 고른 분야(null = 전체). */
  domain: string | null;
  onDomain(domain: string | null): void;
}

function Item({ label, count, on, onClick }: { label: string; count: number; on: boolean; onClick(): void }) {
  return (
    <li>
      <button type="button" className="ex-nav" aria-pressed={on} onClick={onClick}>
        <span className="ex-ellipsis" title={label}>
          {label}
        </span>{' '}
        <span className="ex-count">{count}</span>
      </button>
    </li>
  );
}

export default function Tree({ schedules, domain, onDomain }: Props) {
  const counts = new Map<string, number>();
  for (const s of schedules) counts.set(s.domain, (counts.get(s.domain) ?? 0) + 1);
  return (
    <nav className="ex-tree" aria-label="일정 분류">
      <div className="ex-grp">일정</div>
      <ul className="ex-navs">
        <Item label="전체" count={schedules.length} on={domain === null} onClick={() => onDomain(null)} />
        {[...counts].map(([d, n]) => (
          <Item key={d} label={domainLabel(d)} count={n} on={domain === d} onClick={() => onDomain(d)} />
        ))}
      </ul>
    </nav>
  );
}
