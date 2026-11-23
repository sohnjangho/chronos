// 메시지 한 줄을 사람 말로: 누가 보냈나(senderTag) · 어떻게 됐나(statusLabel) · 방금 누른 보내기의 판정(outcomeLabel) ·
// 하네스 사건 한 줄(eventLine·eventSummary) · KST 시각. 연락처 창의 대화 칸과 대화 카드가 같은 글을 쓴다.
// 통로 결과는 셋이다 — 도착·접수 / 실패 / 「확인 필요 — 보냈는지 알 수 없음」. 셋째를 실패나 성공으로 그리지 않는다.
import type { Message, MessageChannel, Outcome, OutreachEvent } from './outreachApi';

export type Tone = 'ok' | 'info' | 'warn' | 'bad' | 'muted';
export interface Label {
  text: string;
  tone: Tone;
}

export const UNSURE_TEXT = '확인 필요 — 보냈는지 알 수 없음';
const FALLBACK_TEXT = '카카오톡 실패 → 문자로 대신 보냄';

// ── 시각(KST, 브라우저 시간대와 상관없이) ──────────────────────────────────
const KST_MS = 9 * 3_600_000;
const WEEKDAYS = ['일', '월', '화', '수', '목', '금', '토'];
const two = (n: number) => String(n).padStart(2, '0');

function kst(iso: string) {
  const d = new Date(new Date(iso).getTime() + KST_MS);
  return { y: d.getUTCFullYear(), mo: d.getUTCMonth() + 1, d: d.getUTCDate(), wd: WEEKDAYS[d.getUTCDay()], hm: `${two(d.getUTCHours())}:${two(d.getUTCMinutes())}` };
}

/** 2026년 11월 23일 월요일 */
export function kstDay(iso: string): string {
  const t = kst(iso);
  return `${t.y}년 ${t.mo}월 ${t.d}일 ${t.wd}요일`;
}
/** 17:30 */
export const kstTime = (iso: string) => kst(iso).hm;
/** 11/24 */
export function kstDate(iso: string): string {
  const t = kst(iso);
  return `${t.mo}/${t.d}`;
}
/** 11/24(화) 08:00 */
export function kstShort(iso: string): string {
  const t = kst(iso);
  return `${t.mo}/${t.d}(${t.wd}) ${t.hm}`;
}

export const channelLabel = (c: MessageChannel) => (c === 'kakao' ? '카카오톡' : '문자');

// ── 누가 보냈나 ────────────────────────────────────────────────────────────
/** [김공정 발신] / [에이전트 발신] · 김공정 승인 / [에이전트 발신 · 위임] / [상대 발신]. 승인한 사람이 없으면 적지 않는다. */
export function senderTag(m: Message): string {
  if (m.direction === 'in' || m.origin === 'peer') return '[상대 발신]';
  if (m.origin === 'user') return `[${m.origin_name || '사용자'} 발신]`;
  if (m.send_mode === 'delegated') return '[에이전트 발신 · 위임]';
  return m.approved_by ? `[에이전트 발신] · ${m.approved_by} 승인` : '[에이전트 발신]';
}

// ── 어떻게 됐나 ────────────────────────────────────────────────────────────
function plainStatus(m: Message): Label {
  switch (m.status) {
    case 'delivered':
      return { text: '도착', tone: 'ok' };
    case 'accepted':
      return { text: '접수', tone: 'info' };
    case 'failed':
      return { text: m.fail_reason ? `실패 — ${m.fail_reason}` : '실패', tone: 'bad' };
    case 'unconfirmed':
      return { text: UNSURE_TEXT, tone: 'warn' };
    case 'scheduled':
      return { text: m.scheduled_at ? `예약됨 ${kstShort(m.scheduled_at)}` : '예약됨', tone: 'info' };
    case 'blocked_test':
      return { text: '시험 모드로 보내지 않음', tone: 'warn' };
    case 'sending':
      return { text: '보내는 중', tone: 'muted' };
    case 'received':
      return { text: '받음', tone: 'muted' };
    case 'draft':
      // 뒤 확인에 걸린 자동 답은 사람이 읽어 본 뒤에 보낸다.
      return m.events.some((e) => e.rule === 'held_for_review') ? { text: '확인 뒤 보내기', tone: 'warn' } : { text: '아직 보내지 않음', tone: 'muted' };
    default:
      return { text: `알 수 없는 상태(${String(m.status)})`, tone: 'warn' };
  }
}

/** 줄의 상태 글과 색. 카카오톡이 문자로 대신 나간 줄은 그 말을 앞에 붙인다. */
export function statusLabel(m: Message): Label {
  const s = plainStatus(m);
  return m.fallback_sms ? { text: `${FALLBACK_TEXT} · ${s.text}`, tone: s.tone } : s;
}

/** 방금 누른 보내기의 판정. 보냄·실패·확인 필요는 셋으로, 그 밖(예약·막힘·「잠시 뒤 다시」)은 문의 글 그대로. */
export function outcomeLabel(o: Outcome): Label {
  if (o.code === 'accepted' || o.code === 'queued') return { text: o.message, tone: 'ok' };
  if (o.code === 'failed') return { text: `실패 — ${o.message}`, tone: 'bad' };
  if (o.code === 'unsure') return { text: UNSURE_TEXT, tone: 'warn' };
  if (o.code === 'scheduled') return { text: o.scheduled_at ? `${o.message} · ${kstShort(o.scheduled_at)}` : o.message, tone: 'info' };
  return { text: o.message, tone: 'warn' };
}

// ── 하네스 사건 ────────────────────────────────────────────────────────────
// API 는 사건의 이름(rule)·판정·detail 만 준다(한글 이름표 없음). 화면의 사건 한글은 아래 세 표에서만 읽는다(harness.types 의 낱말).
// 개발 콘솔(backend/app/programs/devconsole/outreach_view.py 의 ORDER_LABELS·VERDICT_LABELS·CODE_TEXT)과 겹치는 낱말은 그 글과
// 똑같이 둔다 — labels.test.ts 가 그 파일을 읽어 맞춰 본다. 표에 없는 이름은 지어내지 않고 이름 그대로 보인다.
export const VERDICT_LABEL: Readonly<Record<string, string>> = { blocked: '막음', allowed: '지나감', noted: '메모' };
export const RULE_LABEL: Readonly<Record<string, string>> = {
  precheck: '앞 확인', test_mode: '시험 모드·허용 번호', blocked_or_dnc: '차단·수신 거부', working_hours: '근무시간', limits: '상한',
  permission: '권한', duplicate: '중복', channel_choice: '통로 고르기',
  reply_within_grace: '답 유예', kakao_not_ready: '카카오톡 준비 전',
  delivery: '통로 결과', delivery_update: '뒤에 확인한 상태', admission: '받기 판정',
  unsupported_date: '근거 없는 날짜', unsupported_answer: '근거 없는 답', out_of_scope_said: '범위 밖 내용', money_said: '금액·계약 언급',
  disclosed_to_unknown: '모르는 사람에게 일정 이름', held_for_review: '뒤 확인에 걸림',
  reply_failed: '답을 만들지 못함', server_restart: '서버가 다시 떠서 닫음', site_pinned: '현장 정함',
  tool_not_allowed: '허용되지 않은 도구', tool_bad_args: '도구 인자 오류', scope_denied: '범위 밖 요청',
};
/** detail 이 정해 둔 코드 하나인 이름(FIXED_DETAILS)의 코드 → 글. */
export const CODE_LABEL: Readonly<Record<string, Readonly<Record<string, string>>>> = {
  channel_choice: { sms: '문자', kakao: '카카오톡', call: '전화' },
  delivery_update: { delivered: '도착', failed: '실패', gave_up: '결과 확인을 그만둠' },
  admission: {
    inbound_off: '받는 범위가 「받지 않음」', outside_test: '시험 모드 — 허용 번호 아님', blocked_number: '차단 번호', burst_limit: '잦은 연락 상한',
    auto_reply_limit: '자동 답 상한', stop_word: '수신 거부 말', machine_text: '기계가 보낸 문자', media_attached: '사진이 붙음',
    do_not_contact: '수신 거부 연락처', unknown_not_accepted: '모르는 번호 — 받지 않음', unknown_accepted: '모르는 번호 — 응대',
    line_busy: '동시 통화 한도', known_caller: '아는 상대 — 응대',
  },
};

/** 판정 한 낱말: 막음 · 지나감 · 메모(모르는 판정은 그대로). */
export const verdictLabel = (verdict: string) => VERDICT_LABEL[verdict] ?? verdict;

/** 사건 한 줄: 「근무시간 — 근무시간 밖이라 다음 근무 시작에 보냅니다」. */
export function eventLine(e: OutreachEvent): string {
  const label = RULE_LABEL[e.rule] ?? (e.rule.startsWith('tool:') ? `도구 ${e.rule.slice(5)}` : e.rule);
  const detail = e.detail === null ? null : (CODE_LABEL[e.rule]?.[e.detail] ?? e.detail);
  return detail ? `${label} — ${detail}` : label;
}

/** 상태 이름표가 이미 말하는 사건(통로 고르기·통로 결과·뒤에 확인한 상태·카카오톡 대신 문자) — 접힌 줄에서는 건수로만 센다. */
const SAID_BY_STATUS = new Set(['channel_choice', 'delivery', 'delivery_update', 'kakao_not_ready']);

/** 나가는 문의 판정 사건(보내기 한 번마다 꼭 하나 — 그 앞의 참고와 그 뒤의 통로 결과가 한 번의 시도다). */
const GATE_DECISIONS = new Set(['precheck', 'test_mode', 'blocked_or_dnc', 'working_hours', 'limits', 'permission', 'duplicate', 'channel_choice']);

/** 접힌 한 줄. 근무시간에 걸려 예약된 줄은 「근무시간 밖 → 월 08:00 예약」, 그 밖은 마지막 시도에서 화면이 아직 말하지 않은 참고·막음과
 *  건수, 그런 것이 없으면 「처리 기록 n건」. 사건이 없으면 null. */
export function eventSummary(m: Message): string | null {
  const n = m.events.length;
  if (n === 0) return null;
  const decisions = m.events.flatMap((e, i) => (GATE_DECISIONS.has(e.rule) ? [i] : []));
  const latest = m.events.slice(decisions.length > 1 ? decisions[decisions.length - 2] + 1 : 0); // 앞선 시도의 막음을 되풀이하지 않는다
  const pick = latest.filter((e) => e.verdict !== 'allowed' && !SAID_BY_STATUS.has(e.rule) && (e.detail === null || e.detail !== m.fail_reason)).at(-1);
  if (!pick) return `처리 기록 ${n}건`;
  if (pick.rule === 'working_hours' && m.status === 'scheduled' && m.scheduled_at) {
    const t = kst(m.scheduled_at);
    return `근무시간 밖 → ${t.wd} ${t.hm} 예약`;
  }
  return n > 1 ? `${eventLine(pick)} · 기록 ${n}건` : eventLine(pick);
}
