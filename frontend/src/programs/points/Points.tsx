// 「관리 포인트」(계획 5 Task 11, PM 이 고른 시안 B 「3주 보드」). 한 일정의 관리 포인트(크리티컬 + 여유 k일 이하, Data Date 부터 w 주 안에
// 시작)를 주 칸(이번 주 · 다음 주 · 그다음 주 …)에 시작일 순 카드로 놓고, 아래 얇은 띠에 버전마다 들어옴·빠짐을 보인다.
// 카드를 누르면 오른쪽 자세히(여유 흐름 · 바깥 위험 · 당겨도 소용 있나 · 담당자 연락 · 만회안). 폰·좁은 창은 주 하나씩(‹ › · 밀기) → 누르면 자세히.
// params: id(일정, 없으면 OS 지금 일정) · activity(고를 포인트). 모든 값은 서버 계산값 — 화면은 날짜를 계산하지 않는다.
// 현장 관리자는 읽기만(담당자 연락 단추 없음). 「설정에서 바꾸기」(기준 k·w)는 개발 콘솔이라 관리자에게만.
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode, type RefObject, type TouchEvent } from 'react';
import { useCurrentSchedule } from '../../os/currentSchedule';
import type { ProgramProps } from '../../os/registry';
import type { ScheduleItem } from '../../os/ScheduleSelector';
import { useSession } from '../../os/session';
import { useActiveDevice } from '../../os/useIsMobile';
import { useUiContext } from '../../os/uiContext';
import { useWindows } from '../../os/windowStore';
import { api } from '../../shared/api';
import { Column, PointCard, Top } from './Board';
import { changeOf, matches, md, riskKinds, weekIndex, weekName } from './format';
import { HistoryAll, HistoryStrip } from './History';
import PointDetail from './PointDetail';
import { errorText, getHistory, getView, type History, type Point, type PointsView, type QuoteState } from './pointsApi';
import './points.css';

const NAME = '관리 포인트';
const NARROW_MAX = 720; // 프로젝트 관리·연락처와 같은 폭
const POLL_MS = 3000;
const positiveInt = (s: string | undefined) => (s && /^\d+$/.test(s) && Number(s) > 0 ? Number(s) : null);

/** 폰이거나 창 몸이 NARROW_MAX 이하면 주 하나씩(재지 못했으면 — 시험 환경 — 넓은 보드). */
function useSingle(ref: RefObject<HTMLElement | null>): boolean {
  const device = useActiveDevice();
  const [width, setWidth] = useState<number | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver((entries) => {
      const w = entries[entries.length - 1]?.contentRect.width;
      if (w) setWidth(w);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  return device === 'phone' || (width !== null && width <= NARROW_MAX);
}

function useSchedules() {
  const [items, setItems] = useState<ScheduleItem[]>([]);
  const reloadToken = useCurrentSchedule((s) => s.reloadToken);
  useEffect(() => {
    let live = true;
    api<ScheduleItem[]>('/api/schedules')
      .then((list) => live && setItems(list))
      .catch(() => live && setItems([]));
    return () => {
      live = false;
    };
  }, [reloadToken]);
  return items;
}

const prefer = (server: QuoteState | null | undefined, mine: QuoteState | undefined) =>
  server && server.status !== 'pending' ? server : mine ?? server ?? null;

/** 포인트 조회·바뀜 기록. 바깥 위험이나 근거 문장을 찾는 중이면 POLL_MS 마다 포인트 조회만 다시 읽는다. */
function useBoard(sid: number) {
  const [view, setView] = useState<PointsView | null>(null);
  const [hist, setHist] = useState<History | null>(null);
  const [error, setError] = useState('');
  const [mine, setMine] = useState<Record<string, QuoteState>>({});
  useEffect(() => {
    let live = true;
    Promise.all([getView(sid), getHistory(sid)])
      .then(([v, h]) => {
        if (!live) return;
        setView(v);
        setHist(h);
      })
      .catch((e) => live && setError(errorText(e, '관리 포인트를 읽지 못했습니다.')));
    return () => {
      live = false;
    };
  }, [sid]);
  const quotes = useMemo(() => {
    const out: Record<string, QuoteState | null> = { ...(view?.quotes ?? {}) };
    for (const [k, q] of Object.entries(mine)) out[k] = prefer(view?.quotes[k], q);
    return out;
  }, [view, mine]);
  const waiting = view !== null && (view.risk_status === 'looking' || Object.values(quotes).some((q) => q?.status === 'pending'));
  useEffect(() => {
    if (!waiting) return;
    const t = setTimeout(() => {
      getView(sid).then(setView).catch(() => undefined);
    }, POLL_MS);
    return () => clearTimeout(t);
  }, [waiting, view, sid]);
  const onQuote = useCallback((key: string, q: QuoteState) => setMine((m) => ({ ...m, [key]: q })), []);
  return { view, hist, error, quotes, onQuote };
}

/** 폰·좁은 창: 주 하나씩(‹ › · 옆으로 밀기). */
function PhoneWeeks({ weeks, byWeek, card, week, setWeek }: {
  weeks: { start: string; end: string }[];
  byWeek: Point[][];
  card(p: Point): ReactNode;
  week: number;
  setWeek(i: number): void;
}) {
  const touch = useRef<number | null>(null);
  const at = Math.min(week, Math.max(0, weeks.length - 1));
  const list = byWeek[at] ?? [];
  const onTouchStart = (e: TouchEvent) => (touch.current = e.touches[0]?.clientX ?? null);
  const onTouchEnd = (e: TouchEvent) => {
    const start = touch.current;
    const end = e.changedTouches[0]?.clientX;
    touch.current = null;
    if (start === null || end === undefined || Math.abs(end - start) < 50) return;
    setWeek(end < start ? Math.min(weeks.length - 1, at + 1) : Math.max(0, at - 1));
  };
  return (
    <>
      <div className="pt-ph-week" role="group" aria-label="주 넘기기">
        <button type="button" className="pt-arrow" aria-label="앞 주" disabled={at === 0} onClick={() => setWeek(at - 1)}>
          ‹
        </button>
        <span className="pt-ph-week-t">
          <b>{weekName(at)}</b>
          <span className="pt-muted">{weeks[at] ? `${md(weeks[at].start)} ~ ${md(weeks[at].end)} · ${list.length}곳` : ''}</span>
        </span>
        <button type="button" className="pt-arrow" aria-label="다음 주" disabled={at >= weeks.length - 1} onClick={() => setWeek(at + 1)}>
          ›
        </button>
      </div>
      <div className="pt-ph-list" onTouchStart={onTouchStart} onTouchEnd={onTouchEnd} aria-label={`${weekName(at)} 포인트`} role="region">
        {list.length === 0 && <p className="pt-muted">이 주에 시작하는 포인트가 없습니다.</p>}
        {list.map(card)}
      </div>
    </>
  );
}

function useWindowContext(windowId: string, sid: number, name: string | null, picked: string | null) {
  useEffect(() => {
    useWindows.getState().setTitle(windowId, name ? `${NAME} — ${name}` : NAME);
  }, [windowId, name]);
  useEffect(() => {
    useUiContext.getState().publish(windowId, { program: 'points', schedule_id: sid, selected_activity: picked });
  }, [windowId, sid, picked]);
}

function Body({ windowId, sid, setSid, params }: { windowId: string; sid: number; setSid(id: number): void; params: ProgramProps['params'] }) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const single = useSingle(rootRef);
  const role = useSession((s) => s.session?.user.role ?? 'user');
  const schedules = useSchedules();
  const current = useCurrentSchedule((s) => s.current);
  const { view, hist, error, quotes, onQuote } = useBoard(sid);
  const [picked, setPicked] = useState<string | null>(params?.activity ?? null);
  const [query, setQuery] = useState('');
  const [all, setAll] = useState(false);
  const [week, setWeek] = useState(0); // 폰: 보는 주(자세히에서 돌아와도 그대로)
  useEffect(() => {
    if (params?.activity) setPicked(params.activity);
  }, [params]);
  useWindowContext(windowId, sid, schedules.find((s) => s.id === sid)?.name ?? (current?.id === sid ? current.name : null), picked);

  const frame = (body: ReactNode) => (
    <div ref={rootRef} className={`pt-root${single ? ' is-single' : ''}`}>
      {body}
    </div>
  );
  if (error) return frame(<p className="pt-error pt-pad" role="alert">{error}</p>);
  if (!view || !hist) return frame(<p className="pt-muted pt-pad">관리 포인트를 읽는 중…</p>);

  const { weeks, data_date: dataDate } = hist.window;
  const shown = [...view.points].sort((a, b) => (a.es < b.es ? -1 : a.es > b.es ? 1 : 0)).filter((p) => matches(p, query));
  const byWeek = weeks.map((_, i) => shown.filter((p) => weekIndex(p.es, weeks) === i));
  const point = view.points.find((p) => p.activity_id === picked) ?? null;
  const responsible = [...(view.card?.new ?? []), ...(view.card?.tightened ?? [])].find((x) => x.activity_id === picked)?.responsible ?? [];
  const card = (p: Point) => (
    <PointCard key={p.activity_id} p={p} change={changeOf(view.diff, p)} kinds={riskKinds(view.risks, p.activity_id)} dataDate={dataDate}
      picked={p.activity_id === picked} onPick={() => setPicked(p.activity_id)} />
  );
  const detail = point && (
    <PointDetail sid={sid} point={point} version={view.version} k={view.basis.tf_days} dataDate={dataDate} change={changeOf(view.diff, point)}
      responsible={responsible} risks={view.risks} quotes={quotes} looking={view.risk_status === 'looking'} entries={hist.versions}
      canContact={role !== 'field'} onQuote={onQuote} onBack={single ? () => setPicked(null) : undefined} />
  );
  const top = (
    <Top sid={sid} schedules={schedules} onSchedule={(id) => { setPicked(null); setSid(id); }} view={view} hist={hist} query={query} setQuery={setQuery}
      shown={shown.length} isAdmin={role === 'admin'} phone={single} />
  );
  const strip = <HistoryStrip hist={hist} open={all} onToggle={() => setAll((o) => !o)} />;

  if (single)
    return frame(
      point ? (
        <div className="pt-ph-detail">{detail}</div>
      ) : (
        <>
          {top}
          <PhoneWeeks weeks={weeks} byWeek={byWeek} card={card} week={week} setWeek={setWeek} />
          {strip}
          {all && <HistoryAll hist={hist} />}
        </>
      ),
    );

  return frame(
    <>
      {top}
      <div className="pt-main">
        <div className="pt-boardpane">
          {all ? (
            <HistoryAll hist={hist} />
          ) : (
            <div className="pt-board" style={{ gridTemplateColumns: `repeat(${Math.max(1, weeks.length)}, minmax(0, 1fr))` }}>
              {weeks.map((w, i) => (
                <Column key={w.start} i={i} week={w} points={byWeek[i]}>
                  {byWeek[i].map(card)}
                </Column>
              ))}
            </div>
          )}
          {strip}
        </div>
        <aside className="pt-side" aria-label="자세히">
          {detail ?? <p className="pt-muted">카드를 누르면 여유 흐름 · 바깥 위험 · 당김 효과가 여기에 보입니다.</p>}
        </aside>
      </div>
    </>,
  );
}

export default function Points({ windowId, params }: ProgramProps) {
  const current = useCurrentSchedule((s) => s.current);
  const [chosen, setChosen] = useState<number | null>(null);
  const sid = chosen ?? positiveInt(params?.id) ?? current?.id ?? null;
  useEffect(() => {
    if (sid !== null) return;
    useWindows.getState().setTitle(windowId, NAME);
    useUiContext.getState().publish(windowId, { program: 'points', schedule_id: null, selected_activity: null });
  }, [windowId, sid]);
  if (sid === null) return <p className="pt-muted pt-pad">메뉴바에서 일정을 고르세요.</p>;
  return <Body key={sid} windowId={windowId} sid={sid} setSid={setChosen} params={params} />;
}
