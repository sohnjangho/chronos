// 접속 신호(설정 → 계정의 「접속 중」·기기 목록): 로그인한 동안 POST /api/me/presence {device_key, kind}.
// 불러올 때 한 번, 창이 보이는 동안 60초마다, 가려졌다 다시 보이면 한 번(지난번에서 20초 안이면 건너뜀). 한 번에 하나만.
// 잠근 화면은 보내지 않는다. 관리자가 이 기기를 로그아웃하면 서버가 401 을 주고 api() 가 로그아웃한다 → 로그인 화면
// (세션이 없으면 보내지 않으니 되풀이 없음). 서버는 토큰을 주지 않는다(204).
import { useEffect } from 'react';
import { api } from '../shared/api';
import { useSession } from './session';
import { loadJson, saveJson } from './storage';
import { detectClientDevice } from './useIsMobile';

export const PRESENCE_MS = 60_000;
const MIN_GAP_MS = 20_000; // 창 보이기·가리기가 오락가락할 때
const KEY = 'chronos.deviceKey';
const VALID = /^[A-Za-z0-9_-]{16,64}$/;

function randomKey(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

/** 이 브라우저의 기기 열쇠(임의 값). 처음 부를 때 만들어 브라우저 저장소에 둔다(사람이 바뀌어도 같은 값). */
export function deviceKey(): string {
  const stored = loadJson(KEY);
  if (typeof stored === 'string' && VALID.test(stored)) return stored;
  const key = randomKey();
  saveJson(KEY, key);
  return key;
}

/** 로그인·접속 신호가 함께 보내는 이 기기 모양(사람이 고른 화면 형태가 아닌 실제 기기). */
export const deviceInfo = () => ({ device_key: deviceKey(), kind: detectClientDevice() });

export function usePresence(): void {
  const userId = useSession((s) => s.session?.user.id ?? null);
  const locked = useSession((s) => s.locked);
  useEffect(() => {
    if (userId === null || locked) return;
    let busy = false;
    let last = -Infinity;
    const beat = async () => {
      if (busy || document.visibilityState === 'hidden' || Date.now() - last < MIN_GAP_MS) return;
      busy = true;
      last = Date.now();
      try {
        await api<void>('/api/me/presence', { method: 'POST', body: JSON.stringify(deviceInfo()) });
      } catch {
        // 연결 실패 등은 다음 차례에 다시. 401 이면 api() 가 이미 로그아웃했다.
      } finally {
        busy = false;
      }
    };
    void beat();
    const timer = setInterval(() => void beat(), PRESENCE_MS);
    const onVisible = () => {
      if (document.visibilityState === 'visible') void beat();
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      clearInterval(timer);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [userId, locked]);
}
