import { create } from 'zustand';
import { loadJson, saveJson } from './storage';

export type Role = 'admin' | 'user';

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
    saveJson(KEY, null);
    set({ session: null, locked: false });
  },
}));

export const getToken = (): string | null => useSession.getState().session?.token ?? null;

export const logout = (): void => useSession.getState().logout();
