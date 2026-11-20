// 비교판 막대 하나(서버 날짜 → shared/gantt 눈금 자리). OD 0 은 ◆. 색은 class(기준 is-base · 비교는 change 이름).
import Header from '../../shared/gantt/Header';
import { barRect, x, type Scale } from '../../shared/gantt/scale';
import type { RowCell } from './compareApi';
import { dot } from './rows';

export const ROW_H = 36;

interface Props {
  scale: Scale;
  cell: RowCell;
  /** 막대 위쪽 y 와 높이. */
  y: number;
  h: number;
  className: string;
  testId: string;
  /** 막대 제목 앞글(예 「작업 B — 기준」). */
  what: string;
}

export const cellText = (c: RowCell) => `${dot(c.start)} ~ ${dot(c.finish)} (OD ${c.od})`;

export default function Bar({ scale, cell, y, h, className, testId, what }: Props) {
  const r = barRect(scale, cell.start, cell.finish);
  const title = <title>{`${what} ${cellText(cell)}`}</title>;
  if (cell.od === 0) {
    const cx = r.x + scale.pxPerDay / 2;
    const cy = y + h / 2;
    const s = h / 2 + 1;
    return (
      <path className={`cmp-bar ${className}`} data-testid={testId} d={`M ${cx} ${cy - s} L ${cx + s} ${cy} L ${cx} ${cy + s} L ${cx - s} ${cy} Z`}>
        {title}
      </path>
    );
  }
  return (
    <rect className={`cmp-bar ${className}`} data-testid={testId} x={r.x} y={y} width={Math.max(r.w, 2)} height={h} rx={2}>
      {title}
    </rect>
  );
}

/** 막대가 차지하는 가로 범위(◆ 은 그 날 칸). 둘 다 없으면 null. */
export function extentOf(scale: Scale, cells: (RowCell | null)[]): { from: number; to: number } | null {
  const rs = cells.filter((c): c is RowCell => c !== null).map((c) => barRect(scale, c.start, c.finish));
  if (!rs.length) return null;
  return { from: Math.min(...rs.map((r) => r.x)), to: Math.max(...rs.map((r) => r.x + r.w)) };
}

/** 기한 세로선 자리: 그날 끝(간트차트와 같음). */
export const dueX = (scale: Scale, iso: string) => x(scale, iso) + scale.pxPerDay;

/** 글 폭 어림(11px 굵은 글: 한글 11 · 그 밖 7). */
const textW = (t: string) => [...t].reduce((n, ch) => n + (/[가-힣]/.test(ch) ? 11 : 7), 0);

/**
 * 날짜 머리(shared/gantt Header) + 기한 이름표. 이름표는 머리 아래 표시 띠에 겹쳐 그리고,
 * 차트 오른쪽을 넘으면 선 왼쪽에 붙인다(머리 밖으로 잘리지 않게).
 */
export function Axis({ scale, width, lines }: { scale: Scale; width: number; lines: { date: string; label: string }[] }) {
  return (
    <div className="cmp-axis">
      <Header scale={scale} />
      <svg className="gantt-svg cmp-duelabels" width={width} height={18} aria-hidden="true">
        {lines.map((l) => {
          const at = dueX(scale, l.date);
          const left = at + 3 + textW(l.label) > width;
          return (
            <text key={l.label} className="gantt-mark is-deadline" x={left ? at - 3 : at + 3} y={13} textAnchor={left ? 'end' : 'start'}>
              {l.label}
            </text>
          );
        })}
      </svg>
    </div>
  );
}
