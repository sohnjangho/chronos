import { useState } from 'react';
import { ApiError, publicApi } from '../shared/api';
import { useSession, type Session, type User } from './session';

/** POST /api/auth/login. 실패하면 서버 글이 든 ApiError. */
export async function signIn(loginId: string, password: string): Promise<Session> {
  const res = await publicApi<{ token: string; user: User }>('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ login_id: loginId, password }),
  });
  return { token: res.token, user: res.user, loginId };
}

/** 로그인·잠금 풀기 양식이 함께 쓰는 제출 상태. 성공하면 세션을 바꾼다(잠금도 풀린다). */
export function useSignIn() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function submit(loginId: string, password: string) {
    setBusy(true);
    setError('');
    try {
      useSession.getState().signIn(await signIn(loginId, password));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '로그인할 수 없습니다.');
      setBusy(false);
    }
  }

  return { busy, error, submit };
}
