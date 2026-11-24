// 시스템 진단 대응표 — 문자 연결 · 카카오톡 · AI 전화(notify 칸과 그 안의 kakao · voice). 저장된 값만 보인다(다시 돌리지 않는다).
import type { KakaoHealth, NotifyHealth, VoiceHealth } from './devApi';
import { type Check, type CheckState, diagFlags, fromStatus, NOT_YET, TEST_WORD, when, worse } from './healthModel';

const INBOUND: Record<string, string> = { off: '받지 않음', known: '주소록에 있는 번호만', all: '모두' };
const AGENT: Record<string, string> = { approve: '승인', delegate: '위임' };
const NOTIFY_WORKER: [string, string][] = [
  ['last_tick_at', '마지막 바퀴'],
  ['last_due_at', '예약 발송'],
  ['last_status_poll_at', '상태 조회'],
  ['last_inbound_poll_at', '받은 문자 조회'],
];
const PROVIDER: Record<string, string> = { google: '구글(Gemini Live)', openai: 'OpenAI', dashboard: '대시보드' };
const BACKEND: Record<string, string> = { ok: '준비됨', not_ready: '준비 안 됨', sdk_missing: 'SDK 없음' };
const OFF: Record<string, string> = { disabled: '꺼 둔 설정', sandbox: '시험 격리' };
// 받는 통화 듣기가 붙어 있지 않은 까닭(서버 runner.status().listen_reason). 끝까지 쉬는 까닭(STUCK)은 다시 붙는 길을 보인다.
const LISTEN: Record<string, string> = {
  off: '받는 범위가 「받지 않음」', not_ready: '음성 설정이 덜 됨', waiting: '통화·진단이 끝나기를 기다림', paused: '음성 진단 동안 멈춤',
  gave_up: '여러 번 붙지 못해 쉼', taken_over: '다른 접속이 이 번호를 가져감', auth_rejected: '플랫폼이 연결을 거절함',
};
const STUCK = new Set(['gave_up', 'taken_over', 'auth_rejected']);

export function notify(nh: NotifyHealth): Check {
  const base = { id: 'notify', source: 'notify', area: 'contact' as const, name: '문자 연결', tech: '알림 연결', raw: nh };
  if (!nh.connected) {
    return {
      ...base, state: 'check', summary: '알림 연결이 없습니다 — 문자 · 전화는 나가지 않습니다',
      todo: '설정 → 알림 연결', impact: '현장에 보내는 문자 · 알림톡 · AI 전화가 모두 이 연결로 나갑니다.',
      fields: [], checkedAt: { at: null, server: true },
    };
  }
  const flags = diagFlags(nh.last_diagnosis);
  let state: CheckState = fromStatus(nh.status) ?? 'unknown';
  if (nh.needs_check > 0 || flags.failed.length || flags.check.length || flags.unfinished) state = worse(state, 'check');
  const label = nh.status === 'ok' ? '정상' : nh.status === 'failed' ? '실패' : '모름';
  const steps = [...flags.failed, ...flags.check].map((s) => `${s.id} 「${s.detail || s.label}」`);
  const agent = nh.agent ?? {};
  const w = nh.worker;
  return {
    ...base, state,
    summary: [`연결 ${label}`, nh.sender_masked ? `발신 ${nh.sender_masked}` : null, nh.needs_check > 0 ? `보냈는지 모름 ${nh.needs_check}건 — 자동으로 다시 보내지 않습니다` : null, steps.length ? `마지막 진단 ${steps.join(' · ')}` : null]
      .filter(Boolean).join(' · '),
    todo: nh.status === 'failed' ? '설정 → 알림 연결 → 연결 시험' : nh.needs_check > 0 ? `연락처에서 ${nh.needs_check}건 확인` : state === 'ok' ? null : '설정 → 알림 연결 → 연결 진단',
    impact: '현장에 보내는 문자 · 알림톡 · AI 전화가 모두 이 연결로 나갑니다. 보냈는지 모르는 문자는 사람이 확인해야 합니다.',
    fields: [
      { title: '설정', rows: [
        ['마지막 연결 시험', when(nh.checked_at)], ['시험 모드', nh.test_mode ? '켬' : '끔'], ['허용 번호', `${nh.allow_count}개`],
        ['발신번호', nh.sender_masked ?? '없음'], ['받는 범위', INBOUND[nh.inbound_mode ?? ''] ?? nh.inbound_mode ?? '—'],
        ['에이전트 권한', `문자 ${AGENT[agent.sms] ?? '—'} · 카카오톡 ${AGENT[agent.kakao] ?? '—'} · 전화 ${AGENT[agent.call] ?? '—'}`],
        ['확인 필요', `${nh.needs_check}건`], ['카카오톡', nh.kakao ? '「카카오톡」 줄' : NOT_YET], ['AI 전화', nh.voice ? '설정됨 — 「AI 전화」 줄' : NOT_YET],
      ] },
      { title: '조회 일꾼', rows: w ? [['조회 일꾼', w.running ? '돌고 있음' : '멈춤'], ...NOTIFY_WORKER.map(([k, l]) => [l, when(w[k])] as [string, string]),
        ['마지막 오류', typeof w.last_error_kind === 'string' ? w.last_error_kind : '없음']] : [['조회 일꾼', '상태를 읽을 수 없음']] },
    ],
    steps: nh.last_diagnosis ? { title: '마지막 연결 진단', diag: nh.last_diagnosis } : null,
    note: nh.last_diagnosis ? null : '저장된 연결 진단이 없습니다(설정 → 알림 연결 → 연결 진단).',
    checkedAt: { at: nh.checked_at, server: true },
  };
}

export function kakao(k: KakaoHealth): Check {
  const base = { id: 'kakao', source: 'notify.kakao', area: 'contact' as const, name: '카카오톡', tech: '알림톡', raw: k };
  const impact = '알림톡으로 보내려는 글입니다. 쓸 수 없으면 같은 글이 문자로 나갑니다.';
  if (k.channel === null) {
    return { ...base, state: 'ok', summary: '연결된 채널 없음 — 쓰지 않음 · 알림톡 요청은 문자로 나갑니다', todo: null, impact, fields: [], checkedAt: { at: k.synced_at, server: true } };
  }
  const t = k.templates;
  return {
    ...base, state: k.ready ? 'ok' : 'check',
    summary: `「${k.channel}」 · 문안 승인 ${t.approved} · 검수 중 ${t.reviewing} · 반려 ${t.rejected}${t.dormant ? ` · 휴면 ${t.dormant}` : ''}${k.ready ? '' : ' · 준비 안 됨'}`,
    todo: k.ready ? null : '설정 → 알림 연결 → 카카오톡에서 채널 · 문안 확인',
    impact,
    fields: [{ title: '저장된 값', rows: [
      ['채널', k.channel], ['쓸 수 있음', k.ready ? '예' : '준비 안 됨'], ['마지막으로 읽은 때', when(k.synced_at)],
      ['목록 읽는 길', k.available ? '확인됨' : '아직 확인하지 못함'],
      ['문안 승인', `${t.approved}개`], ['문안 검수 중', `${t.reviewing}개`], ['문안 반려', `${t.rejected}개`], ['문안 휴면', `${t.dormant}개`],
    ] }],
    checkedAt: { at: k.synced_at, server: true },
  };
}

export function voice(v: VoiceHealth): Check {
  const w = v.worker;
  const flags = diagFlags(v.last_diagnosis);
  let state: CheckState = fromStatus(v.status) ?? 'unknown';
  if (state === 'ok' && (flags.failed.length || flags.check.length || flags.unfinished)) state = 'check';
  const why = w && typeof w.listen_reason === 'string' ? w.listen_reason : null;
  const stuck = !!w && !w.listening && !!why && STUCK.has(why);
  if (stuck || (w && !w.running)) state = worse(state, 'check');
  const off = w && typeof w.off_reason === 'string' ? ` (${OFF[w.off_reason] ?? w.off_reason})` : '';
  const listen = w?.listening ? '받는 중(번호 묶임)' : why ? `붙어 있지 않음 — ${LISTEN[why] ?? why}` : '붙어 있지 않음';
  const verdict = v.status === 'ok' ? '음성 진단 정상' : v.status === 'failed' ? '음성 진단 실패' : '음성 진단을 아직 하지 않아 판정이 없습니다';
  return {
    id: 'voice', source: 'notify.voice', area: 'contact', name: 'AI 전화', tech: PROVIDER[v.provider] ?? v.provider, state,
    summary: [verdict, w ? `통화 일꾼 ${w.running ? '돌고 있음' : `멈춤${off}`}` : null, w && !w.listening && why ? `받는 통화는 ${LISTEN[why] ?? why}` : null].filter(Boolean).join(' · '),
    todo: state === 'ok' ? null : '설정 → 알림 연결 → AI 전화 → 음성 진단',
    impact: 'AI 가 현장에 거는 전화와 걸려 오는 전화를 받는 일입니다. 판정이 없거나 실패면 통화가 나가지 못할 수 있습니다.',
    fields: [
      { title: '음성 설정', rows: [
        ['공급자', PROVIDER[v.provider] ?? v.provider], ['음성 모델', v.model ?? 'SDK 기본'], ['음성 SDK', v.sdk_installed ? '설치됨' : '설치되지 않음'],
        ['마지막 음성 진단 판정', v.checked_at ? `${TEST_WORD[v.status] ?? v.status} · ${when(v.checked_at)}` : '아직 진단 안 함'],
      ] },
      { title: '통화 일꾼', rows: w ? [
        ['통화 일꾼', w.running ? '돌고 있음' : `멈춤${off}`], ['음성 서버', BACKEND[String(w.backend)] ?? String(w.backend ?? '—')], ['받는 통화 듣기', listen],
        ['지금 통화', `${typeof w.live === 'number' ? w.live : 0}통`], ['마지막 통화', when(w.last_call_at)],
        ['마지막 오류', typeof w.last_error_kind === 'string' ? w.last_error_kind : '없음'],
      ] : [['통화 일꾼', '상태를 읽을 수 없음']] },
    ],
    steps: v.last_diagnosis ? { title: '마지막 음성 진단', diag: v.last_diagnosis } : null,
    note: stuck
      ? '음성 설정을 바꾸거나, 받는 범위를 껐다 켜거나, 서버를 다시 시작하면 다시 붙습니다.'
      : v.last_diagnosis ? null : '저장된 음성 진단이 없습니다(설정 → 알림 연결 → AI 전화 → 음성 진단).',
    raw: v, checkedAt: { at: v.checked_at, server: true },
  };
}
