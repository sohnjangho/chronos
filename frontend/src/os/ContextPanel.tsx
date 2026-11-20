import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';
import { api } from '../shared/api';
import Tabs from '../shared/ui/Tabs';
import { useAiChat } from './aiChat';
import { ActivityTab, AiTab, EvidenceTab } from './ContextTabs';
import { useContextPanel, type ContextSource, type ContextTab } from './contextStore';
import { useCurrentSchedule } from './currentSchedule';
import { useEvidence, type EvidenceItem } from './evidence';
import { PanelIcon } from './icons';
import { getProgram } from './registry';
import { useShell } from './shell';
import { activeWindow, topWindow, useWindows } from './windowStore';
import './overlays.css';

interface ScheduleView {
  name: string;
  level: string;
  version: number;
  data_date: string | null;
  finish: string;
  plan_finish: string | null;
  summary: { critical_count: number; negative_float_count: number; warning_count: number };
}

/** 패널이 열려 있는 동안, 창을 열거나 앞으로 가져올 때마다(topZ) 그 창을 출처로 삼는다. 창을 닫는 것으로는 바뀌지 않는다. */
function useSourceTracking(open: boolean) {
  const topZ = useWindows((s) => s.topZ);
  useEffect(() => {
    if (!open) return;
    const st = useWindows.getState();
    const w = activeWindow(st) ?? topWindow(st.wins);
    if (w) useContextPanel.getState().setSource({ id: w.id, programId: w.programId, title: w.title, params: w.params });
  }, [open, topZ]);
}

/** 업무 프로그램(일정판·조건) 창이면 지금 일정 요약을 근거로 쓴다(그 창이 따로 넘긴 근거가 없을 때). */
function useScheduleEvidence(source: ContextSource | null, scheduleId: number | null): EvidenceItem[] | null {
  const isWork = source !== null && getProgram(source.programId)?.kind === 'work';
  const [view, setView] = useState<ScheduleView | null>(null);
  useEffect(() => {
    setView(null);
    if (!isWork || scheduleId === null) return;
    let live = true;
    api<ScheduleView>(`/api/schedules/${scheduleId}`).then((v) => live && setView(v), () => {});
    return () => {
      live = false;
    };
  }, [isWork, scheduleId]);
  if (!isWork || !view) return null;
  return [
    { label: '일정', value: `${view.name} · ${view.level}`, detail: `버전 ${view.version}` },
    { label: '기준일 (Data Date)', value: view.data_date ?? '없음' },
    { label: '완료 예정', value: view.finish },
    { label: 'Plan 완료', value: view.plan_finish ?? '없음' },
    { label: '크리티컬 액티비티', value: `${view.summary.critical_count}개` },
    { label: '경고', value: `${view.summary.warning_count}개`, detail: `음수 여유 ${view.summary.negative_float_count}개` },
  ];
}

function ResizeEdge({ width }: { width: number }) {
  const setWidth = useContextPanel.getState().setWidth;
  function onPointerDown(e: ReactPointerEvent) {
    e.preventDefault();
    const x0 = e.clientX;
    const w0 = width;
    const move = (ev: PointerEvent) => (ev.buttons === 0 ? stop() : setWidth(w0 + (x0 - ev.clientX)));
    const stop = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', stop);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', stop);
  }
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="패널 폭 조절"
      aria-valuenow={width}
      tabIndex={0}
      className="os-ctx-edge"
      onPointerDown={onPointerDown}
      onKeyDown={(e) => {
        if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') setWidth(width + (e.key === 'ArrowLeft' ? 16 : -16));
      }}
    />
  );
}

function Panel() {
  const { width, tab, source } = useContextPanel();
  const wins = useWindows((s) => s.wins);
  const scheduleId = useCurrentSchedule((s) => s.current?.id ?? null);
  const live = source ? wins.find((w) => w.id === source.id) : undefined;
  const stale = source !== null && !live;
  const title = live?.title ?? source?.title ?? '';
  const passed = useEvidence((s) => (source ? s.byWindow[source.id] : undefined));
  const scheduleEvidence = useScheduleEvidence(source, scheduleId);
  const evidence = passed ?? scheduleEvidence ?? [];
  const tabs = [
    { id: 'ai', label: 'AI' },
    { id: 'evidence', label: <>근거 <span className="os-ctx-count">{evidence.length}</span></> },
    { id: 'activity', label: '활동' },
  ];
  return (
    <aside className="os-ctx" aria-label="Context 패널" style={{ width }}>
      <ResizeEdge width={width} />
      <div className="os-ctx-head">
        {source && stale && <span className="os-ctx-src is-closed">닫힌 창: {title}</span>}
        {source && !stale && (
          <button type="button" className="os-ctx-src" aria-label={`출처: ${title}`} onClick={() => useWindows.getState().focus(source.id)}>
            {title}
          </button>
        )}
        {!source && <span className="os-ctx-src is-closed">출처 창 없음</span>}
        <button type="button" className="os-ctx-close" aria-label="Context 패널 닫기" onClick={() => useContextPanel.getState().close()}>
          ×
        </button>
      </div>
      <Tabs items={tabs} value={tab} onChange={(t) => useContextPanel.getState().setTab(t as ContextTab)} label="Context 패널 탭" />
      <div key={scheduleId ?? 'none'} className={`os-ctx-body${stale ? ' is-stale' : ''}`}>
        {tab === 'ai' && <AiTab source={source} stale={stale} />}
        {tab === 'evidence' && <EvidenceTab items={evidence} />}
        {tab === 'activity' && <ActivityTab scheduleId={scheduleId} />}
      </div>
    </aside>
  );
}

/** Context 패널과 여는 단추(오른쪽 아래 48px). Ctrl+Alt+. 로도 연다. 닫으면 출처 창(없으면 여는 단추)으로 포커스. */
export default function ContextPanel() {
  const open = useContextPanel((s) => s.open);
  const scheduleId = useCurrentSchedule((s) => s.current?.id ?? null);
  // 확대한 창이 있어 Dock 이 숨으면 단추도 함께 숨는다(창 내용을 가리지 않게). Dock 을 드러내면 함께 나온다.
  const maximized = useWindows((s) => s.wins.some((w) => w.maximized && !w.minimized));
  const revealed = useShell((s) => s.dockRevealed);
  const dockHidden = maximized && !revealed;
  const button = useRef<HTMLButtonElement>(null);
  const wasOpen = useRef(open);
  useSourceTracking(open);
  useEffect(() => useAiChat.getState().bindSchedule(scheduleId), [scheduleId]);
  useEffect(() => {
    const src = useContextPanel.getState().source;
    const st = useWindows.getState();
    const alive = src !== null && st.wins.some((w) => w.id === src.id);
    if (wasOpen.current && !open && !alive) {
      // 여는 단추가 숨어 있으면(확대한 창 + Dock 숨김) 맨 앞 창으로 포커스를 준다.
      const front = dockHidden ? (activeWindow(st) ?? topWindow(st.wins)) : null;
      if (front) st.focus(front.id);
      else button.current?.focus();
    }
    wasOpen.current = open;
  }, [open]); // 닫힐 때 한 번
  if (open) return <Panel />;
  return (
    <button
      ref={button}
      type="button"
      className="os-ctx-open"
      hidden={dockHidden}
      aria-label="Context 패널 열기 (Ctrl+Alt+.)"
      data-tip="Context 패널 열기 (Ctrl+Alt+.)"
      onClick={() => useContextPanel.getState().toggle()}
    >
      <PanelIcon />
    </button>
  );
}
