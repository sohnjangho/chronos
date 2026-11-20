// 오른쪽: 고른 일정의 요약 · [스케줄에서 열기] · (관리자) [일정 지우기] · 버전 목록(번호·처음 계획·메모·누가·[되돌리기]).
import Badge from '../../shared/ui/Badge';
import Button from '../../shared/ui/Button';
import { dot, domainLabel, levelLabel, stamp, type ScheduleSummary, type TreeSchedule, type Version } from './exApi';

interface Props {
  schedule: TreeSchedule | null;
  view: { data: ScheduleSummary | null; error: string | null } | null;
  versions: Version[] | null;
  /** 버전을 읽지 못했을 때 서버 글. [다시 읽기]는 onRetry. */
  versionsError: string | null;
  onRetry(): void;
  admin: boolean;
  onOpen(): void;
  onDelete(): void;
  onRestore(n: number): void;
}

function finishText(s: TreeSchedule, view: ScheduleSummary | null): string {
  if (s.finish === null) return '계산 안 됨';
  const plan = view?.plan_finish;
  return plan && plan !== s.finish ? `${dot(s.finish)} (Plan ${dot(plan)})` : dot(s.finish);
}

/** 「김하늘 · 직접 수정」. 이름이 종류 글과 같으면(「에이전트」) 한 번만. */
function author(v: Version): string {
  const kind = v.by_kind === 'agent' ? '에이전트' : '직접 수정';
  return v.by_name === kind ? kind : `${v.by_name} · ${kind}`;
}

/** 번호 · 「지금」 · 「처음 계획」(is_plan 버전. 화면의 Plan 은 지금 일정을 실적 없이 계산한 것이라 이 버전과 다르다). */
function badgeText(v: Version, current: number): string {
  return [String(v.n), v.n === current ? '지금' : '', v.is_plan ? '처음 계획' : ''].filter(Boolean).join(' ');
}

function Versions({ versions, current, onRestore }: { versions: Version[]; current: number; onRestore(n: number): void }) {
  return (
    <ul className="ex-vers" aria-label="버전">
      {versions.map((v) => (
        <li key={v.n} className="ex-ver">
          <Badge tone={v.n === current ? 'info' : 'neutral'}>{badgeText(v, current)}</Badge>
          <span className="ex-ver-b">
            <span className="ex-wrap">{v.note || '메모 없음'}</span>
            <small className="ex-wrap">{`${author(v)} · ${stamp(v.created_at)}`}</small>
          </span>
          {v.n !== current && <Button onClick={() => onRestore(v.n)}>되돌리기</Button>}
        </li>
      ))}
    </ul>
  );
}

export default function VersionPanel({ schedule, view, versions, versionsError, onRetry, admin, onOpen, onDelete, onRestore }: Props) {
  if (schedule === null) {
    return (
      <section className="ex-panel" aria-label="일정 정보">
        <p className="ex-muted">일정을 고르면 요약과 버전이 보입니다.</p>
      </section>
    );
  }
  const data = view?.data ?? null;
  return (
    <section className="ex-panel" aria-label="일정 정보">
      <h3 className="ex-panel-h ex-wrap">{schedule.name}</h3>
      <dl className="ex-kv">
        <div>
          <dt>분야</dt>
          <dd>{`${domainLabel(schedule.domain)} · ${levelLabel(schedule.level)}`}</dd>
        </div>
        <div>
          <dt>지금 버전</dt>
          <dd>{schedule.version}</dd>
        </div>
        <div>
          <dt>준공</dt>
          <dd>{finishText(schedule, data)}</dd>
        </div>
        <div>
          <dt>액티비티</dt>
          <dd className="ex-wrap">{view?.error ?? (data ? `${data.activities.length}개 · 관계 ${data.relations.length}개` : '불러오는 중…')}</dd>
        </div>
        <div>
          <dt>고친 때</dt>
          <dd>{stamp(schedule.updated_at)}</dd>
        </div>
      </dl>
      <div className="ex-actions">
        <Button variant="primary" onClick={onOpen}>
          스케줄에서 열기
        </Button>
        {admin && (
          <Button variant="danger" onClick={onDelete}>
            일정 지우기
          </Button>
        )}
      </div>
      <h4 className="ex-ver-h">버전</h4>
      {versionsError !== null && (
        <p className="ex-error" role="alert">
          <span className="ex-wrap">{`버전을 읽지 못했습니다: ${versionsError}`}</span>
          <Button onClick={onRetry}>다시 읽기</Button>
        </p>
      )}
      {versionsError === null && versions === null && <p className="ex-muted">불러오는 중…</p>}
      {versions !== null && <Versions versions={versions} current={schedule.version} onRestore={onRestore} />}
    </section>
  );
}
