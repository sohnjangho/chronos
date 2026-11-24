// 개발 콘솔의 연락 기록 낱말(Task 96 후속): 같은 줄은 연락처 화면(shared/outreach/labels.ts)과 같은 글로 읽힌다 — 등급·통화 상태·
// 문자 상태가 한 곳(labels)에서 온다. 콘솔에만 있는 등급(차단·시험 모드 밖·우리가 먼저 연락)만 여기 따로.
import { describe, expect, test } from 'vitest';
import { CALL_UNSURE_TEXT, CALLER_CLASS_LABEL, UNSURE_TEXT } from '../../shared/outreach/labels';
import type { OutreachRow } from './devApi';
import { classOf, rowStatusOf } from './outreachText';

const row = (over: Partial<OutreachRow>): OutreachRow => ({
  kind: 'call', id: 1, at: '2026-11-24T05:00:00Z', direction: 'out', channel: 'call', origin: 'agent', origin_name: '에이전트', send_mode: 'approved',
  caller_class: 'outbound', status: 'completed', contact_name: '박현장', company_name: '대한골조', number_masked: '010-****-0101', schedule_name: '5층',
  events: 0, needs_check: false, ...over,
});

describe('the console reads like the contacts screen', () => {
  test('caller classes are the shared words; console-only classes keep their own', () => {
    for (const [cls, word] of Object.entries(CALLER_CLASS_LABEL)) expect(classOf(cls)).toBe(word);
    expect([classOf('blocked'), classOf('outside_test'), classOf('outbound'), classOf(null), classOf('new_class')]).toEqual(['차단', '시험 모드 밖', '우리가 먼저 연락', '—', 'new_class']);
  });

  test('call statuses are the call card’s words and tones; the unknown outcome stays amber', () => {
    const words = (over: Partial<OutreachRow>) => rowStatusOf(row(over));
    expect(words({ status: 'completed' })).toEqual({ label: '통화함', tone: 'success' });
    expect(words({ status: 'in_call' })).toEqual({ label: '통화 중', tone: 'info' });
    expect(words({ status: 'queued' })).toEqual({ label: '걸 차례를 기다리는 중', tone: 'info' });
    expect(words({ status: 'busy' })).toEqual({ label: '상대 통화 중', tone: 'warning' });
    expect(words({ status: 'failed' })).toEqual({ label: '실패', tone: 'danger' });
    expect(words({ status: 'failed', needs_check: true })).toEqual({ label: CALL_UNSURE_TEXT, tone: 'warning' });
    expect(words({ direction: 'in', caller_class: 'shared', status: 'missed' })).toEqual({ label: '부재중', tone: 'warning' });
    expect(words({ direction: 'in', caller_class: 'unknown', status: 'rejected' })).toEqual({ label: '받지 않음', tone: 'neutral' });
    expect(words({ direction: 'in', status: 'dialing' })).toEqual({ label: '받는 중', tone: 'info' });
  });

  test('message statuses are the bubble’s words', () => {
    const words = (status: string) => rowStatusOf(row({ kind: 'message', channel: 'sms', status })).label;
    expect(['delivered', 'accepted', 'failed', 'unconfirmed', 'blocked_test', 'sending', 'received', 'draft'].map(words)).toEqual([
      '도착', '접수', '실패', UNSURE_TEXT, '시험 모드로 보내지 않음', '보내는 중', '받음', '아직 보내지 않음',
    ]);
  });

  test('the head of a call row with its duration reads 「통화 n분」 like the card', () => {
    expect(rowStatusOf({ ...row({ status: 'completed' }), duration_s: 95 }).label).toBe('통화 1분 35초');
  });
});
