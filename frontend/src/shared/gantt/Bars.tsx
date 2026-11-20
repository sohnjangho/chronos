// 간트 막대 조각(SVG). y 는 그 줄의 위쪽, 줄 높이는 ROW_H. 색은 gantt.css(토큰 변수)가 정한다.
// 간트·CPM·비교 판이 같이 쓴다. data-* 는 시험·내보내기·고치기가 막대를 찾는 이름이다.
import type { ReactNode, SVGProps } from 'react';
import './gantt.css';

export const ROW_H = 30;
const BAR_Y = 8;
const BAR_H = 12;

/** 줄 바탕(고른 줄 표시·누르기). */
export function Band({ y, w, className, ...rest }: { y: number; w: number; className?: string } & SVGProps<SVGRectElement>) {
  return <rect className={['gantt-band', className].filter(Boolean).join(' ')} x={0} y={y} width={w} height={ROW_H} {...rest} />;
}

interface BarProps extends Omit<SVGProps<SVGGElement>, 'x' | 'y' | 'id'> {
  id: string;
  x: number;
  w: number;
  y: number;
  critical?: boolean;
  /** 0~1. 막대 앞쪽을 진하게 채운다. */
  progress?: number;
  children?: ReactNode;
}

/** 일반 막대 + 진도 채움. children 은 막대 위에 겹칠 것(끌기 손잡이 등). */
export function Bar({ id, x, w, y, critical, progress = 0, children, ...g }: BarProps) {
  const tone = critical ? ' critical' : '';
  return (
    <g {...g}>
      <rect className={`gantt-bar${tone}`} data-bar={id} x={x} y={y + BAR_Y} width={Math.max(w, 1)} height={BAR_H} rx={2} />
      {progress > 0 && (
        <rect className={`gantt-progress${tone}`} data-progress={id} x={x} y={y + BAR_Y} width={w * Math.min(progress, 1)} height={BAR_H} rx={2} />
      )}
      {children}
    </g>
  );
}

/** 막대 오른쪽 끝의 끌기 손잡이(보이지 않는 넓은 칸 + 얇은 표시). */
export function EndHandle({ id, x, y, ...rest }: { id: string; x: number; y: number } & Omit<SVGProps<SVGRectElement>, 'x' | 'y' | 'id'>) {
  return <rect className="gantt-handle" data-resize={id} x={x - 4} y={y + BAR_Y - 2} width={8} height={BAR_H + 4} {...rest} />;
}

const diamond = (cx: number, cy: number, r: number) => `M ${cx} ${cy - r} L ${cx + r} ${cy} L ${cx} ${cy + r} L ${cx - r} ${cy} Z`;

/** 마일스톤 ◆. */
export function Milestone({ id, cx, y, critical }: { id: string; cx: number; y: number; critical?: boolean }) {
  return <path className={`gantt-ms${critical ? ' critical' : ''}`} data-ms={id} d={diamond(cx, y + ROW_H / 2, 6)} />;
}

/** 기한 ◇(조건의 날짜). */
export function Due({ id, cx, y, title }: { id: string; cx: number; y: number; title: string }) {
  return (
    <path className="gantt-due" data-due={id} d={diamond(cx, y + ROW_H / 2, 6)}>
      <title>{title}</title>
    </path>
  );
}

/** 묶음 줄의 얇은 요약 막대. */
export function Summary({ id, x, w, y }: { id: string; x: number; w: number; y: number }) {
  return <rect className="gantt-summary" data-summary={id} x={x} y={y + 12} width={Math.max(w, 1)} height={6} rx={3} />;
}

/** 막대 아래 가는 Actual 줄. */
export function ActualLine({ id, x, w, y }: { id: string; x: number; w: number; y: number }) {
  return <rect className="gantt-actual" data-actual={id} x={x} y={y + 22} width={Math.max(w, 2)} height={4} rx={1} />;
}

/** 막대 위 얇은 Plan 버전 자리(지금 일정과 다를 때). */
export function PlanMark({ id, x, w, y }: { id: string; x: number; w: number; y: number }) {
  return <rect className="gantt-planmark" data-planmark={id} x={x} y={y + 3} width={Math.max(w, 2)} height={3} />;
}

/** 여유 꼬리: 막대 끝(EF 다음 날 0시)부터 LF 끝까지, 막대 아래 가는 줄. */
export function FloatTail({ id, x, w, y, title }: { id: string; x: number; w: number; y: number; title: string }) {
  return (
    <rect className="gantt-float" data-float={id} x={x} y={y + 26} width={Math.max(w, 1)} height={2}>
      <title>{title}</title>
    </rect>
  );
}

/** 작업 금지 기간 음영(전체 높이). */
export function Blocked({ tag, x, w, h, title }: { tag: string; x: number; w: number; h: number; title: string }) {
  return (
    <rect className="gantt-blocked" data-blocked={tag} x={x} y={0} width={w} height={h}>
      <title>{title}</title>
    </rect>
  );
}

/** 점선 막대(미리 보기 이전 자리·끌기 중 새 자리). */
export function Ghost({ x, w, y, ...rest }: { x: number; w: number; y: number } & Omit<SVGProps<SVGRectElement>, 'x' | 'y'>) {
  return <rect className="gantt-ghost" x={x} y={y + BAR_Y} width={Math.max(w, 2)} height={BAR_H} rx={2} {...rest} />;
}

/** 자원 줄·자원 묶음 줄 안의 옅은 막대(겹치면 진해진다). */
export function LaneBar({ x, w, y, h = BAR_H, title, ...rest }: { x: number; w: number; y: number; h?: number; title: string } & Omit<SVGProps<SVGRectElement>, 'x' | 'y'>) {
  return (
    <rect className="gantt-lane" x={x} y={y} width={Math.max(w, 1)} height={h} rx={2} {...rest}>
      <title>{title}</title>
    </rect>
  );
}

/** 막대 옆 이름. */
export function Label({ x, y, text, tone }: { x: number; y: number; text: string; tone?: 'danger' }) {
  return (
    <text className={`gantt-label${tone ? ` is-${tone}` : ''}`} x={x} y={y + 19}>
      {text}
    </text>
  );
}

/** 세로선(Data Date·기한·오늘). */
export function VLine({ kind, x, h }: { kind: 'data' | 'deadline' | 'today'; x: number; h: number }) {
  return <line className={`gantt-vline is-${kind}`} data-vline={kind} x1={x} x2={x} y1={0} y2={h} />;
}

/** 달력상 주말 음영. */
export function Weekends({ days, pxPerDay, h }: { days: { date: string; x: number }[]; pxPerDay: number; h: number }) {
  return (
    <g className="gantt-weekends">
      {days.map((d) => (
        <rect key={d.date} className="gantt-weekend" data-weekend={d.date} x={d.x} y={0} width={pxPerDay} height={h} />
      ))}
    </g>
  );
}
