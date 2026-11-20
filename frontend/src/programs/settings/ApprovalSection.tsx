import { useEffect, useId, useState } from 'react';
import { useSession } from '../../os/session';
import Button from '../../shared/ui/Button';
import { APPROVAL_MODES, approvalLabel, type ApprovalMode, type LlmError } from './model';
import { ErrorLine, toProblem } from './parts';
import { settingsApi } from './settingsApi';

/** 지금 승인 수준. 읽기 전에는 null. */
function useApprovalMode() {
  const [mode, setMode] = useState<ApprovalMode | null>(null);
  const [error, setError] = useState<LlmError | null>(null);
  useEffect(() => {
    let live = true;
    settingsApi
      .approval()
      .then((r) => live && setMode(r.mode))
      .catch((e) => live && setError(toProblem(e)));
    return () => {
      live = false;
    };
  }, []);
  return { mode, setMode, error };
}

/** 「내 정보」: 이름·등급·아이디. 사용자에게는 승인 수준을 읽기 전용으로 보인다. */
export function MeSection() {
  const session = useSession((s) => s.session);
  const isAdmin = session?.user.role === 'admin';
  return (
    <div className="st-pane">
      <h2>내 정보</h2>
      <dl className="st-facts st-facts-wide">
        <dt>이름</dt>
        <dd>{session?.user.name}</dd>
        <dt>등급</dt>
        <dd>{isAdmin ? '관리자' : '사용자'}</dd>
        <dt>아이디</dt>
        <dd>{session?.loginId}</dd>
        {!isAdmin && <ApprovalReadOnly />}
      </dl>
    </div>
  );
}

function ApprovalReadOnly() {
  const { mode, error } = useApprovalMode();
  return (
    <>
      <dt>승인 수준</dt>
      <dd>
        {mode && (
          <>
            <span>{approvalLabel(mode)}</span> <span className="st-muted">관리자가 정합니다.</span>
          </>
        )}
        {!mode && !error && '불러오는 중…'}
        <ErrorLine error={error} />
      </dd>
    </>
  );
}

function ApprovalChoices({ value, disabled, onPick }: { value: ApprovalMode | null; disabled: boolean; onPick(m: ApprovalMode): void }) {
  const name = useId();
  return (
    <fieldset className="st-radios" disabled={disabled}>
      <legend className="st-hidden">승인 수준</legend>
      {APPROVAL_MODES.map((m) => (
        <label key={m.value} className="st-radio">
          <input type="radio" name={name} value={m.value} checked={value === m.value} onChange={() => onPick(m.value)} />
          <span className="st-radio-text">
            <b>{m.label}</b>
            <span className="st-muted">{m.desc}</span>
          </span>
        </label>
      ))}
    </fieldset>
  );
}

/** 「승인 수준」(관리자): 모두 승인 · 중요한 것만 · 자동. */
export default function ApprovalSection() {
  const { mode: saved, setMode: setSaved, error: loadError } = useApprovalMode();
  const [choice, setChoice] = useState<ApprovalMode | null>(null);
  const [state, setState] = useState<{ busy?: boolean; done?: boolean; error?: LlmError }>({});
  const current = choice ?? saved;
  async function save() {
    if (!current) return;
    setState({ busy: true });
    try {
      setSaved((await settingsApi.saveApproval(current)).mode);
      setChoice(null);
      setState({ done: true });
    } catch (e) {
      setState({ error: toProblem(e) });
    }
  }
  return (
    <div className="st-pane">
      <h2>승인 수준</h2>
      <p className="st-muted">에이전트가 일정을 바꿀 때 언제 사람의 승인을 받을지 정합니다.</p>
      <ErrorLine error={loadError} />
      <ApprovalChoices
        value={current}
        disabled={!saved || state.busy === true}
        onPick={(m) => {
          setChoice(m);
          setState({});
        }}
      />
      <ErrorLine error={state.error} />
      {state.done && <p className="st-ok">저장했습니다.</p>}
      <div className="st-actions">
        <Button variant="primary" onClick={save} disabled={state.busy || !current || current === saved}>
          저장
        </Button>
      </div>
    </div>
  );
}
