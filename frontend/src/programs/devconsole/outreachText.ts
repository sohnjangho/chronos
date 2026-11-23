// 연락 기록(Task 108)의 화면 글: 상태·통로·시작한 쪽·권한 방식·등급. 값은 계획 4 이름표의 낱말이다(서버가 준 값을 바꾸지 않고
// 읽기만 한다 — 모르는 값은 그대로 보인다). 사건 이름·묶음의 글은 서버(harness.types 상수)가 준다.
import type { Tone } from '../../shared/ui/Badge';
import type { OutreachRow } from './devApi';

const STATUS: Record<string, [string, Tone]> = {
  draft: ['초안', 'neutral'],
  scheduled: ['예약', 'info'],
  sending: ['보내는 중', 'info'],
  accepted: ['접수', 'success'],
  delivered: ['도착', 'success'],
  failed: ['실패', 'danger'],
  unconfirmed: ['보냈는지 확인 필요', 'warning'],
  blocked_test: ['시험 모드로 보내지 않음', 'neutral'],
  received: ['받음', 'success'],
  queued: ['줄에 넣음', 'info'],
  dialing: ['거는 중', 'info'],
  in_call: ['통화하는 중', 'info'],
  completed: ['통화됨', 'success'],
  no_answer: ['받지 않음', 'neutral'],
  busy: ['통화 중', 'neutral'],
  blocked_hours: ['근무시간 밖으로 막힘', 'neutral'],
  rejected: ['받지 않고 거절', 'neutral'],
  missed: ['받을 수 없었음', 'warning'],
};
const CHANNEL: Record<string, string> = { sms: '문자', kakao: '카카오톡', call: '전화' };
const MODE: Record<string, string> = { manual: '직접', approved: '승인', delegated: '위임' };
const CLASS: Record<string, string> = {
  internal: '내부',
  contact: '연락처',
  contact_multi: '여러 현장 연락처',
  shared: '함께 쓰는 번호',
  do_not_contact: '수신 거부',
  unknown: '모르는 번호',
  withheld: '번호 숨김',
  blocked: '차단',
  outside_test: '시험 모드 밖',
  outbound: '우리가 먼저 연락',
};

export const statusOf = (s: string): { label: string; tone: Tone } => {
  const [label, tone] = STATUS[s] ?? [s, 'neutral'];
  return { label, tone };
};
export const channelOf = (r: Pick<OutreachRow, 'channel' | 'direction'>) =>
  `${CHANNEL[r.channel] ?? r.channel} ${r.direction === 'in' ? '받음' : '보냄'}`;
export const modeOf = (m: string | null) => (m ? (MODE[m] ?? m) : '—');
export const classOf = (c: string | null) => (c ? (CLASS[c] ?? c) : '—');

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
