// 다른 화면에서 연락 시작하기(Task 104) — 미리 채우는 문자 글. 카카오톡이 잠겨 있는 동안 문안 대신 같은 뜻의 문자 글이고, 작업 이름·날짜는
// 현장 항목·승인 건 자료에서 코드가 채운다. 채운 값에 보이지 않는 글자가 있어도 서버 검사(invalid_text)에 걸리지 않게 지운다. 자료는 가상.
import { expect, test } from 'vitest';
import { approvalText, checkinText, cleanValue, dayKo, handoffText, pollText } from './contactKit';

// 서버(app/programs/outreach/service.py _HIDDEN·Cc)가 막는 글자
// eslint-disable-next-line no-control-regex
const HIDDEN = /[\u0000-\u0008\u000B-\u001F\u007F-\u009F\u200B\u200E\u200F\u061C\u2028\u2029\u202A-\u202E\u2066-\u2069]/;

test('dayKo reads a date or a UTC time as the KST calendar day', () => {
  expect(dayKo('2026-11-30')).toBe('11월 30일');
  expect(dayKo('2026-11-29T16:30:00Z')).toBe('11월 30일'); // KST 01:30
  expect(dayKo(null)).toBe('');
  expect(dayKo('엉뚱한 값')).toBe('');
});

test('check-in text names the site, the day and the work from the field item', () => {
  expect(checkinText({ activity_name: '3층 슬래브 타설', created_at: '2026-11-30T00:10:00Z' }, '가람현장')).toBe(
    '[크로노스] 가람현장 11월 30일 3층 슬래브 타설 체크인 부탁드립니다(인원·시작 시각·막히는 점). 이 번호로 답 문자 주세요.',
  );
});

test('hand-off text uses the successor start day and the days left', () => {
  expect(handoffText({ activity_name: '기초 거푸집', payload_json: { succ_start: '2026-12-03', days_left: 3 } })).toBe(
    '[크로노스] 기초 거푸집 시작 3일 전입니다(12월 3일). 자재·장비·인력 준비 상태를 이 번호로 답 문자 주세요.',
  );
  // 시작일을 모르면 괄호를 빼고, 남은 날을 모르면 3일
  expect(handoffText({ activity_name: '기초 거푸집', payload_json: {} })).toBe(
    '[크로노스] 기초 거푸집 시작 3일 전입니다. 자재·장비·인력 준비 상태를 이 번호로 답 문자 주세요.',
  );
});

test('poll text carries the question', () => {
  expect(pollText({ activity_name: '외장 패널', prompt_text: '주말 병행 투입이 가능한지 의견을 주세요.' }, '가람현장')).toBe(
    '[크로노스] 가람현장 외장 패널 만회안 의견을 여쭙니다 — 주말 병행 투입이 가능한지 의견을 주세요. 이 번호로 답 문자 주세요.',
  );
});

test('approval text names the waiting item and the day it was raised', () => {
  expect(approvalText({ title: '만회안 B 반영 — 크레인 2대', created_at: '2026-11-24T03:00:00Z' })).toBe(
    '[크로노스] 승인을 기다리는 건이 있습니다: 만회안 B 반영 — 크레인 2대(11월 24일). 승인함에서 확인해 주세요. 문의는 이 번호로 문자 주세요.',
  );
});

test('filled values lose hidden and direction characters and stay short, so the server text check passes', () => {
  const nasty = '타설\u202E\u0007\u200B\u2066 작업\n둘째 줄';
  expect(cleanValue(nasty)).toBe('타설 작업 둘째 줄');
  expect(cleanValue('가'.repeat(300)).length).toBeLessThanOrEqual(80);
  for (const text of [
    checkinText({ activity_name: nasty, created_at: '2026-11-30T00:00:00Z' }, `현장\u202E`),
    handoffText({ activity_name: nasty, payload_json: { succ_start: '2026-12-03' } }),
    pollText({ activity_name: nasty, prompt_text: `질문\u2028${'긴'.repeat(900)}` }, '현장'),
    approvalText({ title: nasty, created_at: '2026-11-24T03:00:00Z' }),
  ]) {
    expect(text).not.toMatch(HIDDEN);
    expect(text.length).toBeLessThanOrEqual(1000);
  }
});
