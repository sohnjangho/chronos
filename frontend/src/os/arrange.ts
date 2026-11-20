// 윈도우 메뉴의 정렬 셋(좌우 분할·격자·계단식)이 쓰는 자리 계산. 순수 함수.

export interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

export const ARRANGE_GAP = 8;
export const CASCADE_STEP = 28;

interface Limits {
  minW: number;
  minH: number;
}

/** 칸이 모자라 남은 창은 마지막 칸에서 28px씩 비켜 겹친다(영역 밖으로 나가지 않게). */
function spill(last: Box, extra: number, area: Box): Box[] {
  return Array.from({ length: extra }, (_, i) => {
    const step = CASCADE_STEP * (i + 1);
    const x = Math.min(last.x + step, area.x + area.w - last.w);
    const y = Math.min(last.y + step, area.y + area.h - last.h);
    return { ...last, x: Math.max(area.x, x), y: Math.max(area.y, y) };
  });
}

/** 한 줄(가로 또는 세로)에 들어가는 칸 수와 칸 길이. 최소 길이보다 작아지면 칸 수를 줄인다. */
function cells(want: number, length: number, min: number) {
  const fit = Math.max(1, Math.floor((length - ARRANGE_GAP) / (min + ARRANGE_GAP)));
  const count = Math.min(want, fit);
  const size = Math.max(min, Math.floor((length - ARRANGE_GAP * (count + 1)) / count));
  return { count, size };
}

/** 첫 창(활성)은 왼쪽 절반, 나머지는 오른쪽 절반에 위아래로 쌓는다. */
export function splitBoxes(n: number, area: Box, lim: Limits): Box[] {
  if (n === 0) return [];
  const columns = n === 1 ? 1 : 2;
  const col = cells(columns, area.w, lim.minW);
  const left: Box = {
    x: area.x + ARRANGE_GAP,
    y: area.y + ARRANGE_GAP,
    w: n === 1 ? area.w - 2 * ARRANGE_GAP : col.size,
    h: area.h - 2 * ARRANGE_GAP,
  };
  if (n === 1) return [left];
  const rows = cells(n - 1, area.h, lim.minH);
  const right = Array.from({ length: rows.count }, (_, i) => ({
    x: left.x + col.size + ARRANGE_GAP,
    y: area.y + ARRANGE_GAP + i * (rows.size + ARRANGE_GAP),
    w: col.size,
    h: rows.size,
  }));
  return [left, ...right, ...spill(right[right.length - 1], n - 1 - rows.count, area)];
}

/** 열은 √n 을 올림한 수, 칸 크기는 모두 같다. */
export function gridBoxes(n: number, area: Box, lim: Limits): Box[] {
  if (n === 0) return [];
  const wantCols = Math.ceil(Math.sqrt(n));
  const col = cells(wantCols, area.w, lim.minW);
  const row = cells(Math.ceil(n / col.count), area.h, lim.minH);
  const placed = Math.min(n, col.count * row.count);
  const boxes = Array.from({ length: placed }, (_, i) => ({
    x: area.x + ARRANGE_GAP + (i % col.count) * (col.size + ARRANGE_GAP),
    y: area.y + ARRANGE_GAP + Math.floor(i / col.count) * (row.size + ARRANGE_GAP),
    w: col.size,
    h: row.size,
  }));
  return [...boxes, ...spill(boxes[boxes.length - 1], n - placed, area)];
}

/** 28px씩 비켜 겹친다. 크기는 지금 크기를 영역에 맞춰 쓰고, 넘치면 처음 자리로 돌아간다. */
export function cascadeBoxes(sizes: { w: number; h: number }[], area: Box, lim: Limits): Box[] {
  let i = 0;
  return sizes.map((size) => {
    const w = Math.max(lim.minW, Math.min(size.w, area.w - 2 * ARRANGE_GAP - CASCADE_STEP * (sizes.length - 1)));
    const h = Math.max(lim.minH, Math.min(size.h, area.h - 2 * ARRANGE_GAP - CASCADE_STEP * (sizes.length - 1)));
    let x = area.x + ARRANGE_GAP + CASCADE_STEP * i;
    let y = area.y + ARRANGE_GAP + CASCADE_STEP * i;
    if (x + w > area.x + area.w || y + h > area.y + area.h) {
      i = 0;
      x = area.x + ARRANGE_GAP;
      y = area.y + ARRANGE_GAP;
    }
    i += 1;
    return { x, y, w, h };
  });
}
