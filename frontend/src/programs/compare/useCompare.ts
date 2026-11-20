// 비교판 자료: 요약 표·버전 목록·두 안 비교를 읽는다. 비교의 기본값은 새로 읽은 요약·버전으로만 고른다(defaultOther).
// 다시 읽는 동안에는 앞 값을 그대로 보이고 refreshing 으로 알린다(빈 화면으로 바꾸지 않는다).
import { useCallback, useEffect, useState } from 'react';
import { getCompare, getSummary, getVersions, messageOf, type CompareOut, type SideOut, type VersionItem } from './compareApi';

/** refreshing: 앞 값이고 새 값을 읽는 중. */
export type Load<T> = { kind: 'loading' } | { kind: 'ready'; data: T; refreshing?: boolean } | { kind: 'failed'; message: string };

/**
 * 기본 비교: 요약 표(새것부터)의 열린 복사본 가운데 첫 것. 「열린」은 서버 요약과 같은 뜻 — open·submitted
 * (컨트롤러 판정 11-20. 반영 단추는 따로 open 만). 없으면 plan, 요약에 Plan 줄이 없으면(Plan 계산 불가)
 * 지금 버전 앞 버전, 그것도 없으면 current.
 */
export function defaultOther(sides: SideOut[], versions: VersionItem[]): string {
  const copy = sides.find((s) => s.ref.startsWith('s:') && (s.status === 'open' || s.status === 'submitted'));
  if (copy) return copy.ref;
  if (sides.some((s) => s.ref === 'plan')) return 'plan';
  const now = sides.find((s) => s.ref === 'current')?.version ?? versions[0]?.n ?? 0; // 버전 목록은 새것부터
  const prev = versions.find((v) => v.n < now);
  return prev ? `v:${prev.n}` : 'current';
}

/**
 * 약속 하나를 읽어 Load 로. deps 가 바뀌면 다시 읽고, 늦게 온 앞 답은 버린다. run 이 null 이면 읽지 않는다.
 * deps 가 바뀐 그림부터는 앞 값을 refreshing 으로 돌려준다(앞 값이 없으면 loading).
 */
function useLoad<T>(run: (() => Promise<T>) | null, deps: unknown[]): Load<T> {
  const key = JSON.stringify(deps);
  const [state, setState] = useState<{ key: string; load: Load<T> } | null>(null);
  useEffect(() => {
    if (!run) return;
    let live = true;
    run()
      .then((data) => live && setState({ key, load: { kind: 'ready', data } }))
      .catch((e) => live && setState({ key, load: { kind: 'failed', message: messageOf(e) } }));
    return () => {
      live = false;
    };
  }, [key]); // run 은 deps(key)로 정해진다
  if (state?.key === key) return state.load;
  return state?.load.kind === 'ready' ? { ...state.load, refreshing: true } : { kind: 'loading' };
}

export interface CompareData {
  summary: Load<SideOut[]>;
  versions: VersionItem[];
  compare: Load<CompareOut>;
  /** 실제로 비교하는 안(고른 것, 없으면 기본값). 기본값을 정할 새 요약·버전이 아직 없으면 null. */
  other: string | null;
  /** 요약이나 비교를 다시 읽는 중(앞 값이 보이는 중). */
  refreshing: boolean;
  reload(): void;
}

function fresh<T>(l: Load<T>): boolean {
  return l.kind === 'failed' || (l.kind === 'ready' && !l.refreshing);
}
function dataOf<T>(l: Load<T[]>): T[] {
  return l.kind === 'ready' ? l.data : [];
}

/** epoch 가 바뀌면(창에 새 params) reload 처럼 모두 다시 읽는다. */
export function useCompareData(scheduleId: number, base: string, picked: string | null, epoch = 0): CompareData {
  const [tick, setTick] = useState(0);
  const summary = useLoad(() => getSummary(scheduleId).then((s) => s.sides), [scheduleId, tick, epoch]);
  const versions = useLoad(() => getVersions(scheduleId), [scheduleId, tick, epoch]);
  // 기본값은 새로 읽은 요약·버전으로만(옛 요약이면 막 버린 복사본을 다시 고를 수 있다). 못 읽었으면 빈 목록으로.
  const other = picked ?? (fresh(summary) && fresh(versions) ? defaultOther(dataOf(summary), dataOf(versions)) : null);
  const compare = useLoad(other ? () => getCompare(scheduleId, base, other) : null, [scheduleId, base, other, tick, epoch]);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  const refreshing = (summary.kind === 'ready' && !!summary.refreshing) || (compare.kind === 'ready' && !!compare.refreshing);
  return { summary, versions: dataOf(versions), compare, other, refreshing, reload };
}
