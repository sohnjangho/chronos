// 왼쪽 실행 기록(새것부터). 일반 사용자는 자기 대화의 실행만, 관리자는 모두 받는다.
import { useSession } from '../../os/session';
import Badge from '../../shared/ui/Badge';
import { seconds, stepStatus, when } from './labels';
import type { RunItem } from './wfApi';

interface Props {
  runs: RunItem[] | null;
  selected: number | null;
  onSelect(id: number): void;
}

const TONE: Record<string, 'info' | 'warning' | 'success' | 'danger' | 'neutral'> = {
  running: 'info',
  waiting: 'warning',
  done: 'success',
  failed: 'danger',
  stopped: 'neutral',
};

function sub(r: RunItem): string {
  const took = r.ended_at ? seconds(Date.parse(r.ended_at) - Date.parse(r.started_at)) : '';
  return [`${r.step_count}단계`, took, when(r.started_at)].filter(Boolean).join(' · ');
}

export default function RunList({ runs, selected, onSelect }: Props) {
  const admin = useSession((s) => s.session?.user.role === 'admin');
  return (
    <aside className="wf-side">
      <h2 className="wf-side-h">실행 기록</h2>
      {runs === null && <p className="wf-muted wf-pad">불러오는 중…</p>}
      {runs?.length === 0 && <p className="wf-muted wf-pad">아직 실행 기록이 없습니다. 에이전트가 도구를 쓰면 여기에 남습니다.</p>}
      {runs && runs.length > 0 && (
        <ul className="wf-runs" aria-label="실행 기록">
          {runs.map((r) => (
            <li key={r.id}>
              <button type="button" className="wf-run" aria-current={r.id === selected ? 'true' : undefined} onClick={() => onSelect(r.id)}>
                <b className="wf-run-t" title={r.title}>
                  {r.title || '제목 없는 실행'}
                </b>
                <small className="wf-run-s">
                  <Badge tone={TONE[r.status] ?? 'neutral'}>{stepStatus(r.status)}</Badge>
                  <span className="wf-ellipsis">{sub(r)}</span>
                </small>
              </button>
            </li>
          ))}
        </ul>
      )}
      <p className="wf-side-foot">{admin ? '관리자는 모든 사람의 실행 기록을 봅니다.' : '내 대화의 실행 기록만 보입니다.'} 실행 기록은 지우지 않고 모두 남습니다.</p>
    </aside>
  );
}
