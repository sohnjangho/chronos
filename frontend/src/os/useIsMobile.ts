// 접속 기기(스마트폰·태블릿·데스크톱) 자동 판별 및 수동 화면 형태 전환(auto | phone | tablet | desktop).
import { useEffect, useState } from 'react';
import { create } from 'zustand';
import { loadPref, savePref } from './prefs';
import { loadJson, saveJson } from './storage';

export const MOBILE_MAX_W = 768;
export const TABLET_MIN_W = 600;
export const TABLET_MAX_W = 960;

export type DeviceMode = 'auto' | 'phone' | 'tablet' | 'desktop';
export type ResolvedDevice = 'phone' | 'tablet' | 'desktop';

const DEVICE_KEY = 'chronos.deviceMode';

function validDeviceMode(raw: unknown): DeviceMode | null {
  return raw === 'auto' || raw === 'phone' || raw === 'tablet' || raw === 'desktop' ? raw : null;
}

interface DeviceModeState {
  userId: number | null;
  mode: DeviceMode;
  load(userId: number | null): void;
  setMode(mode: DeviceMode): void;
  reset(): void;
}

export const useDeviceMode = create<DeviceModeState>((set, get) => ({
  userId: null,
  mode: validDeviceMode(loadJson(DEVICE_KEY)) ?? 'auto',
  load(userId) {
    const mode = validDeviceMode(loadPref('deviceMode', userId)) ?? validDeviceMode(loadJson(DEVICE_KEY)) ?? 'auto';
    set({ userId, mode });
  },
  setMode(mode) {
    savePref('deviceMode', get().userId, mode);
    saveJson(DEVICE_KEY, mode);
    set({ mode });
  },
  reset() {
    set({ userId: null, mode: 'auto' });
  },
}));

/**
 * 접속 기기의 User-Agent, 터치 포인터, 화면 크기·비율을 조합해 기기 형태를 자동 판별한다.
 * - 폰 UA 또는 세로·짧은 변 600px 미만의 터치 기기 -> phone
 * - 태블릿 UA(iPadOS 데스크톱 Safari 포함) 또는 600~960px / 세로형 ~1024px 태블릿 -> tablet
 * - 그 외(일반 PC 모니터·1024x768 가로 데스크톱 등) -> desktop
 */
export function detectClientDevice(width?: number, height?: number): ResolvedDevice {
  const w = width ?? (typeof window !== 'undefined' ? window.innerWidth : 1280);
  const h = height ?? (typeof window !== 'undefined' ? window.innerHeight : 800);

  if (typeof navigator !== 'undefined') {
    const ua = navigator.userAgent || '';
    const platform = navigator.platform || '';
    const touchPoints = typeof navigator.maxTouchPoints === 'number' ? navigator.maxTouchPoints : 0;

    if (/iPhone|iPod|Android.*Mobile|Windows Phone|BlackBerry|IEMobile|Opera Mini/i.test(ua)) {
      return 'phone';
    }
    const isIpadOs = (/Macintosh|MacIntel/i.test(ua) || /Mac/i.test(platform)) && touchPoints > 1;
    if (/iPad|Tablet|PlayBook|Silk|Kindle/i.test(ua) || (/Android/i.test(ua) && !/Mobile/i.test(ua)) || isIpadOs) {
      return 'tablet';
    }
    if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
      try {
        if (window.matchMedia('(pointer: coarse)').matches) {
          if (Math.min(w, h) < TABLET_MIN_W) return 'phone';
          if (Math.max(w, h) <= 1366) return 'tablet';
        }
      } catch {
        // matchMedia 미지원 테스트 환경 무시
      }
    }
  }

  if (w < TABLET_MIN_W) return 'phone';
  if (w <= TABLET_MAX_W || (w <= 1024 && h > w)) return 'tablet';
  return 'desktop';
}

function useViewportSize(): { w: number; h: number } {
  const [size, setSize] = useState(() =>
    typeof window !== 'undefined' ? { w: window.innerWidth, h: window.innerHeight } : { w: 1280, h: 800 },
  );
  useEffect(() => {
    const onResize = () => setSize({ w: window.innerWidth, h: window.innerHeight });
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);
  return size;
}

export function useDetectedDevice(): ResolvedDevice {
  const { w, h } = useViewportSize();
  return detectClientDevice(w, h);
}

export function useActiveDevice(): ResolvedDevice {
  const mode = useDeviceMode((s) => s.mode);
  const detected = useDetectedDevice();
  return mode === 'auto' ? detected : mode;
}

export function useIsMobile(): boolean {
  const device = useActiveDevice();
  return device === 'phone' || device === 'tablet';
}

export function useResolvedDevice(): 'phone' | 'tablet' {
  const device = useActiveDevice();
  return device === 'tablet' ? 'tablet' : 'phone';
}
