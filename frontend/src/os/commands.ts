// 메뉴와 단축키가 함께 쓰는 셸 명령. 정렬·일괄 명령은 화면 낭독기에 한 번 알린다.
import { useShell } from './shell';
import { activeWindow, useWindows, type ArrangeKind } from './windowStore';
import { useZoom } from './zoom';

const ARRANGE_TEXT: Record<ArrangeKind, string> = { split: '좌우로 분할했습니다', grid: '격자로 정렬했습니다', cascade: '계단식으로 정렬했습니다' };

const say = (text: string) => useShell.getState().announce(text);
const store = () => useWindows.getState();

export function arrangeWindows(kind: ArrangeKind) {
  const n = store().arrange(kind);
  if (n) say(`창 ${n}개를 ${ARRANGE_TEXT[kind]}`);
}

export function minimizeAllWindows() {
  const n = store().minimizeAll();
  if (n) say(`창 ${n}개를 최소화했습니다`);
}

export function closeAllWindows() {
  const n = store().closeAll();
  if (n) say(`창 ${n}개를 닫았습니다`);
}

/** 활성 창 프로그램의 배율 바꾸기. 활성 창이 없으면 아무것도 하지 않는다. */
export function zoomActive(dir: 'in' | 'out' | 'reset') {
  const active = activeWindow(store());
  if (!active) return;
  const z = useZoom.getState();
  if (dir === 'in') z.zoomIn(active.programId);
  else if (dir === 'out') z.zoomOut(active.programId);
  else z.reset(active.programId);
}
