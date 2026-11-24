// 「승인 수준」 아래 한 칸(PM 11-24): AI 가 못 읽은 현장 사진을 누가 사람 판독할지. 기본 관리자만, 넓히면 사용자까지.
// 현장 관리자는 어느 값이든 못 한다(서버도 403). 바꾸기는 관리자만(서버 PUT 도 관리자만).
import { useEffect, useId, useState } from 'react';
import Button from '../../shared/ui/Button';
import type { LlmError } from './model';
import { ErrorLine, toProblem } from './parts';
import { settingsApi } from './settingsApi';

type Role = 'admin' | 'user';
const CHOICES: { value: Role; label: string; desc: string }[] = [
  { value: 'admin', label: '관리자만', desc: '관리자만 사진을 보고 진도를 넣거나 다시 찍어 달라고 요청합니다.' },
  { value: 'user', label: '관리자와 사용자', desc: '사용자 등급도 사람 판독을 합니다. 현장 관리자는 하지 않습니다.' },
];

export default function HumanReadRoleCard() {
  const name = useId();
  const [saved, setSaved] = useState<Role | null>(null);
  const [choice, setChoice] = useState<Role | null>(null);
  const [state, setState] = useState<{ busy?: boolean; done?: boolean; error?: LlmError | null }>({});
  useEffect(() => {
    let live = true;
    settingsApi
      .humanRead()
      .then((r) => live && setSaved(r.role))
      .catch((e) => live && setState({ error: toProblem(e) }));
    return () => {
      live = false;
    };
  }, []);
  const current = choice ?? saved;
  async function save() {
    if (!current) return;
    setState({ busy: true });
    try {
      setSaved((await settingsApi.saveHumanRead(current)).role);
      setChoice(null);
      setState({ done: true });
    } catch (e) {
      setState({ error: toProblem(e) });
    }
  }
  return (
    <section className="st-card" aria-label="사진 사람 판독">
      <div className="st-card-head">
        <b className="st-card-name">사진 사람 판독</b>
      </div>
      <p className="st-muted">AI 가 판독하지 못한 현장 사진(어두움·가림·공정과 관계없음 등)은 사람 판독 대기가 됩니다. 누가 판독할지 고르세요.</p>
      <fieldset className="st-radios" disabled={!saved || state.busy === true}>
        <legend className="st-hidden">사진 사람 판독</legend>
        {CHOICES.map((c) => (
          <label key={c.value} className="st-radio">
            <input type="radio" name={name} value={c.value} checked={current === c.value} onChange={() => { setChoice(c.value); setState({}); }} />
            <span className="st-radio-text">
              <b>{c.label}</b>
              <span className="st-muted">{c.desc}</span>
            </span>
          </label>
        ))}
      </fieldset>
      <ErrorLine error={state.error ?? null} />
      <div className="st-actions">
        {state.done && <p className="st-ok">저장했습니다.</p>}
        <span className="st-gap" />
        <Button variant="primary" onClick={save} disabled={state.busy || !current || current === saved}>
          저장
        </Button>
      </div>
    </section>
  );
}
