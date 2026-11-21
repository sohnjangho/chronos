import { useEffect, useId, useState } from 'react';
import { useSession } from '../../os/session';
import { useWindows } from '../../os/windowStore';
import Button from '../../shared/ui/Button';
import Field from '../../shared/ui/Field';
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

/** 「내 정보」: 프로필 요약 카드 + 본인 이름·비밀번호 변경 카드. */
export function MeSection() {
  const session = useSession((s) => s.session);
  const isAdmin = session?.user.role === 'admin';
  const [name, setName] = useState(session?.user.name ?? '');
  const [seenName, setSeenName] = useState(session?.user.name ?? '');
  if ((session?.user.name ?? '') !== seenName) {
    setSeenName(session?.user.name ?? '');
    setName(session?.user.name ?? '');
  }
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<LlmError | null>(null);

  const trimmed = name.trim();
  const changed = (session && trimmed !== '' && trimmed !== session.user.name) || password !== '';

  async function saveProfile() {
    if (!session || !changed) return;
    setBusy(true);
    setDone(false);
    setError(null);
    try {
      const updated = await settingsApi.updateMe({
        ...(trimmed !== session.user.name ? { name: trimmed } : {}),
        ...(password !== '' ? { password } : {}),
      });
      useSession.getState().signIn({ ...session, user: updated });
      setPassword('');
      setDone(true);
    } catch (e) {
      setError(toProblem(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="st-pane">
      <div className="st-section-head">
        <h2>내 정보</h2>
        <p className="st-muted">로그인 계정 정보와 표시 이름, 비밀번호를 관리합니다.</p>
      </div>

      <section className="st-card" aria-label="내 계정 요약">
        <b className="st-card-name">계정 요약</b>
        <dl className="st-facts st-facts-wide">
          <dt>이름</dt>
          <dd>{session?.user.name}</dd>
          <dt>등급</dt>
          <dd>{isAdmin ? '관리자' : '사용자'}</dd>
          <dt>아이디</dt>
          <dd>{session?.loginId}</dd>
          {!isAdmin && <ApprovalReadOnly />}
        </dl>
      </section>

      <section className="st-card" aria-label="내 이름 · 비밀번호 변경">
        <b className="st-card-name">프로필 · 비밀번호 변경</b>
        <div className="st-grid2">
          <Field label="표시 이름">
            <input value={name} disabled={busy} onChange={(e) => { setName(e.target.value); setDone(false); }} />
          </Field>
          <Field label="새 비밀번호" hint="변경할 때만 입력하세요.">
            <input
              type="password"
              autoComplete="new-password"
              value={password}
              disabled={busy}
              onChange={(e) => { setPassword(e.target.value); setDone(false); }}
            />
          </Field>
        </div>
        <ErrorLine error={error} />
        <div className="st-actions">
          {done && <span className="st-ok">내 정보를 저장했습니다.</span>}
          <span className="st-gap" />
          <Button variant="primary" disabled={busy || !changed} onClick={() => void saveProfile()}>
            {busy ? '저장 중…' : '변경 저장'}
          </Button>
        </div>
      </section>
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

/** 「승인 수준」(관리자): 모두 승인 · 중요한 것만 · 자동 + 개발 콘솔 에이전트 설정 바로가기. */
export default function ApprovalSection() {
  const { mode: saved, setMode: setSaved, error: loadError } = useApprovalMode();
  const [choice, setChoice] = useState<ApprovalMode | null>(null);
  const [state, setState] = useState<{ busy?: boolean; done?: boolean; error?: LlmError }>({});
  const open = useWindows((s) => s.open);
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
      <div className="st-section-head">
        <h2>승인 수준</h2>
        <p className="st-muted">에이전트가 일정을 바꿀 때 언제 사람의 승인을 받을지 정합니다.</p>
      </div>

      <section className="st-card">
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
        <div className="st-actions">
          {state.done && <p className="st-ok">저장했습니다.</p>}
          <span className="st-gap" />
          <Button variant="primary" onClick={save} disabled={state.busy || !current || current === saved}>
            저장
          </Button>
        </div>
      </section>

      <section className="st-card st-card-subtle" aria-label="개발 콘솔 에이전트 설정">
        <div className="st-card-head">
          <b className="st-card-name">에이전트 · 하네스 상세 실행 설정</b>
          <span className="st-gap" />
          <Button onClick={() => void open('devconsole', { tab: 'harness' })}>
            개발 콘솔에서 에이전트 설정 열기
          </Button>
        </div>
        <p className="st-muted">
          ReAct 루프 단계 한도, 하네스 조건 점검 재시도 횟수, 도구 출력 길이 상한, 컨텍스트 유지 메시지 수, 스킬 매칭 및 자가 점검 설정은 개발 콘솔에서 직접 변경할 수 있습니다.
        </p>
      </section>
    </div>
  );
}
