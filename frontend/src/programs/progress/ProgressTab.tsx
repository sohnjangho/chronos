// 「공정률」 화면(ScheduleFrame 의 children): 도구줄(단위 · 가중치 방식 · 그림 내보내기, Data Date 는 창 머리줄) · 요약 띠 ·
// S-커브와 마일스톤 · WBS · 일정 수행 지수 추이 · 지연 상위 · 앞으로 3주. 모든 값은 진행 API(서버 계산)에서 온다.
// 같은 일정 저장소의 버전이나 가중치 방식이 바뀌면(다른 창에서 고침) 다시 불러온다.
import { useEffect, useState, type ReactNode } from 'react';
import { ApiError } from '../../shared/api';
import { dot } from '../../shared/schedule/format';
import type { ScheduleView } from '../../shared/schedule/scheduleApi';
import { useSchedule, useScheduleStore } from '../../shared/schedule/scope';
import { useSession } from '../../os/session';
import Button from '../../shared/ui/Button';
import { VisualButton } from '../../shared/visual/VisualFrame';
import DelayTop from './DelayTop';
import { exportImage } from './exportSheet';
import FieldHub from './FieldHub';
import { pct, weightModeLabel } from './format';
import KpiRow from './KpiRow';
import Lookahead from './Lookahead';
import MilestoneTable from './MilestoneTable';
import { getProgress, type ProgressData, type Unit } from './progressApi';
import SCurve from './SCurveCard';
import SpiTrend from './SpiTrend';
import WbsTable from './WbsTable';
import {
  SPAN_OPTIONS,
  WIDGET_META,
  loadWidgetLayout,
  moveWidget,
  reorderWidget,
  resetWidgetLayout,
  saveWidgetLayout,
  setWidgetSpan,
  toggleWidgetVisible,
  type WidgetId,
  type WidgetItem,
  type WidgetSpan,
} from './widgetLayout';
import './progress.css';

/** Plan 시작 = 액티비티 Plan 시작 가운데 가장 이른 날(서버 값 글자 비교만). */
function planStartOf(view: ScheduleView | null): string | null {
  let first: string | null = null;
  for (const a of view?.activities ?? []) if (a.plan_start && (first === null || a.plan_start < first)) first = a.plan_start;
  return first;
}

/** 보고서용 그림은 지금 버전으로만: 읽는 중이면 끄고, 보이는 공정률이 일정의 지금 버전이 아니면 까닭을 보인다. */
function visualOff(data: ProgressData | null, version: number | undefined): string | undefined {
  if (!data) return '';
  return version !== undefined && data.version !== version ? '지금 버전으로만 만들 수 있습니다' : undefined;
}

function useProgress(id: number, unit: Unit, version: number | undefined, weightMode: string | undefined) {
  const [state, setState] = useState<{ data: ProgressData | null; error: string | null }>({ data: null, error: null });
  useEffect(() => {
    let live = true;
    getProgress(id, unit).then(
      (data) => live && setState({ data, error: null }),
      (e: unknown) => live && setState({ data: null, error: e instanceof ApiError ? e.message : '공정률을 읽을 수 없습니다.' }),
    );
    return () => {
      live = false;
    };
  }, [id, unit, version, weightMode]);
  return state;
}

function Toolbar({
  scheduleId,
  data,
  version,
  unit,
  view,
  editMode,
  hiddenCount,
  onToggleField,
  onToggleEdit,
  onUnit,
  onImage,
}: {
  scheduleId: number;
  data: ProgressData | null;
  version?: number;
  unit: Unit;
  view: 'dashboard' | 'field';
  editMode: boolean;
  hiddenCount: number;
  onToggleField: () => void;
  onToggleEdit: () => void;
  onUnit: (u: Unit) => void;
  onImage: () => void;
}) {
  return (
    <div role="group" aria-label="공정률 도구" className="sch-toolbar pg-toolbar">
      {data?.data_date_assumed && (
        <>
          <span className="pg-assumed">{`오늘로 가정 ${dot(data.data_date)}`}</span>
          <span className="sch-muted">일정에 Data Date 가 없어 오늘 날짜로 계산했습니다</span>
          <span className="sch-sep" />
        </>
      )}
      <span className="sch-muted">단위</span>
      <div role="group" aria-label="단위" className="pg-seg">
        {(['week', 'month'] as const).map((u) => (
          <button key={u} type="button" aria-pressed={unit === u} onClick={() => onUnit(u)}>
            {u === 'week' ? '주' : '월'}
          </button>
        ))}
      </div>
      {data && (
        <span className="pg-weight" title="가중치 방식은 스케줄 창에서 바꿉니다">{`가중치: ${weightModeLabel(data.weight_mode)}`}</span>
      )}
      <Button aria-pressed={view === 'field'} onClick={onToggleField}>
        현장 모바일 점검
      </Button>
      {view === 'dashboard' && (
        <Button
          aria-pressed={editMode}
          className={editMode ? 'pg-edit-toggle is-active' : 'pg-edit-toggle'}
          onClick={onToggleEdit}
        >
          {hiddenCount > 0 && !editMode ? `배치 편집 (숨김 ${hiddenCount})` : '배치 편집'}
        </Button>
      )}
      <span className="sch-gap" />
      <Button onClick={onImage} disabled={!data}>
        그림 내보내기
      </Button>
      <VisualButton scheduleId={scheduleId} kind="s_curve" version={data?.version} unit={unit} disabledReason={visualOff(data, version)} />
    </div>
  );
}

function WidgetEditBar({
  layout,
  onToggleVisible,
  onReset,
  onDone,
}: {
  layout: WidgetItem[];
  onToggleVisible: (id: WidgetId) => void;
  onReset: () => void;
  onDone: () => void;
}) {
  return (
    <div role="region" aria-label="위젯 배치 도구" className="pg-edit-bar">
      <div className="pg-edit-chips">
        <span className="pg-muted">위젯 표시:</span>
        {layout.map((item) => {
          const label = WIDGET_META[item.id].shortLabel;
          return (
            <button
              key={item.id}
              type="button"
              className="pg-edit-chip"
              aria-pressed={item.visible}
              onClick={() => onToggleVisible(item.id)}
            >
              {`${item.visible ? '✓' : '+'} ${label}`}
            </button>
          );
        })}
      </div>
      <div className="pg-edit-actions">
        <span className="pg-muted">카드를 끌어 순서 변경</span>
        <Button onClick={onReset}>기본 배치 복원</Button>
        <Button onClick={onDone}>편집 완료</Button>
      </div>
    </div>
  );
}

function renderWidget(id: WidgetId, data: ProgressData, scheduleId: number, planStart: string | null): ReactNode {
  switch (id) {
    case 'kpi':
      return <KpiRow data={data} planStart={planStart} />;
    case 'scurve':
      return <SCurve data={data} />;
    case 'milestone':
      return <MilestoneTable data={data} />;
    case 'wbs':
      return <WbsTable data={data} />;
    case 'spi':
      return <SpiTrend data={data} />;
    case 'delay':
      return <DelayTop data={data} scheduleId={scheduleId} />;
    case 'lookahead':
      return <Lookahead data={data} />;
  }
}

/** Plan 이 없는(계획 뒤에 더한) 액티비티를 계획 지표에서 뺐다는 알림. */
function AddedNote({ added }: { added: ProgressData['added_after_plan'] }) {
  return (
    <p className="pg-note" role="note">
      {`Plan 이 없는 액티비티 ${added.count}개는 계획 공정률·S-커브·일정 수행 지수에서 뺐습니다 · 그것들의 실적 ${pct(added.actual_pct)}%`}
    </p>
  );
}

/** 위젯을 모두 숨겼을 때. */
function NoWidgets({ onReset }: { onReset: () => void }) {
  return (
    <div className="pg-card pg-widgets-empty">
      <p className="pg-empty">표시된 위젯이 없습니다.</p>
      <Button onClick={onReset}>기본 배치 복원</Button>
    </div>
  );
}

/** 배치 편집 중 위젯 위의 막대: 끌기 손잡이 · 앞뒤로 옮기기 · 너비 · 숨기기. */
function WidgetBar({
  item,
  shortLabel,
  first,
  last,
  onMove,
  onSpan,
  onToggleVisible,
}: {
  item: WidgetItem;
  shortLabel: string;
  first: boolean;
  last: boolean;
  onMove: (id: WidgetId, delta: -1 | 1) => void;
  onSpan: (id: WidgetId, span: WidgetSpan) => void;
  onToggleVisible: (id: WidgetId) => void;
}) {
  return (
    <div className="pg-widget-bar">
      <span className="pg-widget-grip" aria-hidden="true">
        ⋮⋮
      </span>
      <span className="pg-widget-name">{shortLabel}</span>
      <button
        type="button"
        className="pg-wbtn"
        aria-label={`${shortLabel} 앞으로 이동`}
        disabled={first}
        onClick={() => onMove(item.id, -1)}
      >
        ←
      </button>
      <button
        type="button"
        className="pg-wbtn"
        aria-label={`${shortLabel} 뒤로 이동`}
        disabled={last}
        onClick={() => onMove(item.id, 1)}
      >
        →
      </button>
      <div role="group" aria-label={`${shortLabel} 너비`} className="pg-span-seg">
        {SPAN_OPTIONS.map((opt) => (
          <button
            key={opt.span}
            type="button"
            aria-pressed={item.span === opt.span}
            onClick={() => onSpan(item.id, opt.span)}
          >
            {opt.label}
          </button>
        ))}
      </div>
      <button
        type="button"
        className="pg-wbtn is-hide"
        aria-label={`${shortLabel} 숨기기`}
        onClick={() => onToggleVisible(item.id)}
      >
        ×
      </button>
    </div>
  );
}

function Body({
  data,
  scheduleId,
  planStart,
  layout,
  editMode,
  onMove,
  onReorder,
  onSpan,
  onToggleVisible,
  onReset,
}: {
  data: ProgressData;
  scheduleId: number;
  planStart: string | null;
  layout: WidgetItem[];
  editMode: boolean;
  onMove: (id: WidgetId, delta: -1 | 1) => void;
  onReorder: (fromId: WidgetId, toId: WidgetId) => void;
  onSpan: (id: WidgetId, span: WidgetSpan) => void;
  onToggleVisible: (id: WidgetId) => void;
  onReset: () => void;
}) {
  const [dragId, setDragId] = useState<WidgetId | null>(null);
  const [overId, setOverId] = useState<WidgetId | null>(null);
  const added = data.added_after_plan;
  const visibleItems = layout.filter((w) => w.visible);

  return (
    <>
      {added.count > 0 && <AddedNote added={added} />}
      {visibleItems.length === 0 ? (
        <NoWidgets onReset={onReset} />
      ) : (
        <div className={editMode ? 'pg-widget-grid is-editing' : 'pg-widget-grid'} aria-label="공정률 위젯 보드">
          {visibleItems.map((item, visibleIdx) => {
            const { shortLabel } = WIDGET_META[item.id];
            const widgetClass = [
              'pg-widget',
              dragId === item.id ? 'is-dragging' : '',
              overId === item.id && dragId !== item.id ? 'is-drop-target' : '',
            ]
              .filter(Boolean)
              .join(' ');
            return (
              <div
                key={item.id}
                className={widgetClass}
                data-widget-id={item.id}
                data-span={item.span}
                draggable={editMode}
                onDragStart={(e) => {
                  if (!editMode) return;
                  setDragId(item.id);
                  e.dataTransfer?.setData('text/plain', item.id);
                  if (e.dataTransfer) e.dataTransfer.effectAllowed = 'move';
                }}
                onDragOver={(e) => {
                  if (!editMode) return;
                  e.preventDefault();
                  if (e.dataTransfer) e.dataTransfer.dropEffect = 'move';
                  if (overId !== item.id) setOverId(item.id);
                }}
                onDragLeave={() => {
                  if (overId === item.id) setOverId(null);
                }}
                onDrop={(e) => {
                  if (!editMode) return;
                  e.preventDefault();
                  const source = (dragId ?? (e.dataTransfer?.getData('text/plain') as WidgetId)) || null;
                  if (source && source !== item.id) onReorder(source, item.id);
                  setDragId(null);
                  setOverId(null);
                }}
                onDragEnd={() => {
                  setDragId(null);
                  setOverId(null);
                }}
              >
                {editMode && (
                  <WidgetBar
                    item={item}
                    shortLabel={shortLabel}
                    first={visibleIdx === 0}
                    last={visibleIdx === visibleItems.length - 1}
                    onMove={onMove}
                    onSpan={onSpan}
                    onToggleVisible={onToggleVisible}
                  />
                )}
                <div className="pg-widget-content">{renderWidget(item.id, data, scheduleId, planStart)}</div>
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}

export default function ProgressTab({
  initialView = 'dashboard',
  humanRead = false,
}: { initialView?: 'dashboard' | 'field'; /** 현장 허브를 사진 탭의 사람 판독 목록으로 연다(「주의할 일정」의 「사람 판독 n」). */ humanRead?: boolean } = {}) {
  const scheduleId = useScheduleStore().getState().scheduleId;
  const version = useSchedule((s) => s.view?.version);
  const weightMode = useSchedule((s) => s.view?.weight_mode);
  const name = useSchedule((s) => s.view?.name ?? '');
  const planStart = useSchedule((s) => planStartOf(s.view));
  const userId = useSession((s) => s.session?.user.id ?? null);
  const [unit, setUnit] = useState<Unit>('week');
  const [view, setView] = useState<'dashboard' | 'field'>(initialView);
  const [seenInitial, setSeenInitial] = useState(initialView);
  const [editMode, setEditMode] = useState(false);
  const [layout, setLayout] = useState<WidgetItem[]>(() => loadWidgetLayout(userId));

  useEffect(() => {
    setLayout(loadWidgetLayout(userId));
  }, [userId]);

  if (initialView !== seenInitial) {
    setSeenInitial(initialView);
    setView(initialView);
    if (initialView === 'field') setEditMode(false);
  }

  const updateLayout = (fn: (prev: WidgetItem[]) => WidgetItem[]) => {
    setLayout((prev) => {
      const next = fn(prev);
      saveWidgetLayout(userId, next);
      return next;
    });
  };

  const hiddenCount = layout.filter((w) => !w.visible).length;
  const { data, error } = useProgress(scheduleId, unit, version, weightMode);
  const onImage = () => data && void exportImage(data, name, `${name} v${data.version} 공정률`);

  return (
    <div className={view === 'field' ? 'pg-tab is-field-view' : 'pg-tab'}>
      <Toolbar
        scheduleId={scheduleId}
        data={data}
        version={version}
        unit={unit}
        view={view}
        editMode={editMode}
        hiddenCount={hiddenCount}
        onToggleField={() => {
          setView((v) => {
            const next = v === 'field' ? 'dashboard' : 'field';
            if (next === 'field') setEditMode(false);
            return next;
          });
        }}
        onToggleEdit={() => setEditMode((e) => !e)}
        onUnit={setUnit}
        onImage={onImage}
      />
      <div className="pg-scroll">
        {view === 'dashboard' && editMode && (
          <WidgetEditBar
            layout={layout}
            onToggleVisible={(id) => updateLayout((prev) => toggleWidgetVisible(prev, id))}
            onReset={() => updateLayout(() => resetWidgetLayout())}
            onDone={() => setEditMode(false)}
          />
        )}
        {view === 'field' ? (
          <FieldHub scheduleId={scheduleId} {...(humanRead ? { initialTab: 'photo', initialPhotoView: 'human' } as const : {})} />
        ) : error ? (
          <p className="pg-empty" role="alert">
            {error}
          </p>
        ) : data ? (
          <Body
            data={data}
            scheduleId={scheduleId}
            planStart={planStart}
            layout={layout}
            editMode={editMode}
            onMove={(id, delta) => updateLayout((prev) => moveWidget(prev, id, delta))}
            onReorder={(fromId, toId) => updateLayout((prev) => reorderWidget(prev, fromId, toId))}
            onSpan={(id, span) => updateLayout((prev) => setWidgetSpan(prev, id, span))}
            onToggleVisible={(id) => updateLayout((prev) => toggleWidgetVisible(prev, id))}
            onReset={() => updateLayout(() => resetWidgetLayout())}
          />
        ) : (
          <p className="pg-empty">공정률을 읽는 중…</p>
        )}
      </div>
    </div>
  );
}
