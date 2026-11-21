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
 * mid: 줄 위쪽에서 선이 닿는 높이(기본 줄 가운데).
 */
export function linkPath(from: LinkEnd, to: LinkEnd, type: RelType, rowH: number, mid = rowH / 2): string {
  const fromEnd = type === 'FS' || type === 'FF';
  const toEnd = type === 'FF' || type === 'SF';
  const sx = fromEnd ? from.x + from.w : from.x;
  const ex = toEnd ? to.x + to.w : to.x;
  const sy = from.row * rowH + mid;
  const ey = to.row * rowH + mid;
  const exitX = fromEnd ? sx + GAP : sx - GAP;
  const enterX = toEnd ? ex + GAP : ex - GAP;
  // 세로 선을 한 x 에 둘 수 있는가: 나가는 쪽과 들어가는 쪽 모두를 만족하는 x.
  const lo = Math.max(fromEnd ? exitX : -Infinity, toEnd ? enterX : -Infinity);
  const hi = Math.min(fromEnd ? Infinity : exitX, toEnd ? Infinity : enterX);
  if (lo <= hi) {
    const v = fromEnd ? lo : hi;
    return `M ${r(sx)} ${r(sy)} H ${r(v)} V ${r(ey)} H ${r(ex)}`;
  }
  // FS 에서 후행이 선행 끝과 바로 이어지거나 좁게 떨어져 있으면(0 <= ex - sx < 2*GAP)
  // 오른쪽으로 삐져나갔다가 되돌아오는 꺾은선 대신 사이 가운데 x 로 곧장 내려가 닿는다.
  if (type === 'FS' && ex >= sx) {
    const v = (sx + ex) / 2;
    return Math.abs(ex - sx) < 0.5
      ? `M ${r(sx)} ${r(sy)} V ${r(ey)} H ${r(ex)}`
      : `M ${r(sx)} ${r(sy)} H ${r(v)} V ${r(ey)} H ${r(ex)}`;
  }
  const midY = ey > sy ? to.row * rowH : (to.row + 1) * rowH;
  return `M ${r(sx)} ${r(sy)} H ${r(exitX)} V ${r(midY)} H ${r(enterX)} V ${r(ey)} H ${r(ex)}`;
}
