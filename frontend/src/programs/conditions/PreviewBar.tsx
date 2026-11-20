import { useWindows } from '../../os/windowStore';
import Badge from '../../shared/ui/Badge';
import Button from '../../shared/ui/Button';
import type { ConditionsModel } from './condStore';
import { allConds, condLabel, shortDate } from './labels';

/** 미리 보기 줄: 「미리 보기 중 · 준공 11.24 → 11.12 · 위반 n」. */
function previewLine(model: ConditionsModel): string | null {
  const p = model.preview;
  if (!p) return null;
  return `준공 ${shortDate(p.before.finish, p.after.finish)} → ${shortDate(p.after.finish, p.before.finish)} · 위반 ${p.after.violated}`;
}

/** 위반 안내(계산만으로는 못 맞춤). 줄마다 「조건 이름: 까닭」. */
function Violations({ model }: { model: ConditionsModel }) {
  const p = model.preview;
  if (!p || p.feasible || !model.shown) return null;
  const conds = allConds(model.shown);
  const name = (id: string) => {
    const c = conds.find((x) => x.id === id);
    return c ? condLabel(c, model.shown!.resources) : id;
  };
  return (
    <div className="cd-alert" role="alert">
      <p className="cd-alert-head">이 조건으로는 계산만으로 맞출 수 없습니다. 에이전트에게 일정을 고치게 하거나 값을 되돌리세요.</p>
      <ul>
        {p.violations.map((v, n) => (
          <li key={`${v.condition_id}-${n}`}>{`${name(v.condition_id)}: ${v.message}`}</li>
        ))}
      </ul>
    </div>
  );
}

function Actions({ model }: { model: ConditionsModel }) {
  const editing = Object.keys(model.edits).length > 0;
  const p = model.preview;
  const savedViolations = (model.view?.summary.violated ?? 0) > 0;
  // 바꿔 보는 중이면 미리 보기가 나온 뒤에만(서버가 그 변경을 확인한 뒤). 아니면 저장된 일정에 위반이 있을 때.
  const showAgent = editing ? p !== null : savedViolations;
  const agentFirst = editing ? p !== null && !p.feasible : savedViolations;
  return (
    <div className="cd-actions">
      {editing && <Button onClick={model.revert}>되돌리기</Button>}
      {showAgent && (
        <Button variant={agentFirst ? 'primary' : 'default'} disabled={model.busy || model.pending} onClick={() => void model.ask()}>
          에이전트에게 맞추게 하기
        </Button>
      )}
      {p?.feasible && (
        <Button variant="primary" disabled={model.busy || model.pending} onClick={() => void model.commit()}>
          확정
        </Button>
      )}
    </div>
  );
}

function NoticeLine({ model }: { model: ConditionsModel }) {
  const n = model.notice;
  if (!n) return null;
  return (
    <div className={`cd-notice is-${n.tone}`} role={n.tone === 'error' ? 'alert' : 'status'}>
      <span>{n.text}</span>
      {n.approvalId !== undefined && (
        <Button onClick={() => useWindows.getState().open('approvals', { id: String(n.approvalId) })}>승인함 열기</Button>
      )}
    </div>
  );
}

/** 위쪽 막대: 하네스 안내 · 미리 보기 상태 · 되돌리기·에이전트·확정, 그 아래 위반 안내와 알림. */
export default function PreviewBar({ model }: { model: ConditionsModel }) {
  const line = previewLine(model);
  const editing = Object.keys(model.edits).length > 0;
  return (
    <div className="cd-top">
      <div className="cd-bar">
        <div className="cd-bar-title">
          <b>하네스 네 겹</b>
          {!editing && <span className="cd-muted">뒤 겹이 앞 겹과 부딪히면 뒤 겹을 따릅니다 (기본 규칙은 예외)</span>}
          {editing && line && <Badge tone="info">미리 보기 중</Badge>}
          {editing && line && <span className="cd-preview-line">{line}</span>}
          {editing && !line && model.pending && <span className="cd-muted" role="status">미리 계산하는 중…</span>}
          {editing && model.problem && (
            <span className="cd-problem" role="alert">
              {model.problem}
            </span>
          )}
        </div>
        <Actions model={model} />
      </div>
      <Violations model={model} />
      <NoticeLine model={model} />
    </div>
  );
}
