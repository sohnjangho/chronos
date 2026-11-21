// 창 화면 가장자리 스냅(좌/우 50% 분할 · 상단 최대화) 미리보기 상태.
import { create } from 'zustand';
import { workArea, type Rect } from './windowStore';

export type SnapZone = 'left' | 'right' | 'top' | null;

const EDGE_PX = 18;
const TOP_PX = 54;

export function detectSnap(clientX: number, clientY: number): SnapZone {
  if (clientX <= EDGE_PX) return 'left';
  if (clientX >= window.innerWidth - EDGE_PX) return 'right';
  if (clientY <= TOP_PX) return 'top';
  return null;
}

export function snapRect(zone: Exclude<SnapZone, null>): Rect {
  const area = workArea();
  if (zone === 'top') return area;
  const half = Math.floor(area.w / 2);
  if (zone === 'left') return { x: area.x, y: area.y, w: half, h: area.h };
  return { x: area.x + half, y: area.y, w: area.w - half, h: area.h };
}

export const useSnap = create<{ zone: SnapZone; setZone(z: SnapZone): void }>((set) => ({
  zone: null,
  setZone: (zone) => set((s) => (s.zone === zone ? s : { zone })),
}));
