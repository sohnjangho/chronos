// 비교판 자료: 요약 표·버전 목록·두 안 비교를 읽는다. 비교의 기본값(열린 복사본 가운데 가장 새것, 없으면 plan)은 요약 표에서 고른다.
import { useCallback, useEffect, useState } from 'react';
import { getCompare, getSummary, getVersions, messageOf, type CompareOut, type SideOut, type VersionItem } from './compareApi';

export type Load<T> = { kind: 'loading' } | { kind: 'ready'; data: T } | { kind: 'failed'; message: string };

/** 요약 표(새것부터)의 열린(status open) 복사본 가운데 첫 것, 없으면 plan. */
export const defaultOther = (sides: SideOut[]) => sides.find((s) => s.ref.startsWith('s:') && s.status === 'open')?.ref ?? 'plan';

/**
 * 약속 하나를 읽어 Load 로. deps 가 바뀌면 다시 읽고, 늦게 온 앞 답은 버린다. run 이 null 이면 읽지 않는다.
 * 받은 값은 그 deps 의 것으로만 쓴다 — deps 가 바뀐 그 그림부터 읽는 중이다(다시 읽을 때 옛 요약으로 기본값을 고르지 않게).
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
  return state?.key === key ? state.load : { kind: 'loading' };
}

export interface CompareData {
  summary: Load<SideOut[]>;
  versions: VersionItem[];
  compare: Load<CompareOut>;
  /** 실제로 비교하는 안(고른 것, 없으면 기본값). 요약을 읽기 전이면 null. */
  other: string | null;
  reload(): void;
}

/** epoch 가 바뀌면(창에 새 params) reload 처럼 모두 다시 읽는다. */
export function useCompareData(scheduleId: number, base: string, picked: string | null, epoch = 0): CompareData {
  const [tick, setTick] = useState(0);
  const summary = useLoad(() => getSummary(scheduleId).then((s) => s.sides), [scheduleId, tick, epoch]);
  const versions = useLoad(() => getVersions(scheduleId), [scheduleId, tick, epoch]);
  const other = picked ?? (summary.kind === 'ready' ? defaultOther(summary.data) : summary.kind === 'failed' ? 'plan' : null);
  const compare = useLoad(other ? () => getCompare(scheduleId, base, other) : null, [scheduleId, base, other, tick, epoch]);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { summary, versions: versions.kind === 'ready' ? versions.data : [], compare, other, reload };
}
