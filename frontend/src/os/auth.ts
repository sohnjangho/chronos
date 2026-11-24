import { useState } from 'react';
import { ApiError, publicApi } from '../shared/api';
import { deviceInfo } from './presence';
import { getToken, useSession, type Session, type User } from './session';

export type SignupRole = 'user' | 'field';

export interface SignupPayload {
  login_id: string;
  password: string;
  name: string;
  role: SignupRole;
  email: string;
  phone?: string;
  organization?: string;
  department?: string;
  note?: string;
}

export interface SignupResponse {
  id: number;
  login_id: string;
  name: string;
  role: SignupRole;
  status: string;
  message: string;
}

/** POST /api/auth/login. 이 기기 열쇠·모양을 함께 보내 서버의 기기 세션에 묶는다. 실패하면 서버 글이 든 ApiError. */
export async function signIn(loginId: string, password: string): Promise<Session> {
  const res = await publicApi<{ token: string; user: User }>('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ login_id: loginId, password, ...deviceInfo() }),
  });
  return { token: res.token, user: res.user, loginId };
}

/**
 * 본인 로그아웃(메뉴·잠금 화면). 서버에 이 기기 줄을 닫으라고 알리고(기다리지 않음, 실패해도 상관없음) 곧바로 로그아웃한다.
 * 같은 브라우저의 다른 탭도 같은 기기 줄이라 다음 요청 때 함께 로그인 화면으로 간다.
 */
export function signOut(): void {
  const token = getToken();
  if (token) {
    try {
      void fetch('/api/auth/logout', { method: 'POST', headers: { Authorization: `Bearer ${token}` }, keepalive: true }).catch(() => {});
    } catch {
      // fetch 를 부를 수 없어도 로그아웃은 한다
    }
  }
  useSession.getState().logout();
}

/** POST /api/auth/signup. 관리자 승인 대기 상태로 가입 신청을 등록한다. */
export async function signUp(payload: SignupPayload): Promise<SignupResponse> {
  return publicApi<SignupResponse>('/api/auth/signup', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
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
