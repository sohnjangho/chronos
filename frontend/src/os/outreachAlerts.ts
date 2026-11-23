// 긴급 보고 토스트(Task 85): 20초마다 GET /api/outreach/alerts?since=… 를 묻고, 처음 보는 긴급 보고마다 토스트 하나.
// 현장 관리자(연락처를 열 수 없음)·로그인 안 함·잠김이면 묻지 않는다. 토스트 글에는 번호가 없다 — 보고 글은 싣지 않고
// 프로젝트·사람 이름에 숫자 세 자리 넘는 묶음이 있으면 「[번호]」로 바꾼다. since 는 서버가 준 now(서버 시계)를 그대로 쓴다.
import { useEffect } from 'react';
import { api } from '../shared/api';
import { onUserChange, useSession } from './session';
import { pushToast } from './ToastStack';

export const ALERT_POLL_MS = 20_000;

export interface OutreachAlert {
  id: number;
  schedule_id: number | null;
  schedule_name: string | null;
  medium: string;
  contact_name: string | null;
  created_at: string;
}

interface AlertsReply {
  now: string;
  items: OutreachAlert[];
}

let since: string | null = null;
let busy = false;
const seen = new Set<number>();

/** 시험·사용자 바뀜: 처음부터(커서·본 보고를 잊는다). */
export function resetOutreachAlerts(): void {
  since = null;
  busy = false;
  seen.clear();
}
onUserChange(() => resetOutreachAlerts());

/** 숫자 셋 넘는 묶음(사이의 빈칸·-·.·괄호 포함)을 「[번호]」로. */
const noNumbers = (s: string) => s.replace(/\d[\d\s().-]*\d/g, (m) => (m.replace(/\D/g, '').length >= 3 ? '[번호]' : m));

/** 「긴급 보고 — 5층 사무동 신축 · 박현장 · 전화로 받은 보고」 */
export function alertText(a: OutreachAlert): string {
  const where = a.schedule_name ?? '일정 없음';
  const who = a.contact_name ?? '모르는 번호';
  return noNumbers(`긴급 보고 — ${where} · ${who} · ${a.medium === 'call' ? '전화로 받은 보고' : '문자로 받은 보고'}`);
}

const mayAsk = () => {
  const { session, locked } = useSession.getState();
  return session !== null && !locked && session.user.role !== 'field';
};

/** 한 번 묻는다. 실패하면 커서를 두고 다음에 다시. 겹쳐 부르면 하나만. */
export async function pollOutreachAlerts(): Promise<void> {
  if (busy || !mayAsk()) return;
  busy = true;
  try {
    const r = await api<AlertsReply>(since ? `/api/outreach/alerts?since=${encodeURIComponent(since)}` : '/api/outreach/alerts');
    for (const a of Array.isArray(r?.items) ? r.items : []) {
      if (seen.has(a.id)) continue;
      seen.add(a.id);
      pushToast(alertText(a), 'warning');
    }
    if (typeof r?.now === 'string') since = r.now;
  } catch {
    // 다음 바퀴에 다시 묻는다(커서는 그대로).
  } finally {
    busy = false;
  }
}

/** 바탕화면(과 태블릿·폰 껍데기)에 한 번 단다 — 역할이 볼 수 있을 때만 20초마다 묻는다. */
export function useOutreachAlerts(): void {
  const role = useSession((s) => s.session?.user.role ?? null);
  const locked = useSession((s) => s.locked);
  useEffect(() => {
    if (role === null || role === 'field' || locked) return;
    void pollOutreachAlerts();
    const timer = setInterval(() => void pollOutreachAlerts(), ALERT_POLL_MS);
    return () => clearInterval(timer);
  }, [role, locked]);
}
