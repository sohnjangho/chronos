// 탐색기 자료: 일정 목록 · 고른 일정의 요약과 버전 · 되돌리기 · 지우기(관리자).
import { useCallback, useEffect, useRef, useState } from 'react';
import { useCurrentSchedule } from '../../os/currentSchedule';
import { ApiError } from '../../shared/api';
import { eulOf, exApi, type ScheduleSummary, type TreeSchedule, type Version } from './exApi';

export interface Notice {
  tone: 'ok' | 'error';
  text: string;
}

type View = { data: ScheduleSummary | null; error: string | null };
const message = (e: unknown) => (e instanceof ApiError ? e.message : '요청을 처리할 수 없습니다.');

/**
 * 고른 일정의 요약(일정 보기)과 버전 목록. 고른 일정이 아닌 늦은 응답은 버린다.
 * 버전을 읽지 못하면 versionsError 에 서버 글을 두고, retry 로 다시 읽는다.
 */
function useDetail(selected: number | null) {
  const [view, setView] = useState<View | null>(null);
  const [versions, setVersions] = useState<Version[] | null>(null);
  const [versionsError, setVersionsError] = useState<string | null>(null);
  const current = useRef<number | null>(null);
  const load = useCallback(async (id: number) => {
    const [v, vs] = await Promise.allSettled([exApi.view(id), exApi.versions(id)]);
    if (current.current !== id) return;
    setView(v.status === 'fulfilled' ? { data: v.value, error: null } : { data: null, error: message(v.reason) });
    setVersions(vs.status === 'fulfilled' ? vs.value : null);
    setVersionsError(vs.status === 'fulfilled' ? null : message(vs.reason));
  }, []);
  useEffect(() => {
    current.current = selected;
    setView(null);
    setVersions(null);
    setVersionsError(null);
    if (selected !== null) void load(selected);
  }, [selected, load]);
  const retry = () => {
    if (selected === null) return;
    setVersionsError(null);
    void load(selected);
  };
  return { view, versions, versionsError, retry, reload: load };
}

export function useExplorerData() {
  const [schedules, setSchedules] = useState<TreeSchedule[] | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const detail = useDetail(selected);
  const loadTree = useCallback(async () => {
    try {
      setSchedules((await exApi.tree()).schedules);
    } catch (e) {
      setNotice({ tone: 'error', text: message(e) });
    }
  }, []);
  useEffect(() => void loadTree(), [loadTree]);
  const schedule = schedules?.find((s) => s.id === selected) ?? null;

  async function restore(n: number) {
    if (!schedule) return;
    try {
      const view = await exApi.restore(schedule.id, n, schedule.version);
      setNotice({ tone: 'ok', text: `버전 ${n}의 내용으로 버전 ${view.version}${eulOf(String(view.version))} 만들었습니다.` });
      useCurrentSchedule.getState().bumpReload(); // 열린 일정 창(간트·스케줄·CPM·공정률)이 새 버전을 다시 읽는다
    } catch (e) {
      setNotice({ tone: 'error', text: message(e) });
    }
    await Promise.all([loadTree(), detail.reload(schedule.id)]);
  }

  async function remove() {
    if (!schedule) return;
    try {
      await exApi.remove(schedule.id);
      const os = useCurrentSchedule.getState();
      if (os.current?.id === schedule.id) os.setCurrent(null);
      setSelected(null);
      setNotice({ tone: 'ok', text: `「${schedule.name}」${eulOf(schedule.name)} 지웠습니다.` });
    } catch (e) {
      setNotice({ tone: 'error', text: message(e) });
    }
    await loadTree();
  }

  const select = (id: number) => {
    setNotice(null);
    setSelected(id);
  };
  return { schedules, schedule, select, notice, ...detail, restore, remove };
}
