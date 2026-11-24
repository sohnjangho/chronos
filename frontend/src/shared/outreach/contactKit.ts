// 다른 화면에서 연락 시작하기(Task 104) — ContactButton·ReplyCandidates 가 같이 쓰는 것: 누가 쓸 수 있는지(현장 관리자는 연락처·
// 문자 길을 쓰지 않는다 — 서버도 403), 알림 연결이 있는지(GET /api/notify/status 의 ready), 미리 채우는 문자 글.
// 카카오톡이 잠겨 있는 동안(지금)은 문안 대신 같은 뜻의 문자 글(docs/design/kakao-templates-draft.md 의 「문자 대신 보내기」에서
// 사람 이름을 뺀 것 — 한 글이 여러 사람에게 간다)이고, 작업 이름·날짜는 현장 항목·승인 건 자료에서 코드가 채운다. 채운 값은
// 서버 글 검사(보이지 않는 글자·글 방향 글자 → 422 invalid_text)에 걸리지 않게 지우고 줄인다.
import { useEffect, useState } from 'react';
import { useSession } from '../../os/session';
import { api } from '../api';

/** 스케줄·간트의 [연락]: 고른 작업 행이 없을 때의 까닭. */
export const PICK_ROW = '작업 행을 먼저 고르세요';

/** 현장 관리자가 아니면 true(연락 단추·회신 후보를 그린다). */
export function useCanContact(): boolean {
  return useSession((s) => s.session !== null && s.session.user.role !== 'field');
}

let asking: Promise<boolean> | null = null;
/** 한 화면의 여러 단추가 같이 물어도 요청은 하나(돌아온 뒤에는 다시 묻는다). 읽지 못하면 연결 없음으로 본다. */
function readReady(): Promise<boolean> {
  asking ??= api<{ ready?: unknown }>('/api/notify/status')
    .then((s) => s?.ready === true, () => false)
    .finally(() => {
      asking = null;
    });
  return asking;
}

/** 알림 연결: null = 묻는 중, true = 있음, false = 없음(또는 읽지 못함). on 이 false 면 묻지 않는다. */
export function useNotifyReady(on: boolean): boolean | null {
  const [ready, setReady] = useState<boolean | null>(null);
  useEffect(() => {
    if (!on) return;
    let live = true;
    void readReady().then((r) => live && setReady(r));
    return () => {
      live = false;
    };
  }, [on]);
  return ready;
}

// 서버(app/programs/outreach/service.py)가 막는 글자: 줄 바꿈·탭 밖의 제어 글자, 글 방향 글자, 줄·문단 구분, 폭 없는 빈칸
// eslint-disable-next-line no-control-regex
const HIDDEN = /[\u0000-\u0008\u000B-\u001F\u007F-\u009F\u200B\u200E\u200F\u061C\u2028\u2029\u202A-\u202E\u2066-\u2069]/g;
const VALUE_MAX = 80;
const QUESTION_MAX = 300;

/** 글에 넣을 값: 막히는 글자를 지우고 빈칸·줄 바꿈은 빈칸 하나로, max 자를 넘으면 줄이고 「…」. */
export function cleanValue(v: unknown, max = VALUE_MAX): string {
  const text = String(v ?? '').replace(HIDDEN, '').replace(/\s+/g, ' ').trim();
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

/** 'YYYY-MM-DD' 는 그날, 시각이 있으면 KST 의 그날 → 「11월 30일」. 읽지 못하면 빈 글. */
export function dayKo(v: unknown): string {
  if (typeof v !== 'string') return '';
  const only = /^(\d{4})-(\d{2})-(\d{2})$/.exec(v);
  if (only) return `${Number(only[2])}월 ${Number(only[3])}일`;
  const t = Date.parse(v);
  if (Number.isNaN(t)) return '';
  const kst = new Date(t + 9 * 3_600_000);
  return `${kst.getUTCMonth() + 1}월 ${kst.getUTCDate()}일`;
}

const join = (...parts: string[]) => parts.filter(Boolean).join(' ');
const ANSWER = '이 번호로 답 문자 주세요.';

/** 체크인 요청(문안 「체크인 요청」의 문자 글). 날짜 = 체크인 항목을 만든 날. */
export function checkinText(item: { activity_name: string; created_at: string }, site: string): string {
  return `${join('[크로노스]', cleanValue(site), dayKo(item.created_at), cleanValue(item.activity_name))} 체크인 부탁드립니다(인원·시작 시각·막히는 점). ${ANSWER}`;
}

/** 만회안 의견 조회 — 맞는 카카오톡 문안이 없어 문자 글만. 질문은 그 항목의 글. */
export function pollText(item: { activity_name: string; prompt_text: string }, site: string): string {
  return `${join('[크로노스]', cleanValue(site), cleanValue(item.activity_name))} 만회안 의견을 여쭙니다 — ${cleanValue(item.prompt_text, QUESTION_MAX)} ${ANSWER}`;
}

/** D-3 핸드오프(문안 「D-3 준비 확인」의 문자 글). 시작일 = 후행 작업 시작(payload.succ_start), 남은 날 = payload.days_left(없으면 3). */
export function handoffText(item: { activity_name: string; payload_json: Record<string, unknown> }): string {
  const p = item.payload_json ?? {};
  const left = typeof p.days_left === 'number' && Number.isFinite(p.days_left) ? Math.max(0, Math.round(p.days_left)) : 3;
  const start = dayKo(p.succ_start);
  return `[크로노스] ${cleanValue(item.activity_name)} 시작 ${left}일 전입니다${start ? `(${start})` : ''}. 자재·장비·인력 준비 상태를 ${ANSWER}`;
}

/** 승인 대기 알림(문안 「승인 대기 알림」의 문자 글). 날짜 = 올린 날. */
export function approvalText(item: { title: string; created_at: string }): string {
  const day = dayKo(item.created_at);
  return `[크로노스] 승인을 기다리는 건이 있습니다: ${cleanValue(item.title)}${day ? `(${day})` : ''}. 승인함에서 확인해 주세요. 문의는 이 번호로 문자 주세요.`;
}
