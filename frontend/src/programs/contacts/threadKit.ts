// 대화 칸 시험 전용: 가상 메시지와, Task 73 계약 꼴로 답하는 가짜 메시지 API(상태를 쥐고 있어 보내기·취소·다시 보내기 뒤에
// 다시 읽으면 바뀐 줄이 온다). 주소록·알림 상태는 testKit 의 가짜가 그대로 답한다. 화면 코드는 이 파일을 import 하지 않는다.
import { vi } from 'vitest';
import type { Role } from '../../os/session';
import type { ContactBrief, Message, Outcome } from '../../shared/outreach/outreachApi';
import { json } from '../../test-helpers';
import { BOOK, stubContacts } from './testKit';

export function message(over: Partial<Message> = {}): Message {
  return {
    id: 1, direction: 'out', channel: 'sms', kind: 'normal', body: '가상 글', body_ko: null, has_media: false, origin: 'user',
    origin_name: '김공정', send_mode: 'manual', approved_by: null, status: 'delivered', fail_reason: null, fallback_sms: false,
    template_id: null, reply_to_id: null, activity: null, field_item_id: null, approval_id: null, chat: null, batch: null, events: [],
    scheduled_at: null, sent_at: null, delivered_at: null, created_at: '2026-11-23T08:30:00Z', ...over,
  };
}

export const received = (over: Partial<Message> = {}) =>
  message({ direction: 'in', origin: 'peer', origin_name: '박현장', send_mode: null, status: 'received', ...over });
export const agentDraft = (over: Partial<Message> = {}) =>
  message({ origin: 'agent', origin_name: '에이전트', send_mode: null, status: 'draft', chat: { id: 4, title: '주간 점검' }, ...over });

interface Call {
  method: string;
  url: string;
  body: unknown;
}
/** 다음 보내기의 판정과 그때 줄이 갖게 될 칸(문이 적는 것). */
interface SendScript {
  outcome: Outcome;
  row: Partial<Message>;
}

const ERR = {
  message: { code: 'not_found', message: '메시지를 찾을 수 없습니다.' },
  person: { code: 'not_found', message: '연락처를 찾을 수 없습니다.' },
  notDraft: { code: 'not_draft', message: '초안만 고치거나 지울 수 있습니다.' },
  notScheduled: { code: 'not_scheduled', message: '예약된 메시지가 아닙니다.' },
  notResendable: { code: 'not_resendable', message: '실패했거나 확인이 필요한 메시지만 다시 보낼 수 있습니다.' },
};

let threads: Map<number, Message[]>;
let unread: Map<number, number>;
let calls: Call[];
let sendQueue: SendScript[];
let failQueue: { test: (c: Call) => boolean; status: number; body: unknown }[];
let holds: { test: (c: Call) => boolean; gate: Promise<void> }[];
let nextId: number;
let userName: string;

const people = () => BOOK.companies.flatMap((c) => c.people);
const find = (id: number) => [...threads.values()].flat().find((m) => m.id === id);

function thread(contactId: number, query: URLSearchParams) {
  const person = people().find((p) => p.id === contactId);
  if (!person) return { status: 404, body: ERR.person };
  const all = threads.get(contactId) ?? [];
  const before = query.get('before');
  const limit = Number(query.get('limit') ?? 50);
  const older = before ? all.filter((m) => m.id < Number(before)) : all;
  const contact: ContactBrief = { ...person, unread: unread.get(contactId) ?? 0 };
  return { status: 200, body: { contact, messages: older.slice(-limit), has_more: older.length > limit } };
}

function send(m: Message) {
  if (!['draft', 'scheduled', 'sending'].includes(m.status))
    return { status: 409, body: { code: 'not_sendable', message: ['failed', 'unconfirmed'].includes(m.status) ? '이미 처리된 메시지입니다. 다시 보내려면 [다시 보내기]를 눌러 주세요.' : '이미 처리된 메시지입니다.' } };
  const script = sendQueue.shift() ?? {
    outcome: { code: 'accepted', message: '보냈습니다', scheduled_at: null },
    row: { status: 'accepted', sent_at: '2026-11-24T00:10:00Z', ...(m.origin === 'user' ? { send_mode: 'manual' as const } : { send_mode: 'approved' as const, approved_by: userName }) },
  };
  if (m.status !== 'sending' && (m.kind === 'auto_reply' || m.kind === 'notice')) m.kind = 'normal';
  Object.assign(m, script.row);
  return { status: 200, body: { message: m, outcome: script.outcome } };
}

function act(method: string, id: number, verb: string | undefined, body: unknown) {
  const m = find(id);
  if (!m) return { status: 404, body: ERR.message };
  if (verb === 'send') return send(m);
  if (verb === 'cancel') {
    if (m.status !== 'scheduled') return { status: 409, body: ERR.notScheduled };
    Object.assign(m, { status: 'draft', scheduled_at: null, send_mode: null, approved_by: null });
    return { status: 200, body: m };
  }
  if (verb === 'resend') {
    if (!['failed', 'unconfirmed'].includes(m.status)) return { status: 409, body: ERR.notResendable };
    const list = [...threads.entries()].find(([, rows]) => rows.includes(m))![1];
    const draft = message({ ...m, id: nextId++, status: 'draft', origin: 'user', origin_name: userName, send_mode: null, approved_by: null, fail_reason: null, kind: 'normal', events: [], chat: null, batch: null, sent_at: null, created_at: '2026-11-24T00:20:00Z' });
    list.push(draft);
    return { status: 200, body: { message: draft, warning: m.status === 'unconfirmed' ? '이미 나갔을 수 있습니다' : null } };
  }
  if (m.status !== 'draft') return { status: 409, body: ERR.notDraft };
  if (method === 'DELETE') {
    for (const rows of threads.values()) if (rows.includes(m)) rows.splice(rows.indexOf(m), 1);
    return { status: 204 };
  }
  Object.assign(m, body as Partial<Message>, m.kind === 'auto_reply' || m.kind === 'notice' ? { kind: 'normal' } : {});
  return { status: 200, body: m };
}

function route(c: Call): { status: number; body?: unknown } | null {
  const [path, qs = ''] = c.url.split('?');
  const read = /^\/api\/schedules\/1\/contacts\/people\/(\d+)\/read$/.exec(path);
  if (read) {
    const n = unread.get(Number(read[1])) ?? 0;
    unread.set(Number(read[1]), 0);
    return { status: 200, body: { read: n } };
  }
  const t = /^\/api\/schedules\/(\d+)\/outreach\/threads\/(\d+)$/.exec(path);
  if (t) return t[1] === '1' ? thread(Number(t[2]), new URLSearchParams(qs)) : { status: 404, body: ERR.person };
  const a = /^\/api\/schedules\/1\/outreach\/messages\/(\d+)(?:\/(send|cancel|resend))?$/.exec(path);
  if (a) return act(c.method, Number(a[1]), a[2], c.body);
  return null;
}

/** 로그인 + 주소록(testKit) + 일정 1의 가짜 메시지 API. rows 는 연락처 id → 그 사람의 메시지(오래된 것부터). */
export function stubThread(rows: Record<number, Message[]> = {}, role: Role = 'admin', name = '김하늘') {
  stubContacts(role);
  const inner = globalThis.fetch;
  threads = new Map(Object.entries(rows).map(([id, list]) => [Number(id), list.map((m) => ({ ...m }))]));
  unread = new Map();
  calls = [];
  sendQueue = [];
  failQueue = [];
  holds = [];
  nextId = 900;
  userName = name;
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const c: Call = { method: init?.method ?? 'GET', url: String(input), body: init?.body ? JSON.parse(String(init.body)) : undefined };
      if (!/\/outreach\/|\/read$/.test(c.url)) return inner(input, init);
      calls.push(c);
      const hold = holds.find((h) => h.test(c));
      if (hold) holds.splice(holds.indexOf(hold), 1);
      const fail = failQueue.find((f) => f.test(c));
      if (fail) failQueue.splice(failQueue.indexOf(fail), 1);
      // 서버는 요청을 받은 때에 처리하고 답을 그때의 모습으로 굳힌다 — 붙잡아 둔 답은 늦게 닿을 뿐이다(그 사이 줄이 바뀌어도 옛 모습).
      const r = fail ? null : (route(c) ?? { status: 404, body: { code: 'not_found', message: '찾을 수 없습니다.' } });
      const body = r ? JSON.stringify(r.body ?? {}) : '';
      if (hold) await hold.gate;
      if (fail?.status === 0) throw new TypeError('network');
      if (fail) return json(fail.status, fail.body);
      return r!.status === 204 ? new Response(null, { status: 204 }) : json(r!.status, JSON.parse(body));
    }),
  );
}

export const threadCalls = () => calls;
export const gets = (contactId = 1) => calls.filter((c) => c.method === 'GET' && c.url.includes(`/outreach/threads/${contactId}`));
export const acts = () => calls.filter((c) => c.method !== 'GET' && c.url.includes('/outreach/messages/'));
export const reads = () => calls.filter((c) => c.url.endsWith('/read'));
export const rowsOf = (contactId = 1) => threads.get(contactId) ?? [];
export const setUnread = (contactId: number, n: number) => void unread.set(contactId, n);
/** 서버 쪽에서 줄이 생김(상대가 답함·에이전트가 초안을 씀). */
export const arrive = (contactId: number, m: Message) => void (threads.get(contactId) ?? threads.set(contactId, []).get(contactId)!).push({ ...m });
/** 다음 보내기 하나의 판정과 줄의 새 칸. */
export const nextSend = (outcome: Outcome, row: Partial<Message>) => void sendQueue.push({ outcome, row });
/** 조건에 맞는 다음 요청 하나를 그 상태로 실패시킨다(0 = 연결 끊김). */
export const failNext = (test: (c: Call) => boolean, status: number, body: unknown = { code: 'http_error', message: '요청을 처리할 수 없습니다.' }) =>
  void failQueue.push({ test, status, body });
/** 조건에 맞는 다음 요청 하나를 붙잡아 둔다. 돌려준 함수를 부르면 답이 간다. */
export function holdNext(test: (c: Call) => boolean): () => void {
  let release!: () => void;
  holds.push({ test, gate: new Promise<void>((r) => (release = r)) });
  return release;
}
