// 간트 관계선 모양. 선은 꺾은선 SVG path 이고 화살표는 marker 가 그린다.

export type RelType = 'FS' | 'SS' | 'FF' | 'SF';

/** 막대 자리(x·폭)와 줄 번호(보이는 첫 줄이 0). */
export interface LinkEnd {
  x: number;
  w: number;
  row: number;
}

const GAP = 6;
const r = (n: number) => String(Math.round(n * 10) / 10);

/**
 * 선행 막대 → 후행 막대 꺾은선. FS·FF 는 선행 끝에서, SS·SF 는 선행 시작에서 나가고,
 * FS·SS 는 후행 시작으로 왼쪽에서, FF·SF 는 후행 끝으로 오른쪽에서 들어간다.
 * 한 번 꺾어 닿을 수 없으면(후행이 선행보다 앞에 있음) 두 줄 사이 경계를 따라 돌아간다.
 */
export function linkPath(from: LinkEnd, to: LinkEnd, type: RelType, rowH: number): string {
  const fromEnd = type === 'FS' || type === 'FF';
  const toEnd = type === 'FF' || type === 'SF';
  const sx = fromEnd ? from.x + from.w : from.x;
  const ex = toEnd ? to.x + to.w : to.x;
  const sy = from.row * rowH + rowH / 2;
  const ey = to.row * rowH + rowH / 2;
  const exitX = fromEnd ? sx + GAP : sx - GAP;
  const enterX = toEnd ? ex + GAP : ex - GAP;
  // 세로 선을 한 x 에 둘 수 있는가: 나가는 쪽과 들어가는 쪽 모두를 만족하는 x.
  const lo = Math.max(fromEnd ? exitX : -Infinity, toEnd ? enterX : -Infinity);
  const hi = Math.min(fromEnd ? Infinity : exitX, toEnd ? Infinity : enterX);
  if (lo <= hi) {
    const v = fromEnd ? lo : hi;
    return `M ${r(sx)} ${r(sy)} H ${r(v)} V ${r(ey)} H ${r(ex)}`;
  }
  const midY = ey > sy ? to.row * rowH : (to.row + 1) * rowH;
  return `M ${r(sx)} ${r(sy)} H ${r(exitX)} V ${r(midY)} H ${r(enterX)} V ${r(ey)} H ${r(ex)}`;
}
