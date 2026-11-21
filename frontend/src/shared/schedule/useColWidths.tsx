// 표 열 폭·행 높이 드래그 조정(로그인 사용자별로 localStorage 기억).
import { useCallback, useState, type PointerEvent as ReactPointerEvent } from 'react';
import { loadPref, savePref } from '../../os/prefs';
import { useSession } from '../../os/session';
import type { ColKey, ColumnDef } from './columns';

const COL_MIN = 44;
const COL_MAX = 520;
const ROW_MIN = 26;
const ROW_MAX = 64;

export type ColWidths = Partial<Record<ColKey, number>>;

function loadWidths(prefKey: string, userId: number | null): ColWidths {
  const saved = loadPref(prefKey, userId);
  if (!saved || typeof saved !== 'object' || Array.isArray(saved)) return {};
  const out: ColWidths = {};
  for (const [k, v] of Object.entries(saved as Record<string, unknown>)) {
    if (typeof v === 'number' && Number.isFinite(v) && v >= COL_MIN && v <= COL_MAX) {
      out[k as ColKey] = Math.round(v);
    }
  }
  return out;
}

/** 표 열 폭 상태(사용자별 localStorage 저장). */
export function useColWidths(prefKey: string) {
  const userId = useSession((s) => s.session?.user.id ?? null);
  const [widths, setWidths] = useState<ColWidths>(() => loadWidths(prefKey, userId));

  const resize = useCallback(
    (key: ColKey, w: number) => {
      const clamped = Math.round(Math.min(COL_MAX, Math.max(COL_MIN, w)));
      setWidths((prev) => {
        const next = { ...prev, [key]: clamped };
        savePref(prefKey, userId, next);
        return next;
      });
    },
    [prefKey, userId],
  );

  const widthOf = useCallback((c: ColumnDef) => widths[c.key] ?? c.width, [widths]);
  return { widths, widthOf, resize };
}

/** 표 행 높이 상태(사용자별 localStorage 저장). */
export function useRowHeight(prefKey: string, fallback = 32) {
  const userId = useSession((s) => s.session?.user.id ?? null);
  const [rowHeight, setRowHeight] = useState<number>(() => {
    const saved = loadPref(prefKey, userId);
    return typeof saved === 'number' && Number.isFinite(saved) && saved >= ROW_MIN && saved <= ROW_MAX ? Math.round(saved) : fallback;
  });

  const resizeRow = useCallback(
    (h: number) => {
      const clamped = Math.round(Math.min(ROW_MAX, Math.max(ROW_MIN, h)));
      setRowHeight(clamped);
      savePref(prefKey, userId, clamped);
    },
    [prefKey, userId],
  );

  return { rowHeight, resizeRow };
}

/** 열 머리글 오른쪽 경계에 붙는 폭 조정 손잡이. */
export function ColResizeHandle({ label, width, onResize }: { label: string; width: number; onResize(w: number): void }) {
  const onPointerDown = (e: ReactPointerEvent) => {
    e.preventDefault();
    e.stopPropagation();
    const x0 = e.clientX;
    const w0 = width;
    const move = (ev: PointerEvent) => onResize(w0 + ev.clientX - x0);
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };
  return (
    <span
      aria-hidden="true"
      title={`${label} 열 너비 조절`}
      className="sch-col-resize"
      onPointerDown={onPointerDown}
    />
  );
}

/** 행 하단 경계에 붙는 높이 조정 손잡이. */
export function RowResizeHandle({ height, onResize }: { height: number; onResize(h: number): void }) {
  const onPointerDown = (e: ReactPointerEvent) => {
    e.preventDefault();
    e.stopPropagation();
    const y0 = e.clientY;
    const h0 = height;
    const move = (ev: PointerEvent) => onResize(h0 + ev.clientY - y0);
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };
  return (
    <span
      aria-hidden="true"
      title="행 높이 조절"
      className="sch-row-resize"
      onPointerDown={onPointerDown}
    />
  );
}
