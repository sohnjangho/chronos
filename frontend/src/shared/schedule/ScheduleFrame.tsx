// 일정 도구 프로그램(스케줄·간트차트·CPM·공정률)의 창 틀. 프로그램은 자기 화면만 children 으로 넘긴다.
// - 일정: params.id, 없으면 OS 지금 일정을 따른다. 같은 일정을 보는 창들은 일정 저장소 하나를 함께 쓴다(scheduleStore).
// - 창 제목 「<프로그램> — <일정 이름>」, 머리줄 요약(서버 계산값), 알림 줄, 화면 맥락(uiContext) 알림, params.activity.
import { useEffect, useMemo, useRef, type ReactNode } from 'react';
import { useCurrentSchedule } from '../../os/currentSchedule';
import { useUiContext } from '../../os/uiContext';
import { useWindows } from '../../os/windowStore';
import Badge from '../ui/Badge';
import { dot } from './format';
import { ScheduleScope, useSchedule, useScheduleStore, type Scope } from './scope';
import { holdSchedule, scheduleStore, type ScheduleStore } from './scheduleStore';
import './schedule.css';

const positiveInt = (s: string | undefined) => (s && /^\d+$/.test(s) && Number(s) > 0 ? Number(s) : null);

/**
 * 머리줄: Data Date · 완료 예정 · 크리티컬 · 음수 플로트 · 경고(서버 계산값).
 * dataDate 를 주면 Data Date 자리에 그것을(스케줄의 고치는 칸), extra 는 끝에 더 그린다.
 */
function Stats({ dataDate, extra }: { dataDate?: ReactNode; extra?: ReactNode }) {
  const view = useSchedule((s) => s.view);
  if (!view) return null;
  const { critical_count: critical, negative_float_count: negative, warning_count: warning } = view.summary;
  return (
    <div role="group" aria-label="일정 요약" className="sch-stats">
      {dataDate ?? (
        <>
          <span className="sch-muted">Data Date</span>
          <span className="sch-date">{view.data_date ? dot(view.data_date) : '없음'}</span>
        </>
      )}
      <Badge tone="info">{`완료 예정 ${dot(view.finish)}`}</Badge>
      <Badge tone={critical ? 'danger' : 'neutral'}>{`크리티컬 ${critical}`}</Badge>
      <Badge tone={negative ? 'danger' : 'success'}>{`음수 플로트 ${negative}`}</Badge>
      <Badge tone={warning ? 'warning' : 'neutral'}>{`경고 ${warning}`}</Badge>
      {extra}
    </div>
  );
}

/** 알림 줄. 다른 창의 동작에서 난 안내(windowId 가 다른 것)는 보이지 않는다. */
function NoticeBar({ windowId }: { windowId: string }) {
  const store = useScheduleStore();
  const notice = useSchedule((s) => s.notice);
  if (!notice || (notice.windowId && notice.windowId !== windowId)) return null;
  return (
    <div className={`sch-notice is-${notice.tone}`} role={notice.tone === 'error' ? 'alert' : 'status'}>
      <span>{notice.text}</span>
      <button type="button" className="sch-x" aria-label="알림 닫기" onClick={() => store.getState().setNotice(null)}>
        ×
      </button>
    </div>
  );
}

/**
 * params.activity: 그 액티비티를 고르고 그 줄을 보이게 한다(검색 창이 쓴다). 받은 params 마다 한 번 —
 * 같은 값이 다시 오면(open 을 다시 부름) 다시 하고, 일정이 바뀌었다고 다시 하지는 않는다.
 */
function useActivityParam(windowId: string, activity: string | undefined, params: unknown) {
  const store = useScheduleStore();
  const ready = useSchedule((s) => s.view !== null);
  const applied = useRef<unknown>(null);
  useEffect(() => {
    if (!activity || !ready || applied.current === params) return;
    applied.current = params;
    const s = store.getState();
    if (s.view?.activities.some((a) => a.id === activity)) s.revealActivity(activity, windowId);
    else s.setNotice({ tone: 'error', text: `액티비티를 찾을 수 없습니다: ${activity}`, windowId });
  }, [store, windowId, activity, params, ready]);
}

interface FrameProps {
  windowId: string;
  params?: Record<string, string>;
  /** 프로그램 id(화면 맥락)와 이름(창 제목). */
  programId: string;
  name: string;
  /** 일정을 읽은 뒤에 그릴 프로그램 화면. 그 안에서는 useSchedule((s) => s.view)! 로 읽어도 된다. */
  children: ReactNode;
  /** 머리줄의 Data Date 자리에 그릴 것(없으면 읽기 전용 글). 일정을 읽은 뒤에만 그린다. */
  dataDate?: ReactNode;
  /** 머리줄 끝에 더 그릴 것(프로그램의 경고 등). */
  headExtra?: ReactNode;
}

/** 일정 하나를 잡은 창 안: 제목·화면 맥락·params.activity, 읽는 중·못 읽음·화면. */
function Held({ windowId, params, programId, name, children, dataDate, headExtra }: FrameProps) {
  const store = useScheduleStore();
  const view = useSchedule((s) => s.view);
  const loadError = useSchedule((s) => s.loadError);
  const selected = useSchedule((s) => s.selected);
  const scheduleName = view?.name ?? null;
  useEffect(() => {
    useWindows.getState().setTitle(windowId, scheduleName ? `${name} — ${scheduleName}` : name);
  }, [windowId, name, scheduleName]);
  useEffect(() => {
    useUiContext.getState().publish(windowId, { program: programId, schedule_id: store.getState().scheduleId, selected_activity: selected });
  }, [windowId, programId, store, selected]);
  useActivityParam(windowId, params?.activity, params);

  const body = view ? (
    children
  ) : loadError ? (
    <p className="sch-empty" role="alert">
      {loadError}
    </p>
  ) : (
    <p className="sch-empty">일정을 읽는 중…</p>
  );
  return (
    <div className="sch-root">
      {view && (
        <div className="sch-head">
          <Stats dataDate={dataDate} extra={headExtra} />
        </div>
      )}
      <NoticeBar windowId={windowId} />
      {/* 일정이 바뀌면 프로그램 화면을 새로 그린다(찾기·접기 같은 화면 상태가 다른 일정으로 넘어가지 않게). */}
      <div className="sch-body" key={store.getState().scheduleId}>
        {body}
      </div>
    </div>
  );
}

/** 일정이 없을 때(params.id 도 OS 지금 일정도 없음): 메뉴바에서 고르라고 안내한다. */
function NoSchedule({ windowId, programId, name }: Pick<FrameProps, 'windowId' | 'programId' | 'name'>) {
  useEffect(() => {
    useWindows.getState().setTitle(windowId, name);
    useUiContext.getState().publish(windowId, { program: programId, schedule_id: null, selected_activity: null });
  }, [windowId, programId, name]);
  return (
    <div className="sch-root">
      <p className="sch-empty">메뉴바에서 일정을 고르세요.</p>
    </div>
  );
}

/**
 * 창을 열 때 늘 다시 읽는다 — 다른 창이 잡고 있던 저장소는 다른 곳(탐색기 되돌리기·승인)에서 바뀐 버전보다 낡았을 수 있다.
 * 버전이 그대로면 다른 창의 지연 알림(lastChange)은 둔다(다시 읽기는 알림을 거두므로).
 */
async function reread(store: ScheduleStore) {
  const { view, lastChange } = store.getState();
  await store.getState().load();
  const s = store.getState();
  if (lastChange && !s.lastChange && s.view?.version === view?.version) store.setState({ lastChange });
}

export default function ScheduleFrame(props: FrameProps) {
  const { windowId, params } = props;
  const current = useCurrentSchedule((s) => s.current);
  const scheduleId = positiveInt(params?.id) ?? current?.id ?? null;
  const scope = useMemo<Scope | null>(() => (scheduleId === null ? null : { store: scheduleStore(scheduleId), windowId }), [scheduleId, windowId]);
  useEffect(() => {
    if (!scope) return;
    const { store } = scope;
    const release = holdSchedule(store, windowId);
    void reread(store);
    // 화면 단추로 버전이 바뀐 곳(탐색기 되돌리기·승인함 승인)은 reloadToken 을 올린다 — 열린 창도 다시 읽는다.
    const stop = useCurrentSchedule.subscribe((s, prev) => {
      if (s.reloadToken !== prev.reloadToken) void store.getState().load();
    });
    return () => {
      stop();
      release();
    };
  }, [scope, windowId]);
  if (!scope) return <NoSchedule {...props} />;
  return (
    <ScheduleScope.Provider value={scope}>
      <Held {...props} />
    </ScheduleScope.Provider>
  );
}
