// 「공정률」 화면(ScheduleFrame 의 children): 도구줄(Data Date · 단위 · 가중치 방식 · 그림 내보내기) · 요약 띠 ·
// S-커브와 마일스톤 · WBS · 일정 수행 지수 추이 · 지연 상위 · 앞으로 3주. 모든 값은 진행 API(서버 계산)에서 온다.
// 같은 일정 저장소의 버전이나 가중치 방식이 바뀌면(다른 창에서 고침) 다시 불러온다.
import { useEffect, useState } from 'react';
import { ApiError } from '../../shared/api';
import { dot } from '../../shared/schedule/format';
import type { ScheduleView } from '../../shared/schedule/scheduleApi';
import { useSchedule, useScheduleStore } from '../../shared/schedule/scope';
import Button from '../../shared/ui/Button';
import DelayTop from './DelayTop';
import { exportImage } from './exportSheet';
import { pct, weightModeLabel } from './format';
import KpiRow from './KpiRow';
import Lookahead from './Lookahead';
import MilestoneTable from './MilestoneTable';
import { getProgress, type ProgressData, type Unit } from './progressApi';
import SCurve from './SCurveCard';
import SpiTrend from './SpiTrend';
import WbsTable from './WbsTable';
import './progress.css';

/** 일정 보기의 가중치 방식(묶음 2 서버의 칸. 공용 타입에는 아직 없다). */
const weightModeOf = (view: ScheduleView | null) => (view as (ScheduleView & { weight_mode?: string }) | null)?.weight_mode;

/** Plan 시작 = 액티비티 Plan 시작 가운데 가장 이른 날(서버 값 글자 비교만). */
function planStartOf(view: ScheduleView | null): string | null {
  let first: string | null = null;
  for (const a of view?.activities ?? []) if (a.plan_start && (first === null || a.plan_start < first)) first = a.plan_start;
  return first;
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

function Toolbar({ data, unit, onUnit, onImage }: { data: ProgressData | null; unit: Unit; onUnit: (u: Unit) => void; onImage: () => void }) {
  return (
    <div role="group" aria-label="공정률 도구" className="sch-toolbar pg-toolbar">
      <span className="sch-muted">Data Date</span>
      <span className="sch-date">{data ? dot(data.data_date) : '—'}</span>
      {data?.data_date_assumed && (
        <span className="pg-assumed" title="일정에 Data Date 가 없어 오늘 날짜로 계산했습니다">오늘로 가정</span>
      )}
      <span className="sch-sep" />
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
      <span className="sch-gap" />
      <Button onClick={onImage} disabled={!data}>
        그림 내보내기
      </Button>
    </div>
  );
}

function Body({ data, scheduleId, planStart }: { data: ProgressData; scheduleId: number; planStart: string | null }) {
  const added = data.added_after_plan;
  return (
    <>
      <KpiRow data={data} planStart={planStart} />
      {added.count > 0 && (
        <p className="pg-note" role="note">
          {`Plan 이 없는 액티비티 ${added.count}개는 계획 공정률·S-커브·일정 수행 지수에서 뺐습니다 · 그것들의 실적 ${pct(added.actual_pct)}%`}
        </p>
      )}
      <div className="pg-mid">
        <SCurve data={data} />
        <MilestoneTable data={data} />
      </div>
      <div className="pg-low">
        <WbsTable data={data} />
        <SpiTrend data={data} />
        <DelayTop data={data} scheduleId={scheduleId} />
        <Lookahead data={data} />
      </div>
    </>
  );
}

export default function ProgressTab() {
  const scheduleId = useScheduleStore().getState().scheduleId;
  const version = useSchedule((s) => s.view?.version);
  const weightMode = useSchedule((s) => weightModeOf(s.view));
  const name = useSchedule((s) => s.view?.name ?? '');
  const planStart = useSchedule((s) => planStartOf(s.view));
  const [unit, setUnit] = useState<Unit>('week');
  const { data, error } = useProgress(scheduleId, unit, version, weightMode);
  const onImage = () => data && void exportImage(data, name, `${name} v${data.version} 공정률`);
  return (
    <div className="pg-tab">
      <Toolbar data={data} unit={unit} onUnit={setUnit} onImage={onImage} />
      <div className="pg-scroll">
        {error ? (
          <p className="pg-empty" role="alert">
            {error}
          </p>
        ) : data ? (
          <Body data={data} scheduleId={scheduleId} planStart={planStart} />
        ) : (
          <p className="pg-empty">공정률을 읽는 중…</p>
        )}
      </div>
    </div>
  );
}
