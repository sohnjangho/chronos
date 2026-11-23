// 긴급 보고 토스트(Task 85): 20초마다 GET /api/outreach/alerts?since=… 를 묻고, 처음 보는 긴급 보고마다 토스트 하나.
// 현장 관리자(연락처를 열 수 없음)·로그인 안 함·잠김이면 묻지 않고, 브라우저 탭이 안 보이는 동안은 건너뛴다.
// since 는 서버가 준 now 에서 30초 앞(서버 시계 — 그 언저리에 들어온 보고를 놓치지 않게 겹치고, 본 보고는 id 로 거른다).
// 실패하면 다음 물음까지 두 배씩(2분까지) 쉬고, 되면 20초로 돌아간다. 토스트 글에는 번호가 없다 — 보고 글은 싣지 않고, 이름에
// 전화번호 꼴이 있으면 「[번호]」로 바꾼다(서버가 이미 가린 것에 한 겹 더 — 「123동 신축」 같은 숫자는 그대로).
import { useEffect } from 'react';
import { api } from '../shared/api';
import { onUserChange, useSession } from './session';
import { pushToast } from './ToastStack';

export const ALERT_POLL_MS = 20_000;
export const ALERT_MAX_MS = 120_000;
/** 커서를 서버 now 보다 이만큼 앞에 둔다. */
export const ALERT_OVERLAP_MS = 30_000;
/** 기억하는 본 보고 수(넘으면 오래된 것부터 잊는다). */
export const SEEN_MAX = 200;

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
let failures = 0;
const seen = new Set<number>();

/** 시험·사용자 바뀜: 처음부터(커서·본 보고·쉼을 잊는다). */
export function resetOutreachAlerts(): void {
  since = null;
  busy = false;
  failures = 0;
  seen.clear();
}
onUserChange(() => resetOutreachAlerts());

/** 처음 보는 보고면 참(기억은 SEEN_MAX 개까지 — Set 은 넣은 차례를 지킨다). */
function firstTime(id: number): boolean {
  if (seen.has(id)) return false;
  seen.add(id);
  if (seen.size > SEEN_MAX) seen.delete(seen.values().next().value as number);
  return true;
}

// 전화번호 꼴만: 국내(0 또는 +82 로 시작, 빈칸·-·.·괄호 사이) 9~11자리와 대표번호(15xx·16xx·18xx-xxxx).
const PHONE = /(?:\+\s?82[\s.()-]*|\b0)\d{1,2}[\s.()-]*\d{3,4}[\s.()-]*\d{4}\b|\b1[568]\d{2}[\s.-]?\d{4}\b/g;
const noPhones = (s: string) => s.replace(PHONE, '[번호]');

/** 「긴급 보고 — 5층 사무동 신축 · 박현장 · 전화로 받은 보고」 */
export function alertText(a: OutreachAlert): string {
  const where = a.schedule_name ?? '일정 없음';
  const who = a.contact_name ?? '모르는 번호';
  return noPhones(`긴급 보고 — ${where} · ${who} · ${a.medium === 'call' ? '전화로 받은 보고' : '문자로 받은 보고'}`);
}

const mayAsk = () => {
  const { session, locked } = useSession.getState();
  return session !== null && !locked && session.user.role !== 'field';
};

const cursor = (now: string) => {
  const t = Date.parse(now);
  return Number.isNaN(t) ? now : new Date(t - ALERT_OVERLAP_MS).toISOString();
};

/** 한 번 묻는다. 실패하면 커서를 두고 쉼을 늘린다. 겹쳐 부르면 하나만. 탭이 안 보이면 묻지 않는다. */
export async function pollOutreachAlerts(): Promise<void> {
  if (busy || !mayAsk() || document.hidden) return;
  busy = true;
  try {
    const r = await api<AlertsReply>(since ? `/api/outreach/alerts?since=${encodeURIComponent(since)}` : '/api/outreach/alerts');
    for (const a of Array.isArray(r?.items) ? r.items : []) if (firstTime(a.id)) pushToast(alertText(a), 'warning');
    if (typeof r?.now === 'string') since = cursor(r.now);
    failures = 0;
  } catch {
    failures += 1; // 다음 물음까지 더 쉰다(커서는 그대로).
  } finally {
    busy = false;
  }
}

/** 다음 물음까지: 20초, 실패가 이어지면 40·80·120(2분)초. */
export const nextDelay = () => Math.min(ALERT_POLL_MS * 2 ** failures, ALERT_MAX_MS);

/** 바탕화면에 한 번 단다 — 역할이 볼 수 있을 때만 묻는다. */
export function useOutreachAlerts(): void {
  const role = useSession((s) => s.session?.user.role ?? null);
  const locked = useSession((s) => s.locked);
  useEffect(() => {
    if (role === null || role === 'field' || locked) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = async () => {
      await pollOutreachAlerts();
      if (alive) timer = setTimeout(() => void tick(), nextDelay());
    };
    void tick();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [role, locked]);
}
