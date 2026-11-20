// 작업 금지 기간 띠(Task 40): 일정 달력의 금지 기간(calendar.blocked)마다 차트 전체 높이의 빗금 띠와 위 이름표
// 「<꼬리표> 작업 금지」. 그 꼬리표를 단 액티비티 줄에서는 띠를 더 진하게 칠한다. 날짜는 서버 값의 자리만 쓴다.
import { useId } from 'react';
import { labelWidth, ROW_H } from '../../shared/gantt/Bars';
import { barRect, type Scale } from '../../shared/gantt/scale';
import { dot } from '../../shared/schedule/format';
import type { GanttRow } from './grouping';

export type BlockedPeriod = { tag: string; start: string; finish: string };

const HATCH = 6;
export const blockedLabel = (tag: string) => `${tag} 작업 금지`;

/** 띠(줄 바탕 위·막대 아래). rows = 그리는 줄들(y 는 첫 줄을 0 으로), h = 그 줄들의 높이. */
export function BlockedBands({ blocked, scale, rows, h }: { blocked: BlockedPeriod[]; scale: Scale; rows: GanttRow[]; h: number }) {
  const hatch = `gt-hatch-${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`;
  if (!blocked.length) return null;
  return (
    <g className="gt-blocked">
      <defs>
        <pattern id={hatch} width={HATCH} height={HATCH} patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <rect className="gt-hatch-bg" width={HATCH} height={HATCH} />
          <line className="gt-hatch" x1={0} y1={0} x2={0} y2={HATCH} />
        </pattern>
      </defs>
      {blocked.map((b) => {
        const r = barRect(scale, b.start, b.finish);
        return (
          <g key={`${b.tag}-${b.start}`}>
            <rect className="gt-band" data-blocked={b.tag} x={r.x} y={0} width={r.w} height={h} fill={`url(#${hatch})`}>
              <title>{`작업 금지(${b.tag}) ${dot(b.start)}~${dot(b.finish)}`}</title>
            </rect>
            {rows.map((row, i) =>
              row.activity?.tags.includes(b.tag) ? (
                <rect key={row.key} className="gt-band-row" data-blocked-row={row.activity.id} x={r.x} y={i * ROW_H} width={r.w} height={ROW_H} />
              ) : null,
            )}
          </g>
        );
      })}
    </g>
  );
}

/**
 * 띠 위 이름표(막대 위에 그린다). y = 보이는 영역 맨 위(그리는 줄들 안에서) — 세로로 스크롤해도 이름표가 보인다.
 * 차트 오른쪽 끝을 넘으면 띠 오른쪽 끝에 맞춰 왼쪽으로 쓴다.
 */
export function BlockedLabels({ blocked, scale, y, total }: { blocked: BlockedPeriod[]; scale: Scale; y: number; total: number }) {
  return (
    <>
      {blocked.map((b) => {
        const r = barRect(scale, b.start, b.finish);
        const text = blockedLabel(b.tag);
        const fits = r.x + 4 + labelWidth(text) <= total;
        return (
          <text
            key={`${b.tag}-${b.start}`}
            className="gt-band-label"
            data-blocked-label={b.tag}
            x={fits ? r.x + 4 : r.x + r.w - 4}
            y={y + 14}
            textAnchor={fits ? undefined : 'end'}
          >
            {text}
          </text>
        );
      })}
    </>
  );
}
