// 간트 막대 조각(SVG). y 는 그 줄의 위쪽, 줄 높이는 ROW_H. 색은 gantt.css(토큰 변수)가 정한다.
// 간트·CPM·비교 판이 같이 쓴다. data-* 는 시험·내보내기·고치기가 막대를 찾는 이름이다.
// 액티비티 줄은 두 칸이다(PM 결정 11-20): 위 = Plan, 아래 = 「Actual·예측」(실적 진하게 + 예측 옅게).
import type { ReactNode, SVGProps } from 'react';
import './gantt.css';

export const ROW_H = 30;
const BAR_H = 10;
/** 줄 안 두 칸의 위쪽: Plan 칸 · Actual·예측 칸. */
const LANE_Y = { plan: 4, track: 16 } as const;
export type Lane = keyof typeof LANE_Y;
/** 관계선이 닿는 높이(Actual·예측 칸 가운데). */
export const TRACK_MID = LANE_Y.track + BAR_H / 2;

/** 줄 바탕(고른 줄 표시·누르기). */
export function Band({ y, w, className, ...rest }: { y: number; w: number; className?: string } & SVGProps<SVGRectElement>) {
  return <rect className={['gantt-band', className].filter(Boolean).join(' ')} x={0} y={y} width={w} height={ROW_H} {...rest} />;
}

interface BarProps extends Omit<SVGProps<SVGGElement>, 'x' | 'y' | 'id' | 'title'> {
  id: string;
  x: number;
  w: number;
  y: number;
  /** 가리키면 보이는 글(층 이름과 서버 날짜). */
  title: string;
  children?: ReactNode;
}

/** Plan 막대(위 칸). children 은 막대 위에 겹칠 것(끌기 손잡이 등). */
export function Bar({ id, x, w, y, title, children, ...g }: BarProps) {
  return (
    <g {...g}>
      <rect className="gantt-bar" data-bar={id} x={x} y={y + LANE_Y.plan} width={Math.max(w, 1)} height={BAR_H} rx={2}>
        <title>{title}</title>
      </rect>
      {children}
    </g>
  );
}

interface TrackBarProps {
  id: string;
  x: number;
  w: number;
  y: number;
  kind: 'actual' | 'forecast';
  critical?: boolean;
  title: string;
}

/** 아래 칸의 막대: 실적(진하게, data-actual) 또는 예측(옅게, data-forecast — CPM 층이면 크리티컬 빨강). */
export function TrackBar({ id, x, w, y, kind, critical, title }: TrackBarProps) {
  const data = kind === 'actual' ? { 'data-actual': id } : { 'data-forecast': id };
  const cls = kind === 'actual' ? 'gantt-actualbar' : `gantt-forecast${critical ? ' critical' : ''}`;
  return (
    <rect className={cls} {...data} x={x} y={y + LANE_Y.track} width={Math.max(w, 2)} height={BAR_H} rx={2}>
      <title>{title}</title>
    </rect>
  );
}

/** Plan 막대 오른쪽 끝의 끌기 손잡이(보이지 않는 넓은 칸 + 얇은 표시). */
export function EndHandle({ id, x, y, ...rest }: { id: string; x: number; y: number } & Omit<SVGProps<SVGRectElement>, 'x' | 'y' | 'id'>) {
  return <rect className="gantt-handle" data-resize={id} x={x - 4} y={y + LANE_Y.plan - 2} width={8} height={BAR_H + 4} {...rest} />;
}

const diamond = (cx: number, cy: number, r: number) => `M ${cx} ${cy - r} L ${cx + r} ${cy} L ${cx} ${cy + r} L ${cx - r} ${cy} Z`;

interface MilestoneProps {
  id: string;
  cx: number;
  y: number;
  lane?: Lane;
  kind?: 'actual' | 'forecast';
  critical?: boolean;
  title: string;
}

/** 마일스톤 ◆: Plan 칸(data-ms) 또는 Actual·예측 칸(data-ms-track, 실적 is-actual · 예측 is-forecast). */
export function Milestone({ id, cx, y, lane = 'plan', kind, critical, title }: MilestoneProps) {
  const cls = ['gantt-ms', lane === 'plan' ? 'is-plan' : `is-${kind}`, critical ? 'critical' : ''].filter(Boolean).join(' ');
  const data = lane === 'plan' ? { 'data-ms': id } : { 'data-ms-track': id };
  return (
    <path className={cls} {...data} d={diamond(cx, y + LANE_Y[lane] + BAR_H / 2, 5)}>
      <title>{title}</title>
    </path>
  );
}

/** 마일스톤의 이전 자리 ◇ 점선 테두리(미리 보기). */
export function GhostMilestone({ cx, y, lane, ...rest }: { cx: number; y: number; lane: Lane } & Omit<SVGProps<SVGPathElement>, 'd' | 'y'>) {
  return <path className="gantt-ghost" d={diamond(cx, y + LANE_Y[lane] + BAR_H / 2, 5)} {...rest} />;
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

/** 여유 꼬리: 예측 막대 끝(EF 다음 날 0시)부터 LF 끝까지, 아래 칸 밑의 가는 줄. */
export function FloatTail({ id, x, w, y, title }: { id: string; x: number; w: number; y: number; title: string }) {
  return (
    <rect className="gantt-float" data-float={id} x={x} y={y + LANE_Y.track + BAR_H + 1} width={Math.max(w, 1)} height={2}>
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

/** 점선 막대(미리 보기 이전 자리·끌기 중 새 자리). lane: 어느 칸(Plan·Actual·예측)에. */
export function Ghost({ x, w, y, lane = 'plan', ...rest }: { x: number; w: number; y: number; lane?: Lane } & Omit<SVGProps<SVGRectElement>, 'x' | 'y'>) {
  return <rect className="gantt-ghost" x={x} y={y + LANE_Y[lane]} width={Math.max(w, 2)} height={BAR_H} rx={2} {...rest} />;
}

/** 자원 줄·자원 묶음 줄 안의 옅은 막대(겹치면 진해진다). */
export function LaneBar({ x, w, y, h = BAR_H, title, ...rest }: { x: number; w: number; y: number; h?: number; title: string } & Omit<SVGProps<SVGRectElement>, 'x' | 'y'>) {
  return (
    <rect className="gantt-lane" x={x} y={y} width={Math.max(w, 1)} height={h} rx={2} {...rest}>
      <title>{title}</title>
    </rect>
  );
}

/** 이름 글 폭 어림(11px 글꼴: 한글 11 · 그 밖 6.5). 차트 끝에서 잘리지 않게 놓을 쪽을 정할 때만 쓴다. */
export const labelWidth = (t: string) => [...t].reduce((n, ch) => n + (/[가-힣]/.test(ch) ? 11 : 6.5), 0);

/** 막대 옆 이름. anchor 'end' 면 x 에서 왼쪽으로 쓴다(차트 오른쪽 끝). */
export function Label({ x, y, text, tone, anchor }: { x: number; y: number; text: string; tone?: 'danger'; anchor?: 'end' }) {
  return (
    <text className={`gantt-label${tone ? ` is-${tone}` : ''}`} x={x} y={y + 19} textAnchor={anchor}>
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
