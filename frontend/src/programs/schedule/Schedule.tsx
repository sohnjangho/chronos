import { Suspense, useEffect, useRef, useState } from 'react';
import { useCurrentSchedule } from '../../os/currentSchedule';
import type { ProgramProps } from '../../os/registry';
import { useUiContext } from '../../os/uiContext';
import { useWindows } from '../../os/windowStore';
import Badge from '../../shared/ui/Badge';
import Tabs from '../../shared/ui/Tabs';
import { dot } from './format';
import { useSchedule } from './scheduleStore';
import { asTab, TABS, type TabId } from './tabs';
import './schedule.css';

const positiveInt = (s: string | undefined) => (s && /^\d+$/.test(s) && Number(s) > 0 ? Number(s) : null);

/** 머리줄 오른쪽: Data Date · 완료 예정 · 크리티컬 · 음수 플로트 · 경고(서버 계산값). */
function Stats() {
  const view = useSchedule((s) => s.view);
  if (!view) return null;
  const { critical_count: critical, negative_float_count: negative, warning_count: warning } = view.summary;
  return (
    <div role="group" aria-label="일정 요약" className="sch-stats">
      <span className="sch-muted">Data Date</span>
      <span className="sch-date">{view.data_date ? dot(view.data_date) : '없음'}</span>
      <Badge tone="info">{`완료 예정 ${dot(view.finish)}`}</Badge>
      <Badge tone={critical ? 'danger' : 'neutral'}>{`크리티컬 ${critical}`}</Badge>
      <Badge tone={negative ? 'danger' : 'success'}>{`음수 플로트 ${negative}`}</Badge>
      <Badge tone={warning ? 'warning' : 'neutral'}>{`경고 ${warning}`}</Badge>
    </div>
  );
}

function NoticeBar() {
  const notice = useSchedule((s) => s.notice);
  if (!notice) return null;
  return (
    <div className={`sch-notice is-${notice.tone}`} role={notice.tone === 'error' ? 'alert' : 'status'}>
      <span>{notice.text}</span>
      <button type="button" className="sch-x" aria-label="알림 닫기" onClick={() => useSchedule.getState().setNotice(null)}>
        ×
      </button>
    </div>
  );
}

/**
 * params.activity: 그 액티비티를 고르고 그 줄로 스크롤한다(검색 창이 쓴다). 받은 params 마다 한 번 —
 * 같은 값이 다시 오면(open 을 다시 부름) 다시 하고, 일정이 바뀌었다고 다시 하지는 않는다.
 */
function useActivityParam(activity: string | undefined, params: unknown, ready: boolean) {
  const applied = useRef<unknown>(null);
  useEffect(() => {
    if (!activity || !ready || applied.current === params) return;
    applied.current = params;
    const store = useSchedule.getState();
    if (store.view?.activities.some((a) => a.id === activity)) store.revealActivity(activity);
    else store.setNotice({ tone: 'error', text: `액티비티를 찾을 수 없습니다: ${activity}` });
  }, [activity, params, ready]);
}

interface BodyProps {
  windowId: string;
  tab: TabId;
  scheduleId: number | null;
  ready: boolean;
  loadError: string | null;
}

/** 일정이 없으면 안내, 못 읽었으면 서버 글, 읽었으면 고른 탭. */
function Body({ windowId, tab, scheduleId, ready, loadError }: BodyProps) {
  if (scheduleId === null) return <p className="sch-empty">메뉴바에서 일정을 고르세요.</p>;
  if (!ready && loadError)
    return (
      <p className="sch-empty" role="alert">
        {loadError}
      </p>
    );
  if (!ready) return <p className="sch-empty">일정을 읽는 중…</p>;
  const Tab = TABS.find((t) => t.id === tab)!.component;
  return (
    <Suspense fallback={<p className="sch-empty">불러오는 중…</p>}>
      <Tab windowId={windowId} />
    </Suspense>
  );
}

/**
 * 일정판. params: id(일정, 없으면 OS 의 지금 일정을 따른다) · tab(table·gantt·cpm·progress) · activity(고를 액티비티).
 * 창 제목은 「일정판 — 일정 이름」, 고른 액티비티는 OS 화면 맥락(uiContext)으로 알린다.
 */
export default function Schedule({ windowId, params }: ProgramProps) {
  const current = useCurrentSchedule((s) => s.current);
  const scheduleId = positiveInt(params?.id) ?? current?.id ?? null;
  const [tab, setTab] = useState<TabId>(() => asTab(params?.tab) ?? 'table');
  const view = useSchedule((s) => s.view);
  const loadError = useSchedule((s) => s.loadError);
  const selected = useSchedule((s) => s.selected);
  const ready = view !== null && view.id === scheduleId;
  const name = ready ? view.name : null;

  useEffect(() => {
    const t = asTab(params?.tab);
    if (t) setTab(t);
  }, [params]);
  useEffect(() => () => useSchedule.getState().reset(), []);
  useEffect(() => {
    if (scheduleId === null) useSchedule.getState().reset();
    else void useSchedule.getState().load(scheduleId);
  }, [scheduleId]);
  useEffect(() => {
    useWindows.getState().setTitle(windowId, name ? `일정판 — ${name}` : '일정판');
  }, [windowId, name]);
  useEffect(() => {
    useUiContext.getState().publish(windowId, { program: 'schedule', schedule_id: scheduleId, selected_activity: selected });
  }, [windowId, scheduleId, selected]);
  useActivityParam(params?.activity, params, ready);

  return (
    <div className="sch-root">
      <div className="sch-head">
        <Tabs label="일정판 화면" items={TABS.map(({ id, label }) => ({ id, label }))} value={tab} onChange={(id) => setTab(id as TabId)} />
        {ready && <Stats />}
      </div>
      <NoticeBar />
      <div className="sch-body">
        <Body windowId={windowId} tab={tab} scheduleId={scheduleId} ready={ready} loadError={loadError} />
      </div>
    </div>
  );
}
