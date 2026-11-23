// 지연 기록 창의 단추 동작: 비교판 · 다시 분석 · 간트에서 보기 · 만회안 요청. 실패하면 알림 줄에 서버 글 그대로.
import { useEffect, useRef, useState } from 'react';
import { useCurrentSchedule } from '../../os/currentSchedule';
import { useSchedulePreview } from '../../os/schedulePreview';
import { useWindows } from '../../os/windowStore';
import { analyzeDelays, getDelayPreview, makeScenario, type DelayEvent, type DelaysData } from './delaysApi';
import { clearDelayPreview, errText } from './useDelays';

export type Notice = { tone: 'info' | 'error'; text: string };

export const ASK_ALL = '지연 기록을 반영한 만회 계획을 만들어 줘';
export const openProgram = (id: string, params: Record<string, string>) => useWindows.getState().open(id, params);

/** 사건 하나의 만회안 요청(대화창). */
const recoverOne = (e: DelayEvent) => openProgram('chat', { ask: `${e.activity_id} ${e.activity_name} ${e.cause} 지연을 만회할 계획을 만들어 줘` });

export function useActions(scheduleId: number, setData: (d: DelaysData) => void) {
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const sid = String(scheduleId);
  // 창이 닫히거나 다른 일정으로 바뀐 뒤(언마운트) 늦게 온 응답으로 미리 보기를 걸거나 창을 열지 않는다.
  const live = useRef(true);
  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);

  /** 사건이 바뀌면 걸어 둔 지연 미리 보기는 낡았으므로 지우고, 열린 간트·공정률 창의 「기록된 지연」 띠가 다시 세게 한다. */
  const redraw = (d: DelaysData) => {
    setData(d);
    clearDelayPreview(scheduleId);
    useCurrentSchedule.getState().bumpDelays();
  };
  const run = async (work: () => Promise<void>) => {
    setBusy(true);
    setNotice(null);
    try {
      await work();
    } catch (e) {
      setNotice({ tone: 'error', text: errText(e, '요청을 처리할 수 없습니다.') });
    } finally {
      setBusy(false);
    }
  };

  const compare = () =>
    run(async () => {
      const { scenario_id } = await makeScenario(scheduleId);
      if (!live.current) return;
      openProgram('compare', { id: sid, base: 'current', other: `s:${scenario_id}` });
    });
  const analyze = () =>
    run(async () => {
      redraw(await analyzeDelays(scheduleId));
      setNotice({ tone: 'info', text: '열린 사건을 지금 일정으로 다시 분석했습니다.' });
    });
  /** 열린 사건: 지연 미리 보기를 걸고(간트가 예측 막대를 옮기고 이전 자리를 점선으로) 연다. 반영된 사건: 저장된 일정 그대로 연다. */
  const gantt = (e: DelayEvent) =>
    run(async () => {
      if (e.status === 'open') {
        const p = await getDelayPreview(scheduleId);
        if (!live.current) return;
        const store = useSchedulePreview.getState();
        if (store.previews[scheduleId]?.source === 'conditions') setNotice({ tone: 'info', text: '조건 미리 보기를 지연 미리 보기로 바꿨습니다.' });
        store.set({ scheduleId, view: p.view, moved: p.moved, source: 'delays' });
      } else clearDelayPreview(scheduleId);
      openProgram('gantt', { id: sid, activity: e.activity_id });
    });

  return { busy, notice, setNotice, redraw, compare, analyze, gantt, recover: recoverOne };
}
