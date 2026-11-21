// 간트차트 Plan · Actual · CPM 색상 선택(10색 팔레트, 로그인 사용자별 기억).
import { useCallback, useState } from 'react';
import { loadPref, savePref } from '../../os/prefs';
import { useSession } from '../../os/session';

export interface GanttColors {
  plan: string;
  actual: string;
  cpm: string;
}

export const GANTT_PALETTE: { name: string; hex: string }[] = [
  { name: '파랑', hex: '#2563eb' },
  { name: '남색', hex: '#4f46e5' },
  { name: '청록', hex: '#0891b2' },
  { name: '초록', hex: '#16a34a' },
  { name: '연두', hex: '#65a30d' },
  { name: '주황', hex: '#ea580c' },
  { name: '빨강', hex: '#dc2626' },
  { name: '자주', hex: '#db2777' },
  { name: '보라', hex: '#9333ea' },
  { name: '슬레이트', hex: '#475569' },
];

export const DEFAULT_GANTT_COLORS: GanttColors = {
  plan: '#2563eb',
  actual: '#16a34a',
  cpm: '#dc2626',
};

const PREF = 'schedule.gantt.colors';
const VALID = new Set(GANTT_PALETTE.map((c) => c.hex));

function loadColors(userId: number | null): GanttColors {
  const saved = loadPref(PREF, userId) as Partial<GanttColors> | null;
  if (!saved || typeof saved !== 'object') return DEFAULT_GANTT_COLORS;
  return {
    plan: saved.plan && VALID.has(saved.plan) ? saved.plan : DEFAULT_GANTT_COLORS.plan,
    actual: saved.actual && VALID.has(saved.actual) ? saved.actual : DEFAULT_GANTT_COLORS.actual,
    cpm: saved.cpm && VALID.has(saved.cpm) ? saved.cpm : DEFAULT_GANTT_COLORS.cpm,
  };
}

export function useGanttColors() {
  const userId = useSession((s) => s.session?.user.id ?? null);
  const [colors, setColors] = useState<GanttColors>(() => loadColors(userId));

  const setColor = useCallback(
    (key: keyof GanttColors, hex: string) => {
      setColors((prev) => {
        const next = { ...prev, [key]: hex };
        savePref(PREF, userId, next);
        return next;
      });
    },
    [userId],
  );

  const resetColors = useCallback(() => {
    setColors(DEFAULT_GANTT_COLORS);
    savePref(PREF, userId, DEFAULT_GANTT_COLORS);
  }, [userId]);

  return { colors, setColor, resetColors };
}
