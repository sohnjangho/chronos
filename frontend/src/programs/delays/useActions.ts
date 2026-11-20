// 지연 기록 창의 단추 동작: 비교판 · 다시 분석 · 간트에서 보기 · 만회안 요청. 실패하면 알림 줄에 서버 글 그대로.
import { useState } from 'react';
import { useSchedulePreview } from '../../os/schedulePreview';
import { useWindows } from '../../os/windowStore';
import { analyzeDelays, getDelayPreview, makeScenario, type DelayEvent, type DelaysData } from './delaysApi';
import { clearDelayPreview, errText } from './useDelays';

export type Notice = { tone: 'info' | 'error'; text: string };

export const ASK_ALL = '지연 기록을 반영한 만회 계획을 만들어 줘';
export const openProgram = (id: string, params: Record<string, string>) => useWindows.getState().open(id, params);

export function useActions(scheduleId: number, setData: (d: DelaysData) => void) {
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const sid = String(scheduleId);

  /** 사건이 바뀌면 걸어 둔 지연 미리 보기는 낡았으므로 지운다. */
  const redraw = (d: DelaysData) => {
    setData(d);
    clearDelayPreview(scheduleId);
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
        useSchedulePreview.getState().set({ scheduleId, view: p.view, moved: p.moved, source: 'delays' });
      } else clearDelayPreview(scheduleId);
      openProgram('gantt', { id: sid, activity: e.activity_id });
    });
  const recover = (e: DelayEvent) => openProgram('chat', { ask: `${e.activity_name} ${e.cause} 지연을 만회할 계획을 만들어 줘` });

  return { busy, notice, setNotice, redraw, compare, analyze, gantt, recover };
}
