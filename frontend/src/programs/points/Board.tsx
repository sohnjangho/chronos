// 보드 조각: 위 띠(일정 · 버전 · 기준 · 개수 · 찾기), 주 칸, 포인트 카드. 값은 서버 그대로(날짜는 자르기만).
import type { ReactNode } from 'react';
import { scheduleText, type ScheduleItem } from '../../os/ScheduleSelector';
import Badge from '../../shared/ui/Badge';
import { changedCount, KindIcon, md, span, stamp, weekName } from './format';
import type { History, Point, PointsView } from './pointsApi';

export function PointCard({ p, change, kinds, dataDate, owners, picked, onPick }: {
  p: Point;
  owners: string[];
  change: string | null;
  kinds: string[];
  dataDate: string;
  picked: boolean;
  onPick(): void;
}) {
  return (
    <button type="button" className={`pt-card ${p.critical ? 'is-crit' : 'is-near'}${picked ? ' is-pick' : ''}`} aria-pressed={picked} onClick={onPick}>
      <span className="pt-card-h">
        <b>{p.name}</b>
        {change && <Badge tone="info">{change}</Badge>}
      </span>
      <span className="pt-card-f">
        <span className={`pt-tf ${p.critical ? 'is-crit' : 'is-near'}`}>{`여유 ${p.tf}일`}</span>
        <span>{`${span(p.es, p.ef)}${p.es < dataDate ? ' · 진행 중' : ''}`}</span>
        {owners.length > 0 && <span>{owners.join(', ')}</span>}
        {kinds.length > 0 && (
          <span className="pt-icons">
            {kinds.map((k) => (
              <KindIcon key={k} kind={k} label />
            ))}
          </span>
        )}
      </span>
    </button>
  );
}

export interface TopProps {
  sid: number;
  schedules: ScheduleItem[];
  onSchedule(id: number): void;
  view: PointsView;
  hist: History;
  query: string;
  setQuery(q: string): void;
  shown: number;
  isAdmin: boolean;
  phone: boolean;
}

export function Top({ sid, schedules, onSchedule, view, hist, query, setQuery, shown, isAdmin, phone }: TopProps) {
  const { tf_days: k, window_weeks: w } = view.basis;
  const weeks = hist.window.weeks;
  const crit = view.points.filter((p) => p.critical).length;
  const at = stamp(hist.versions.find((e) => e.version === view.version)?.saved_at ?? null);
  return (
    <div className={phone ? 'pt-ph-sum' : 'pt-top'}>
      <div className="pt-top-l">
        {schedules.length > 1 && !phone ? ( /* 폰은 위 머리줄의 일정 고르기를 쓴다 */
          <select className="pt-input pt-pick" aria-label="일정" value={sid} onChange={(e) => onSchedule(Number(e.target.value))}>
            {schedules.map((s) => (
              <option key={s.id} value={s.id}>
                {scheduleText(s)}
              </option>
            ))}
          </select>
        ) : null}
        <span className="pt-chip">{`버전 ${view.version}${at ? ` · ${at}` : ''}`}</span>
        <span className="pt-basis">
          기준 <b>{`여유 ${k}일 이하`}</b> · <b>{`앞으로 ${w}주`}</b>
          {weeks.length > 0 && ` (${md(weeks[0].start)} ~ ${md(weeks[weeks.length - 1].end)})`}
        </span>
        {isAdmin && <span className="pt-muted">관리자가 개발 콘솔에서 바꿉니다</span>}
      </div>
      <div className="pt-counts">
        <span className="pt-count is-crit">
          크리티컬 <b>{crit}</b>
        </span>
        <span className="pt-count is-near">
          크리티컬 직전 <b>{view.points.length - crit}</b>
        </span>
        <span className="pt-count is-changed">
          이번에 바뀜 <b>{changedCount(view.diff)}</b>
        </span>
      </div>
      <div className="pt-find">
        <input type="search" className="pt-input" aria-label="포인트 찾기" placeholder="이름·작업 ID로 찾기" value={query} onChange={(e) => setQuery(e.target.value)} />
        <span className="pt-muted">{shown === view.points.length ? `${shown}곳` : `${shown} / ${view.points.length}곳`}</span>
      </div>
    </div>
  );
}

export function Column({ i, week, points, children }: { i: number; week: { start: string; end: string }; points: Point[]; children: ReactNode }) {
  return (
    <section className="pt-col" aria-label={weekName(i)}>
      <div className="pt-col-h">
        <b>{weekName(i)}</b>
        <span className="pt-muted">{`${md(week.start)} ~ ${md(week.end)} · ${points.length}곳`}</span>
      </div>
      <div className="pt-col-b">
        {points.length === 0 && <p className="pt-muted">이 주에 시작하는 포인트가 없습니다.</p>}
        {children}
      </div>
    </section>
  );
}
