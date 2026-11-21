// 스마트폰·태블릿 뷰포트 판별 및 수동 화면 형태 전환(auto | phone | tablet | desktop).
import { useEffect, useState } from 'react';
import { create } from 'zustand';

export const MOBILE_MAX_W = 768;
export const TABLET_MIN_W = 600;

export type DeviceMode = 'auto' | 'phone' | 'tablet' | 'desktop';

interface DeviceModeState {
  mode: DeviceMode;
  setMode(mode: DeviceMode): void;
}

export const useDeviceMode = create<DeviceModeState>((set) => ({
  mode: 'auto',
  setMode: (mode) => set({ mode }),
}));

const checkNarrow = () => (typeof window !== 'undefined' ? window.innerWidth <= MOBILE_MAX_W : false);

function useViewportWidth(): number {
  const [w, setW] = useState(() => (typeof window !== 'undefined' ? window.innerWidth : 1280));
  useEffect(() => {
    const onResize = () => setW(window.innerWidth);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);
  return w;
}

export function useIsMobile(): boolean {
  const mode = useDeviceMode((s) => s.mode);
  const [narrow, setNarrow] = useState(checkNarrow);
  useEffect(() => {
    const onResize = () => setNarrow(checkNarrow());
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);
  if (mode === 'phone' || mode === 'tablet') return true;
  if (mode === 'desktop') return false;
  return narrow;
}

export function useResolvedDevice(): 'phone' | 'tablet' {
  const mode = useDeviceMode((s) => s.mode);
  const width = useViewportWidth();
  if (mode === 'phone') return 'phone';
  if (mode === 'tablet') return 'tablet';
  return width >= TABLET_MIN_W ? 'tablet' : 'phone';
}
