// 대화 줄 묶기(자정 KST) · 새로 읽은 쪽과 앞서 읽은 쪽 합치기 · 「요청에 대한 답」 한 줄.
import { expect, test } from 'vitest';
import type { Message } from '../../shared/outreach/outreachApi';
import { groupByDay, mergeNewest, prependOlder, replyLine } from './thread';
import { message } from './threadKit';

const at = (id: number, created_at: string, over: Partial<Message> = {}) => message({ id, created_at, ...over });

test('groupByDay: 23:59:59 and 00:00:00 KST fall on two days', () => {
  const groups = groupByDay([at(1, '2026-11-23T08:30:00Z'), at(2, '2026-11-23T14:59:59Z'), at(3, '2026-11-23T15:00:00Z')]);
  expect(groups.map((g) => g.day)).toEqual(['2026년 11월 23일 월요일', '2026년 11월 24일 화요일']);
  expect(groups.map((g) => g.items.map((m) => m.id))).toEqual([[1, 2], [3]]);
  expect(groupByDay([])).toEqual([]);
});

test('mergeNewest: the re-read window replaces what it covers, older pages stay, a deleted draft goes', () => {
  const prev = [at(1, '2026-11-20T01:00:00Z'), at(2, '2026-11-21T01:00:00Z'), at(3, '2026-11-22T01:00:00Z', { status: 'accepted' }), at(4, '2026-11-22T02:00:00Z', { status: 'draft' })];
  const fresh = [at(3, '2026-11-22T01:00:00Z', { status: 'delivered' }), at(5, '2026-11-23T01:00:00Z')];
  const merged = mergeNewest(prev, fresh);
  expect(merged.map((m) => m.id)).toEqual([1, 2, 3, 5]);
  expect(merged[2].status).toBe('delivered');
  expect(mergeNewest(prev, [])).toEqual([]);
});

test('prependOlder: only rows older than what is shown are added, once', () => {
  const shown = [at(5, '2026-11-23T01:00:00Z'), at(6, '2026-11-23T02:00:00Z')];
  expect(prependOlder(shown, [at(3, '2026-11-22T01:00:00Z'), at(4, '2026-11-22T02:00:00Z'), at(5, '2026-11-23T01:00:00Z')]).map((m) => m.id)).toEqual([3, 4, 5, 6]);
});

test('replyLine: names the request it answers', () => {
  const request = at(10, '2026-11-23T23:02:00Z', { activity: { id: 'A1210', name: '지상 골조' } });
  const answer = at(11, '2026-11-23T23:40:00Z', { direction: 'in', origin: 'peer', status: 'received', reply_to_id: 10 });
  expect(replyLine(answer, [request, answer])).toBe('↩ 11/24 A1210 지상 골조 요청에 대한 답');
  const plain = at(12, '2026-11-23T23:02:00Z');
  expect(replyLine({ ...answer, reply_to_id: 12 }, [plain, answer])).toBe('↩ 11/24 08:02 보낸 글에 대한 답');
  const auto = at(13, '2026-11-24T00:00:00Z', { origin: 'agent', kind: 'auto_reply', reply_to_id: 11 });
  expect(replyLine(auto, [answer, auto])).toBe('↩ 11/24 08:40 받은 글에 대한 답');
  expect(replyLine({ ...answer, reply_to_id: 2 }, [answer])).toBe('↩ 앞선 글에 대한 답');
  expect(replyLine(plain, [plain])).toBeNull();
});
