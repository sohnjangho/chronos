// 기준 ▾ / 비교 ▾: 묶음(현재·Plan / 버전 / 만약에 복사본)과 찾기로 안을 고른다. 판은 창 안에서 넘치지 않게 자리를 맞춘다.
import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from 'react';
import PickList from '../../os/PickList';
import type { SideOut, VersionItem } from './compareApi';

export interface PlanItem {
  ref: string;
  label: string;
  detail?: string;
}
export interface PlanGroup {
  title: string;
  items: PlanItem[];
}

const FIXED: [string, string][] = [
  ['current', '현재 일정'],
  ['plan', 'Plan'],
];

const COPY_STATE: Record<string, string> = { submitted: '승인 대기', applied: '반영됨', discarded: '버린 복사본' };

/**
 * 요약 표의 안과 버전 목록(새것부터)으로 묶음을 만든다. 요약에 Plan 줄이 없으면(Plan 계산 불가) Plan 은 빼고,
 * 복사본은 열린 것만 낡았으면 「낡음」, 나머지는 상태 글.
 */
export function planGroups(sides: SideOut[], versions: VersionItem[]): PlanGroup[] {
  const label = (ref: string, fallback: string) => sides.find((s) => s.ref === ref)?.label ?? fallback;
  const copyDetail = (s: SideOut) => (s.status === 'open' ? (s.stale ? '낡음' : undefined) : COPY_STATE[s.status ?? '']);
  const fixed = FIXED.filter(([ref]) => ref !== 'plan' || sides.some((s) => s.ref === 'plan'));
  return [
    { title: '현재·Plan', items: fixed.map(([ref, name]) => ({ ref, label: label(ref, name) })) },
    {
      title: '버전',
      items: versions.map((v) => ({ ref: `v:${v.n}`, label: `버전 ${v.n}`, detail: [v.is_plan && '처음 계획', v.note].filter(Boolean).join(' · ') || undefined })),
    },
    { title: '만약에 복사본', items: sides.filter((s) => s.ref.startsWith('s:')).map((s) => ({ ref: s.ref, label: s.label, detail: copyDetail(s) })) },
  ];
}

const matches = (it: PlanItem, q: string) => !q || `${it.label} ${it.detail ?? ''}`.toLowerCase().includes(q.toLowerCase());

interface Props {
  /** 기준 · 비교 */
  title: string;
  tone: 'base' | 'other';
  value: string;
  label: string;
  groups: PlanGroup[];
  onPick(ref: string): void;
}

/** 열린 판이 창(비교판 바탕) 오른쪽·아래를 넘지 않게: 넘친 만큼 왼쪽으로 옮기고 높이를 줄인다(창 배율도 따진다). */
function useFit(open: boolean) {
  const ref = useRef<HTMLDivElement>(null);
  const [style, setStyle] = useState<CSSProperties>({});
  useLayoutEffect(() => {
    const pop = ref.current;
    const box = pop?.closest('.cmp-root');
    if (!open || !pop || !box || !pop.parentElement) return;
    // 단추 자리(옮기기 전 왼쪽 끝)에서 잰다 — 앞서 옮긴 값에 흔들리지 않게.
    const at = pop.parentElement.getBoundingClientRect();
    const r = pop.getBoundingClientRect();
    const b = box.getBoundingClientRect();
    const k = r.width > 0 ? pop.offsetWidth / r.width : 1;
    const over = Math.max(0, at.left + r.width - (b.right - 8));
    const room = Math.max(0, at.left - b.left - 8);
    setStyle({ left: -Math.min(over, room) * k, maxHeight: Math.min(420, Math.max(160, (b.bottom - r.top - 8) * k)) });
  }, [open]);
  return { ref, style };
}

export default function PlanPicker({ title, tone, value, label, groups, onPick }: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const rootRef = useRef<HTMLDivElement>(null);
  const fit = useFit(open);
  useEffect(() => {
    if (!open) return;
    const onPointer = (e: PointerEvent) => !rootRef.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener('pointerdown', onPointer);
    return () => document.removeEventListener('pointerdown', onPointer);
  }, [open]);
  const close = () => {
    setOpen(false);
    setQuery('');
    rootRef.current?.querySelector('button')?.focus();
  };
  const shown = groups.map((g) => ({
    title: g.title,
    items: g.items
      .filter((it) => matches(it, query))
      .map((it) => ({ key: it.ref, label: it.label, detail: it.detail, selected: it.ref === value, run: () => (close(), onPick(it.ref)) })),
  }));
  return (
    <div className="cmp-pick" ref={rootRef}>
      <button
        type="button"
        className="cmp-pick-btn"
        aria-label={`${title}: ${label}`}
        aria-expanded={open}
        aria-haspopup="listbox"
        onClick={() => (open ? close() : setOpen(true))}
      >
        <span className={`cmp-swatch is-${tone}`} aria-hidden="true" />
        <span className="cmp-pick-text">{label}</span>
        <span aria-hidden="true">▾</span>
      </button>
      {open && (
        <div className="cmp-pop" ref={fit.ref} style={fit.style}>
          <PickList label={`${title} 안 찾기`} placeholder="이름·버전·메모 찾기" query={query} onQuery={setQuery} groups={shown} onClose={close} />
        </div>
      )}
    </div>
  );
}
