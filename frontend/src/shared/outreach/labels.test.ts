// 발신 글 네 가지 · 상태 글(셋으로 갈린 결과가 셋으로 남는지) · 보내기 판정 글 · 하네스 사건 한 줄 · KST 시각.
import { describe, expect, test } from 'vitest';
import {
  callOutcomeLabel, callResultLine, callStatusLabel, CODE_LABEL, channelLabel, durationText, eventLine, eventSummary, hasPhone, kstDay, kstShort, kstTime,
  maskPhones, outcomeLabel, RULE_LABEL, senderTag, statusLabel, VERDICT_LABEL,
} from './labels';
import type { Message } from './outreachApi';

function msg(over: Partial<Message> = {}): Message {
  return {
    id: 1, direction: 'out', channel: 'sms', kind: 'normal', body: '가상 글', body_ko: null, has_media: false, origin: 'user',
    origin_name: '김공정', send_mode: 'manual', approved_by: null, status: 'delivered', fail_reason: null, fallback_sms: false,
    template_id: null, reply_to_id: null, activity: null, field_item_id: null, approval_id: null, chat: null, batch: null, events: [],
    scheduled_at: null, sent_at: null, delivered_at: null, created_at: '2026-11-23T08:30:00Z', ...over,
  };
}

describe('senderTag', () => {
  test('a person who sent it themselves', () => {
    expect(senderTag(msg())).toBe('[김공정 발신]');
  });
  test('an agent text a person approved names the approver', () => {
    expect(senderTag(msg({ origin: 'agent', origin_name: '에이전트', send_mode: 'approved', approved_by: '김공정' }))).toBe('[에이전트 발신] · 김공정 승인');
  });
  test('an agent text sent under delegation', () => {
    expect(senderTag(msg({ origin: 'agent', origin_name: '에이전트', send_mode: 'delegated' }))).toBe('[에이전트 발신 · 위임]');
  });
  test('a received text', () => {
    expect(senderTag(msg({ direction: 'in', origin: 'peer', origin_name: '박현장', send_mode: null, status: 'received' }))).toBe('[상대 발신]');
  });
  test('an agent draft nobody approved yet claims no approver', () => {
    expect(senderTag(msg({ origin: 'agent', origin_name: '에이전트', send_mode: null, approved_by: null, status: 'draft' }))).toBe('[에이전트 발신]');
  });
});

describe('statusLabel', () => {
  test('delivered and accepted', () => {
    expect(statusLabel(msg({ status: 'delivered' }))).toEqual({ text: '도착', tone: 'ok' });
    expect(statusLabel(msg({ status: 'accepted' }))).toEqual({ text: '접수', tone: 'info' });
  });
  test('failed carries the reason the server gave', () => {
    expect(statusLabel(msg({ status: 'failed', fail_reason: '제공사에 연결하지 못했습니다' }))).toEqual({ text: '실패 — 제공사에 연결하지 못했습니다', tone: 'bad' });
    expect(statusLabel(msg({ status: 'failed', fail_reason: null }))).toEqual({ text: '실패', tone: 'bad' });
  });
  test('kakao that went out as a text says so in front of the real state', () => {
    expect(statusLabel(msg({ status: 'delivered', fallback_sms: true })).text).toBe('카카오톡 실패 → 문자로 대신 보냄 · 도착');
    expect(statusLabel(msg({ status: 'accepted', fallback_sms: true }))).toEqual({ text: '카카오톡 실패 → 문자로 대신 보냄 · 접수', tone: 'info' });
    expect(statusLabel(msg({ status: 'unconfirmed', fallback_sms: true }))).toEqual({
      text: '카카오톡 실패 → 문자로 대신 보냄 · 확인 필요 — 보냈는지 알 수 없음', tone: 'warn',
    });
  });
  test('scheduled shows the time in KST', () => {
    expect(statusLabel(msg({ status: 'scheduled', scheduled_at: '2026-11-23T23:00:00Z' }))).toEqual({ text: '예약됨 11/24(화) 08:00', tone: 'info' });
  });
  test('test mode', () => {
    expect(statusLabel(msg({ status: 'blocked_test' }))).toEqual({ text: '시험 모드로 보내지 않음', tone: 'warn' });
  });
  test('unconfirmed is a warning of its own, never a failure and never a success', () => {
    const s = statusLabel(msg({ status: 'unconfirmed', fail_reason: '보냈는지 확인 필요' }));
    expect(s).toEqual({ text: '확인 필요 — 보냈는지 알 수 없음', tone: 'warn' });
    expect(s.text).not.toMatch(/실패|도착|접수/);
  });
  test('an automatic reply held by the after-check', () => {
    const held = msg({ status: 'draft', origin: 'agent', kind: 'auto_reply', fail_reason: '내용 확인 필요', events: [{ rule: 'held_for_review', verdict: 'blocked', detail: null }] });
    expect(statusLabel(held)).toEqual({ text: '확인 뒤 보내기', tone: 'warn' });
  });
  test('draft, sending, received, and a status this screen does not know', () => {
    expect(statusLabel(msg({ status: 'draft' }))).toEqual({ text: '아직 보내지 않음', tone: 'muted' });
    expect(statusLabel(msg({ status: 'sending' }))).toEqual({ text: '보내는 중', tone: 'muted' });
    expect(statusLabel(msg({ status: 'received', direction: 'in' }))).toEqual({ text: '받음', tone: 'muted' });
    expect(statusLabel(msg({ status: 'something_new' as never }))).toEqual({ text: '알 수 없는 상태(something_new)', tone: 'warn' });
  });
});

describe('outcomeLabel', () => {
  test('the three delivery results stay three', () => {
    expect(outcomeLabel({ code: 'accepted', message: '보냈습니다', scheduled_at: null })).toEqual({ text: '보냈습니다', tone: 'ok' });
    expect(outcomeLabel({ code: 'failed', message: '제공사에 연결하지 못했습니다', scheduled_at: null })).toEqual({ text: '실패 — 제공사에 연결하지 못했습니다', tone: 'bad' });
    expect(outcomeLabel({ code: 'unsure', message: '보냈는지 확인 필요', scheduled_at: null })).toEqual({ text: '확인 필요 — 보냈는지 알 수 없음', tone: 'warn' });
  });
  test('busy or duplicate is the server text, not a success', () => {
    const o = outcomeLabel({ code: 'duplicate', message: '이미 보내는 중이거나 잠시 뒤 다시 해 보세요', scheduled_at: null });
    expect(o).toEqual({ text: '이미 보내는 중이거나 잠시 뒤 다시 해 보세요', tone: 'warn' });
  });
  test('scheduled adds the KST time, the rest is the gate text as it is', () => {
    expect(outcomeLabel({ code: 'scheduled', message: '근무시간 밖이라 다음 근무 시작에 보냅니다', scheduled_at: '2026-11-24T08:00:00+09:00' })).toEqual({
      text: '근무시간 밖이라 다음 근무 시작에 보냅니다 · 11/24(화) 08:00', tone: 'info',
    });
    expect(outcomeLabel({ code: 'needs_approval', message: '사람의 승인이 필요합니다', scheduled_at: null })).toEqual({ text: '사람의 승인이 필요합니다', tone: 'warn' });
    expect(outcomeLabel({ code: 'blocked_test', message: '시험 모드라 허용한 번호에만 연락합니다', scheduled_at: null }).tone).toBe('warn');
  });
});

describe('events', () => {
  test('a line is the rule name from the table plus what the server recorded', () => {
    expect(eventLine({ rule: 'working_hours', verdict: 'blocked', detail: '근무시간 밖이라 다음 근무 시작에 보냅니다' })).toBe('근무시간 — 근무시간 밖이라 다음 근무 시작에 보냅니다');
    expect(eventLine({ rule: 'channel_choice', verdict: 'allowed', detail: 'sms' })).toBe('통로 고르기 — 문자');
    expect(eventLine({ rule: 'delivery_update', verdict: 'noted', detail: 'gave_up' })).toBe('뒤에 확인한 상태 — 결과 확인을 그만둠');
    expect(eventLine({ rule: 'kakao_not_ready', verdict: 'noted', detail: null })).toBe('카카오톡 준비 전');
  });
  test('a name the table does not have is shown as it is, not guessed', () => {
    expect(eventLine({ rule: 'brand_new_rule', verdict: 'noted', detail: '글' })).toBe('brand_new_rule — 글');
  });
  test('summary: a schedule made by working hours reads as one short line', () => {
    const m = msg({ status: 'scheduled', scheduled_at: '2026-11-22T23:00:00Z', events: [{ rule: 'working_hours', verdict: 'blocked', detail: '근무시간 밖이라 다음 근무 시작에 보냅니다' }] });
    expect(eventSummary(m)).toBe('근무시간 밖 → 월 08:00 예약');
  });
  test('summary: the latest note or block the status text does not already say, with the count', () => {
    const grace = msg({ events: [{ rule: 'reply_within_grace', verdict: 'noted', detail: '상대가 방금 보낸 문자의 답이라 근무시간 밖이어도 보냅니다' }, { rule: 'channel_choice', verdict: 'allowed', detail: 'sms' }, { rule: 'delivery', verdict: 'allowed', detail: '통로가 받았습니다' }] });
    expect(eventSummary(grace)).toBe('답 유예 — 상대가 방금 보낸 문자의 답이라 근무시간 밖이어도 보냅니다 · 기록 3건');
    const held = msg({ status: 'draft', fail_reason: '내용 확인 필요', events: [{ rule: 'unsupported_date', verdict: 'noted', detail: '도구 결과에 없는 날짜입니다' }, { rule: 'held_for_review', verdict: 'blocked', detail: '내용 확인 필요' }] });
    expect(eventSummary(held)).toBe('근거 없는 날짜 — 도구 결과에 없는 날짜입니다 · 기록 2건');
    expect(eventSummary(msg({ direction: 'in', status: 'received', events: [{ rule: 'admission', verdict: 'noted', detail: 'stop_word' }] }))).toBe('받기 판정 — 수신 거부 말');
  });
  test('summary: what the status chip already says is only counted', () => {
    const sent = msg({ events: [{ rule: 'channel_choice', verdict: 'allowed', detail: 'sms' }, { rule: 'delivery', verdict: 'allowed', detail: '통로가 받았습니다' }, { rule: 'delivery_update', verdict: 'noted', detail: 'delivered' }] });
    expect(eventSummary(sent)).toBe('처리 기록 3건');
    const failed = msg({ status: 'failed', fail_reason: '제공사에 연결하지 못했습니다', events: [{ rule: 'channel_choice', verdict: 'allowed', detail: 'sms' }, { rule: 'delivery', verdict: 'blocked', detail: '제공사에 연결하지 못했습니다' }] });
    expect(eventSummary(failed)).toBe('처리 기록 2건');
    const waiting = msg({ status: 'draft', fail_reason: '사람의 승인이 필요합니다', events: [{ rule: 'permission', verdict: 'blocked', detail: '사람의 승인이 필요합니다' }] });
    expect(eventSummary(waiting)).toBe('처리 기록 1건');
  });
  test('summary: only the latest attempt speaks — an older block is not repeated after a newer decision', () => {
    const retried = msg({
      status: 'draft', fail_reason: '알림 연결이 준비되지 않았습니다. 설정에서 연결을 확인해 주세요',
      events: [{ rule: 'permission', verdict: 'blocked', detail: '사람의 승인이 필요합니다' }, { rule: 'precheck', verdict: 'blocked', detail: '알림 연결이 준비되지 않았습니다. 설정에서 연결을 확인해 주세요' }],
    });
    expect(eventSummary(retried)).toBe('처리 기록 2건');
    const sentLater = msg({ status: 'accepted', events: [{ rule: 'working_hours', verdict: 'blocked', detail: '근무시간 밖이라 다음 근무 시작에 보냅니다' }, { rule: 'channel_choice', verdict: 'allowed', detail: 'sms' }, { rule: 'delivery', verdict: 'allowed', detail: '통로가 받았습니다' }] });
    expect(eventSummary(sentLater)).toBe('처리 기록 3건');
    expect(eventSummary(msg())).toBeNull();
  });
});

test('times are KST whatever the browser zone is', () => {
  expect(kstDay('2026-11-23T14:59:59Z')).toBe('2026년 11월 23일 월요일');
  expect(kstDay('2026-11-23T15:00:00Z')).toBe('2026년 11월 24일 화요일');
  expect(kstTime('2026-11-23T08:30:00Z')).toBe('17:30');
  expect(kstShort('2026-11-23T23:02:00Z')).toBe('11/24(화) 08:02');
  expect(channelLabel('kakao')).toBe('카카오톡');
  expect(channelLabel('sms')).toBe('문자');
});

describe('calls (Task 92)', () => {
  const row: Parameters<typeof callStatusLabel>[0] = { status: 'failed', events: [], fail_reason: '전화를 걸지 못했습니다', duration_s: null, scheduled_at: null };
  const unsure = { rule: 'delivery', verdict: 'noted', detail: '보냈는지 확인 필요', at: null };
  test('three outcomes stay three: failed, 「확인 필요」 and a call that went through', () => {
    expect(callStatusLabel(row)).toEqual({ text: '실패 — 전화를 걸지 못했습니다', tone: 'bad' });
    expect(callStatusLabel({ ...row, events: [unsure] })).toEqual({ text: '확인 필요 — 걸렸는지 알 수 없음', tone: 'warn' });
    expect(callStatusLabel({ ...row, status: 'completed', duration_s: 130 })).toEqual({ text: '통화 2분 10초', tone: 'ok' });
    expect(callOutcomeLabel({ code: 'unsure', message: '보냈는지 확인 필요', scheduled_at: null })).toEqual({ text: '확인 필요 — 걸렸는지 알 수 없음', tone: 'warn' });
    expect(callOutcomeLabel({ code: 'queued', message: '전화를 걸 차례에 넣었습니다', scheduled_at: null }).tone).toBe('ok');
  });
  test('durations', () => {
    expect([0, 45, 60, 130, 3600, 3700].map(durationText)).toEqual(['0초', '45초', '1분', '2분 10초', '1시간', '1시간 1분 40초']);
  });
  test('the result line says who proposed and who confirmed', () => {
    expect(callResultLine({ result_proposed: '', result_confirmed: null, confirmed_by: null })).toBeNull();
    expect(callResultLine({ result_proposed: '가능', result_confirmed: null, confirmed_by: null })).toBe('결과: 가능 (에이전트 제안 · 확정 전)');
    expect(callResultLine({ result_proposed: '가능', result_confirmed: '가능', confirmed_by: '김공정' })).toBe('결과: 가능 (에이전트 제안 · 김공정 확정)');
    expect(callResultLine({ result_proposed: '가능', result_confirmed: '토요일만', confirmed_by: '김공정' })).toBe('결과: 토요일만 (김공정 확정 · 에이전트 제안 「가능」)');
    expect(callResultLine({ result_proposed: '', result_confirmed: '토요일만', confirmed_by: '김공정' })).toBe('결과: 토요일만 (김공정 확정)');
  });
  test('phone-like numbers in a person’s text are hidden in the middle; dates and short numbers are left alone', () => {
    expect(maskPhones('010-0000-0199 · 010 0000 0198 · 01000000197 · 02-123-4567 · 0311234567')).toBe(
      '010-****-0199 · 010-****-0198 · 010-****-0197 · 02-****-4567 · 031-****-4567',
    );
    expect(maskPhones('11/30 08:00 · 2026-11-24 · A1210 · 6명')).toBe('11/30 08:00 · 2026-11-24 · A1210 · 6명');
    expect([hasPhone('010-0000-0199 로'), hasPhone('A1210 6명'), hasPhone('010-****-0199')]).toEqual([true, false, false]);
  });
  test('call events read with the console words for the call codes', () => {
    expect(eventLine({ rule: 'call_result', verdict: 'noted', detail: 'busy' })).toBe('통화 결과 — 통화 중');
    expect(eventLine({ rule: 'hangup_by_person', verdict: 'noted', detail: null })).toBe('사람이 끊음');
  });
});

// 개발 콘솔(서버)의 사건 이름표와 같은 낱말인지 — 파이썬 파일을 글로 읽는다. 파일 모양이 바뀌면 조용히 지나가지 않고 깨진다.
// 앞 폴더 밖이라 ?raw 로는 읽히지 않는다(vite 가 막음) — node 의 fs 로 읽는다(이 프로젝트에는 node 형 정의가 없어 꼴을 적어 둠).
const fsModule = 'node:fs';
const { readFileSync } = (await import(/* @vite-ignore */ fsModule)) as { readFileSync(path: URL, encoding: 'utf8'): string };
const here = import.meta.url; // new URL(글, import.meta.url) 꼴은 vite 가 자산으로 바꾸므로 변수로 둔다
const backend = (path: string) => readFileSync(new URL(`../../../../backend/${path}`, here), 'utf8');
const gateTypes = backend('app/outreach/harness/types.py');
const serverView = backend('app/programs/devconsole/outreach_view.py');

describe('the event words are the developer console’s (backend/app/programs/devconsole/outreach_view.py)', () => {
  const block = (src: string, start: RegExp, end: string) => {
    const at = src.search(start);
    expect(at, `${start} 를 서버 파일에서 찾지 못함`).toBeGreaterThanOrEqual(0);
    const stop = src.indexOf(end, at);
    expect(stop, `${start} 의 끝(${end})을 찾지 못함`).toBeGreaterThan(at);
    return src.slice(at, stop);
  };
  const pairs = (text: string) => Object.fromEntries([...text.matchAll(/"(\w+)":\s*"([^"]*)"/g)].map((m) => [m[1], m[2]]));

  const order = [...block(gateTypes, /^GATE_RULES: /m, '})').matchAll(/(\d+):\s*"(\w+)"/g)].sort((a, b) => Number(a[1]) - Number(b[1])).map((m) => m[2]);
  const orderText = [...block(serverView, /^ORDER_LABELS: /m, 'strict=True').matchAll(/"([^"]+)"/g)].map((m) => m[1]);
  const verdicts = pairs(block(serverView, /^VERDICT_LABELS = /m, '}'));
  const codes = pairs(block(serverView, /^CODE_TEXT = /m, '\n}'));

  test('the server tables were read', () => {
    expect(order).toHaveLength(8);
    expect(orderText).toHaveLength(order.length);
    expect(Object.keys(verdicts).sort()).toEqual(['allowed', 'blocked', 'noted']);
    expect(Object.keys(codes).length).toBeGreaterThanOrEqual(20);
  });
  test('gate rule names', () => {
    order.forEach((rule, i) => expect([rule, RULE_LABEL[rule]]).toEqual([rule, orderText[i]]));
  });
  test('verdicts', () => {
    expect(VERDICT_LABEL).toEqual(verdicts);
  });
  test('every code both tables have reads the same', () => {
    const shared = Object.values(CODE_LABEL).flatMap((t) => Object.entries(t)).filter(([code]) => code in codes);
    expect(shared.length).toBeGreaterThanOrEqual(15);
    for (const [code, text] of shared) expect([code, text]).toEqual([code, codes[code]]);
  });
});
