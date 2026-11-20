import { useState, type FormEvent } from 'react';
import Button from '../shared/ui/Button';
import Field from '../shared/ui/Field';
import { useSignIn } from './auth';

/** 시안 「로그인」. 성공하면 세션이 생겨 바탕화면으로 바뀐다. */
export default function Login() {
  const [loginId, setLoginId] = useState('');
  const [password, setPassword] = useState('');
  const { busy, error, submit } = useSignIn();

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void submit(loginId, password);
  }

  return (
    <div className="os-login">
      <div className="os-login-brand">
        <div className="os-login-name">ChronOS</div>
        <div className="os-login-tagline">일정을 만들고, 지키고, 고치는 에이전트 OS</div>
      </div>
      <form className="os-card" onSubmit={onSubmit}>
        <h1 className="os-card-title">로그인</h1>
        <Field label="아이디">
          <input value={loginId} onChange={(e) => setLoginId(e.target.value)} autoComplete="username" required autoFocus />
        </Field>
        <Field label="비밀번호">
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </Field>
        {error && (
          <p className="os-card-error" role="alert">
            {error}
          </p>
        )}
        <Button type="submit" variant="primary" className="os-card-submit" disabled={busy}>
          들어가기
        </Button>
        <p className="os-card-note">계정은 관리자가 만듭니다. 등급은 관리자와 사용자 두 가지입니다.</p>
      </form>
      <div className="os-login-foot">2026 .EXE-THON 출품작 · Liner API로 동작합니다</div>
    </div>
  );
}
