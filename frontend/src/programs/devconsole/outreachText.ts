// 연락 기록(Task 108)의 화면 글: 상태·통로·시작한 쪽·권한 방식·등급. 값은 계획 4 이름표의 낱말이다(서버가 준 값을 바꾸지 않고
// 읽기만 한다 — 모르는 값은 그대로 보인다). 사건 이름·묶음의 글은 서버(harness.types 상수)가 준다.
import { CALL_UNSURE_TEXT, callerClassLabel, callStatusLabel, statusLabel, type Tone as LabelTone } from '../../shared/outreach/labels';
import type { Message } from '../../shared/outreach/outreachApi';
import type { Tone } from '../../shared/ui/Badge';
import type { OutreachHead, OutreachRow } from './devApi';

// 등급·상태 글은 연락처 화면과 한 곳(shared/outreach/labels.ts — Task 96 후속): 같은 줄이 두 화면에서 같은 말로 읽힌다.
const TONE: Record<LabelTone, Tone> = { ok: 'success', info: 'info', warn: 'warning', bad: 'danger', muted: 'neutral' };
const CHANNEL: Record<string, string> = { sms: '문자', kakao: '카카오톡', call: '전화' };
const MODE: Record<string, string> = { manual: '직접', approved: '승인', delegated: '위임' };
/** 연락처 화면에는 칩이 없는 등급(받지 않은 상대 · 우리가 건 통화의 상대) — 콘솔에서만. */
const CONSOLE_CLASS: Record<string, string> = { blocked: '차단', outside_test: '시험 모드 밖', outbound: '우리가 먼저 연락' };

/** 줄의 상태 배지 — 통화는 통화 카드(callStatusLabel), 문자는 말풍선(statusLabel)과 같은 글. 목록 줄에는 사건·까닭이 없어 거절은
 *  「받지 않음」, 길이가 없으면 「통화함」(머리 줄은 길이·실패 까닭을 준다). 결과를 모르는 통화(서버의 needs_check)는 「실패」가 아니라 「확인 필요 — 걸렸는지 알 수 없음」. */
export function rowStatusOf(r: Pick<OutreachRow, 'kind' | 'status' | 'needs_check' | 'direction'> & Pick<Partial<OutreachHead>, 'duration_s' | 'fail_reason'>): { label: string; tone: Tone } {
  if (r.kind === 'call' && r.needs_check) return { label: CALL_UNSURE_TEXT, tone: 'warning' };
  const base = { status: r.status, events: [], fail_reason: r.fail_reason ?? null, scheduled_at: null };
  const l = r.kind === 'call'
    ? callStatusLabel({ ...base, duration_s: r.duration_s ?? null, direction: r.direction } as Parameters<typeof callStatusLabel>[0])
    : statusLabel({ ...base, fallback_sms: false } as unknown as Message);
  return { label: l.text, tone: TONE[l.tone] };
}
/** 통로·방향: 거는 통화는 「AI 전화」(보낸 것이 아니라 건 것), 그 밖은 「문자 보냄」·「전화 받음」 꼴. */
export const channelOf = (r: Pick<OutreachRow, 'channel' | 'direction'>) =>
  r.channel === 'call' && r.direction !== 'in' ? 'AI 전화' : `${CHANNEL[r.channel] ?? r.channel} ${r.direction === 'in' ? '받음' : '보냄'}`;
export const modeOf = (m: string | null) => (m ? (MODE[m] ?? m) : '—');
export const classOf = (c: string | null) => (c ? (callerClassLabel(c) ?? CONSOLE_CLASS[c] ?? c) : '—');

/** 누가 시작했나: 사람 이름 · 에이전트 · 상대. */
export function starterOf(r: Pick<OutreachRow, 'origin' | 'origin_name'>): string {
  if (r.origin === 'agent') return '에이전트';
  if (r.origin === 'peer') return '상대';
  return r.origin_name || '사람';
}

/** 누구와: 주소록 이름 · 협력사, 없으면 「모르는 번호」와 가린 번호. */
export function whoOf(r: Pick<OutreachRow, 'contact_name' | 'company_name' | 'number_masked'>): string {
  if (!r.contact_name) return `모르는 번호 ${r.number_masked}`;
  return r.company_name ? `${r.contact_name} · ${r.company_name}` : r.contact_name;
}
