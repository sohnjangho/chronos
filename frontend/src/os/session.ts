import { create } from 'zustand';
import { loadJson, saveJson } from './storage';

export type Role = 'admin' | 'user' | 'field';

export interface User {
  id: number;
  name: string;
  role: Role;
}

/** 로그인 결과. loginId 는 잠금을 풀 때 다시 로그인하려고 둔다(비밀번호는 두지 않는다). */
export interface Session {
  token: string;
  user: User;
  loginId: string;
}

interface SessionState {
  session: Session | null;
  locked: boolean;
  signIn(session: Session): void;
  lock(): void;
  logout(): void;
}

const KEY = 'chronos.session';

type UserChange = (next: Session | null) => void;
const userListeners = new Set<UserChange>();

/**
 * 로그인한 사람이 바뀔 때(로그아웃·다른 사람 로그인) 부를 함수를 단다. 세션을 바꾸기 **전에**, 같은 호출 안에서
 * 부르므로 다음 사람의 첫 화면에 앞 사람의 상태가 그려지지 않는다. 잠금을 푸는 같은 사람은 부르지 않는다.
 */
export function onUserChange(fn: UserChange): () => void {
  userListeners.add(fn);
  return () => void userListeners.delete(fn);
}

function notify(prev: Session | null, next: Session | null) {
  if ((prev?.user.id ?? null) !== (next?.user.id ?? null)) userListeners.forEach((fn) => fn(next));
}

function restore(): Pick<SessionState, 'session' | 'locked'> {
  const raw = loadJson(KEY) as (Session & { locked?: unknown }) | null;
  const valid =
    raw && typeof raw.token === 'string' && typeof raw.loginId === 'string' && typeof raw.user === 'object' && raw.user;
  if (!valid) {
    return { session: null, locked: false };
  }
  const { token, user, loginId } = raw;
  return { session: { token, user, loginId }, locked: raw.locked === true };
}

export const useSession = create<SessionState>((set, get) => ({
  ...restore(),
  signIn(session) {
    notify(get().session, session);
    saveJson(KEY, { ...session, locked: false });
    set({ session, locked: false });
  },
  lock() {
    const { session } = get();
    if (!session) return;
    saveJson(KEY, { ...session, locked: true });
    set({ locked: true });
  },
  logout() {
    notify(get().session, null);
    saveJson(KEY, null);
    set({ session: null, locked: false });
  },
}));

export const getToken = (): string | null => useSession.getState().session?.token ?? null;

export const logout = (): void => useSession.getState().logout();
