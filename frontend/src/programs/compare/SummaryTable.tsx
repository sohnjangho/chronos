// 여러 안 요약 표(현재 · Plan · 열린 복사본). 줄을 누르면 그 안이 비교가 된다. 값은 모두 서버 계산값.
// 가로로 좁으면 표 안에서만 밀리고 「안」 칸은 고정이다.
import type { KeyboardEvent } from 'react';
import Badge from '../../shared/ui/Badge';
import type { Peak, SideOut } from './compareApi';
import { deltaText, dot, floatText, toneOf } from './rows';

const peakText = (p: Peak | null) => (p ? `${p.name} ${p.need}/${p.capacity}` : '—');

function Row({ s, base, other, onPick }: { s: SideOut; base: string; other: string | null; onPick(ref: string): void }) {
  const role = s.ref === base ? 'base' : s.ref === other ? 'other' : null;
  const pickable = s.ref !== base;
  const pick = () => pickable && onPick(s.ref);
  const onKey = (e: KeyboardEvent) => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    e.preventDefault();
    pick();
  };
  return (
    <tr
      className={`${role ? `is-${role}` : ''}${pickable ? ' is-pickable' : ''}`}
      aria-current={role === 'other' ? 'true' : undefined}
      tabIndex={pickable ? 0 : undefined}
      onClick={pick}
      onKeyDown={onKey}
    >
      <td className="cmp-sticky cmp-plan">
        <span className={`cmp-swatch is-${role ?? 'none'}`} aria-hidden="true" />
        {s.label}
        {/* 반영된 복사본은 늘 낡으므로 낡음 배지를 띄우지 않는다. */}
        {s.stale && s.status !== 'applied' && <Badge tone="warning">기준 일정이 바뀌었습니다</Badge>}
        {s.status === 'submitted' && <Badge tone="info">승인 대기</Badge>}
      </td>
      <td className="cmp-num">{dot(s.finish)}</td>
      <td className={`cmp-num ${toneOf(s.plan_delta)}`}>{deltaText(s.plan_delta)}</td>
      <td className={`cmp-num ${toneOf(s.deadline_float, true)}`}>{floatText(s.deadline_float)}</td>
      <td className="cmp-num">{s.critical_count}</td>
      <td className="cmp-num">
        <span className={s.violations ? 'is-bad' : ''}>{s.violations}</span>
        {s.uncheckable > 0 && <span className="cmp-muted"> · </span>}
        {s.uncheckable > 0 && <span className="cmp-muted">자동 점검 안 됨 {s.uncheckable}</span>}
      </td>
      <td className={`cmp-num ${s.peak && s.peak.need > s.peak.capacity ? 'is-bad' : ''}`}>{peakText(s.peak)}</td>
      <td className="cmp-changes" title={s.changes.join('\n') || undefined}>
        {s.changes.join(' · ')}
      </td>
    </tr>
  );
}

interface Props {
  sides: SideOut[];
  base: string;
  other: string | null;
  onPick(ref: string): void;
}

export default function SummaryTable({ sides, base, other, onPick }: Props) {
  return (
    <div className="cmp-sum">
      <table className="cmp-table" aria-label="여러 안 요약">
        <thead>
          <tr>
            <th className="cmp-sticky">안</th>
            <th className="cmp-num">준공</th>
            <th className="cmp-num">Plan 대비</th>
            <th className="cmp-num">기한 여유</th>
            <th className="cmp-num">크리티컬 수</th>
            <th className="cmp-num">조건 위반</th>
            <th className="cmp-num">자원 최고 부하</th>
            <th>바꾸는 것</th>
          </tr>
        </thead>
        <tbody>
          {sides.map((s) => (
            <Row key={s.ref} s={s} base={base} other={other} onPick={onPick} />
          ))}
        </tbody>
      </table>
    </div>
  );
}
