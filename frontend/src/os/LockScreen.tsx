import { useState, type FormEvent } from 'react';
import Button from '../shared/ui/Button';
import Field from '../shared/ui/Field';
import { useSignIn } from './auth';
import { useSession } from './session';

/** 바탕화면 위를 덮는 잠금 화면. 지금 사용자의 비밀번호로 다시 로그인하면 풀린다(창은 그대로). */
export default function LockScreen() {
  const session = useSession((s) => s.session);
  const [password, setPassword] = useState('');
  const { busy, error, submit } = useSignIn();
  if (!session) return null;

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (session) void submit(session.loginId, password);
  }

  return (
    <div className="os-lock" role="dialog" aria-modal="true" aria-label="잠금 화면">
      <form className="os-card" onSubmit={onSubmit}>
        <h1 className="os-card-title">잠겨 있습니다</h1>
        <p className="os-card-note">{session.user.name} 님의 비밀번호를 넣으면 하던 화면으로 돌아갑니다.</p>
        <Field label="비밀번호">
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
            autoFocus
          />
        </Field>
        {error && (
          <p className="os-card-error" role="alert">
            {error}
          </p>
        )}
        <Button type="submit" variant="primary" className="os-card-submit" disabled={busy}>
          잠금 풀기
        </Button>
      </form>
    </div>
  );
}
