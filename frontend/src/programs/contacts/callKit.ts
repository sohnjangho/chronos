// 통화 화면 시험 전용(Task 92): 가상 통화 줄과, Task 91 계약 꼴로 답하는 가짜 통화 API(상태를 쥐고 있어 걸기·예약·끊기·다시 걸기·
// 결과 확정 뒤에 다시 읽으면 바뀐 줄이 온다). 주소록·사람 자세히·알림 상태는 testKit 의 가짜가 그대로 답한다. 화면 코드는 이 파일을
// import 하지 않는다. 사람·번호는 모두 가상이다.
import { vi } from 'vitest';
import type { Role } from '../../os/session';
import type { Call, CallDetail, Outcome, TranscriptLine } from '../../shared/outreach/outreachApi';
import { json } from '../../test-helpers';
import { BOOK, stubContacts } from './testKit';

export function call(over: Partial<Call> = {}): Call {
  return {
    id: 1, direction: 'out', caller_class: 'outbound', contact: { id: 1, name: '박현장', role_title: '골조 팀장', company: '대한골조' },
    origin: 'agent', origin_name: '에이전트', send_mode: 'approved', approved_by: '김공정', status: 'completed', fail_reason: null,
    purpose: 'A1210 만회안 B 가능 여부 확인', questions: ['이번 주말 인원 투입 가능한지'], avoid: ['계약·금액'], language: 'ko', voice_id: null,
    duration_s: 130, summary_ko: '토요일 6명 가능, 일요일은 불가.', result_proposed: '조건부 가능', result_confirmed: null, confirmed_by: null,
    answers: [], events: [], has_recording: false, prev_call_id: null, activity: null, scheduled_at: null,
    started_at: '2026-11-24T05:15:00Z', ended_at: '2026-11-24T05:17:10Z', created_at: '2026-11-24T05:14:00Z', ...over,
  };
}

/** 사람이 쓴 초안(걸기 전). */
export const draftCall = (over: Partial<Call> = {}) =>
  call({ origin: 'user', origin_name: '김공정', send_mode: null, approved_by: null, status: 'draft', duration_s: null, summary_ko: '', result_proposed: '', started_at: null, ended_at: null, ...over });

interface Req {
  method: string;
  url: string;
  body: unknown;
  /** 받은 때(Date.now — 가짜 시계면 그 시각) */
  at: number;
}
type Reply = { status: number; body?: unknown };

const ERR = {
  call: { code: 'not_found', message: '통화를 찾을 수 없습니다.' },
  person: { code: 'not_found', message: '연락처를 찾을 수 없습니다.' },
  notDraft: { code: 'not_draft', message: '초안만 고치거나 지울 수 있습니다.' },
  notLive: { code: 'not_live', message: '진행 중인 통화가 아닙니다.' },
  notScheduled: { code: 'not_scheduled', message: '예약된 통화가 아닙니다.' },
  notSchedulable: { code: 'not_schedulable', message: '초안이거나 근무시간 밖이라 멈춘 통화만 예약할 수 있습니다.' },
  notRedialable: { code: 'not_redialable', message: '받지 않았거나 통화 중이었거나 실패한 통화만 다시 걸 수 있습니다.' },
  notCompleted: { code: 'not_completed', message: '통화가 끝난 뒤에만 결과를 확정할 수 있습니다.' },
  hasPhone: (field: string) => ({ code: 'has_phone', message: '전화번호는 넣을 수 없습니다 — 연락처에서 고릅니다', detail: { field } }),
};
/** 서버(hide_phones)처럼 번호가 든 글을 알아본다 — 이 가짜에서는 숫자 9자리 넘게 이어진 꼴만. */
const PHONE = /0\d{1,2}[-. )]?\d{3,4}[-. ]?\d{4}/;
function phoneField(body: Record<string, unknown> | undefined): string | null {
  for (const [field, v] of Object.entries(body ?? {})) if ((Array.isArray(v) ? v : [v]).some((x) => typeof x === 'string' && PHONE.test(x))) return field;
  return null;
}
const LIVE = ['queued', 'dialing', 'in_call'];

let rows: Call[];
let transcripts: Map<number, TranscriptLine[]>;
let reqs: Req[];
let placeQueue: { outcome: Outcome; row: Partial<Call> }[];
let failQueue: { test: (r: Req) => boolean; status: number; body: unknown }[];
let holds: { test: (r: Req) => boolean; gate: Promise<void> }[];
let onDetail: ((c: Call) => void) | null;
let personFails: boolean;
let nextId: number;
let userName: string;

const find = (id: number) => rows.find((c) => c.id === id);
const people = () => BOOK.companies.flatMap((c) => c.people);
const mode = (c: Call): Partial<Call> => (c.origin === 'user' ? { send_mode: 'manual', approved_by: null } : { send_mode: 'approved', approved_by: userName });

function place(c: Call): Reply {
  if (!['draft', 'scheduled', 'blocked_hours'].includes(c.status)) {
    const again = ['no_answer', 'busy', 'failed'].includes(c.status);
    return { status: 409, body: { code: 'not_sendable', message: again ? '이미 끝난 통화입니다. 다시 걸려면 [다시 걸기]를 눌러 주세요.' : '이미 처리된 통화입니다.' } };
  }
  const script = placeQueue.shift() ?? { outcome: { code: 'queued', message: '전화를 걸 차례에 넣었습니다', scheduled_at: null }, row: { status: 'queued' as const, ...mode(c) } };
  Object.assign(c, script.row);
  return { status: 200, body: { call: { ...c }, outcome: script.outcome } };
}

function act(method: string, c: Call, verb: string | undefined, body: Record<string, unknown> | undefined): Reply {
  switch (verb) {
    case 'place':
      return place(c);
    case 'schedule':
      if (!['draft', 'blocked_hours', 'scheduled'].includes(c.status)) return { status: 409, body: ERR.notSchedulable };
      Object.assign(c, { status: 'scheduled', scheduled_at: String(body?.at), fail_reason: null, ...mode(c) });
      return { status: 200, body: { ...c } };
    case 'cancel':
      if (c.status !== 'scheduled') return { status: 409, body: ERR.notScheduled };
      Object.assign(c, { status: 'draft', scheduled_at: null, send_mode: null, approved_by: null });
      return { status: 200, body: { ...c } };
    case 'hangup':
      return LIVE.includes(c.status) ? { status: 200, body: { ...c } } : { status: 409, body: ERR.notLive };
    case 'redial': {
      if (!['no_answer', 'busy', 'failed'].includes(c.status)) return { status: 409, body: ERR.notRedialable };
      // 서버처럼 내용·작업·언어·음성만 옮기고 방식·승인·결과·요약은 옮기지 않는다.
      const fresh = draftCall({
        contact: c.contact, purpose: c.purpose, questions: [...c.questions], avoid: [...c.avoid], language: c.language, voice_id: c.voice_id, activity: c.activity,
        id: nextId++, origin_name: userName, created_at: '2026-11-24T06:00:00Z',
      });
      rows.push(fresh);
      return { status: 200, body: { ...fresh } };
    }
    case 'confirm':
      if (phoneField(body)) return { status: 422, body: ERR.hasPhone('result') };
      if (c.status !== 'completed') return { status: 409, body: ERR.notCompleted };
      Object.assign(c, { result_confirmed: String(body?.result), confirmed_by: userName });
      return { status: 200, body: { ...c } };
    case 'recording':
      return c.has_recording ? { status: 200, body: 'RIFF' } : { status: 404, body: ERR.call };
  }
  if (method === 'GET') {
    onDetail?.(c);
    const detail: CallDetail = { ...c, transcript: [...(transcripts.get(c.id) ?? [])], reports: [] };
    return { status: 200, body: detail };
  }
  if (method === 'PATCH' && phoneField(body)) return { status: 422, body: ERR.hasPhone(phoneField(body)!) };
  if (c.status !== 'draft') return { status: 409, body: ERR.notDraft };
  if (method === 'DELETE') {
    rows.splice(rows.indexOf(c), 1);
    return { status: 204 };
  }
  Object.assign(c, body);
  return { status: 200, body: { ...c } };
}

function route(r: Req): Reply | null {
  const [path, qs = ''] = r.url.split('?');
  if (path === '/api/schedules/1/outreach/calls') {
    if (r.method === 'POST') {
      const b = r.body as { contact_id: number; purpose: string; questions?: string[]; avoid?: string[]; activity_id?: string; language?: string };
      const bad = phoneField(r.body as Record<string, unknown>);
      if (bad) return { status: 422, body: ERR.hasPhone(bad) };
      const p = people().find((x) => x.id === b.contact_id);
      if (!p) return { status: 404, body: ERR.person };
      const made = draftCall({
        id: nextId++, origin_name: userName, contact: { id: p.id, name: p.name, role_title: p.role_title, company: '대한골조' }, purpose: b.purpose,
        questions: b.questions ?? [], avoid: b.avoid ?? [], language: b.language ?? 'ko', activity: b.activity_id ? { id: b.activity_id, name: null } : null,
        created_at: '2026-11-24T06:00:00Z',
      });
      rows.push(made);
      return { status: 200, body: { ...made } };
    }
    const who = Number(new URLSearchParams(qs).get('contact_id'));
    return { status: 200, body: rows.filter((c) => c.contact?.id === who).sort((a, b) => b.id - a.id).map((c) => ({ ...c })) };
  }
  const m = /^\/api\/schedules\/1\/outreach\/calls\/(\d+)(?:\/(place|schedule|cancel|hangup|redial|confirm|recording))?$/.exec(path);
  if (!m) return null;
  const c = find(Number(m[1]));
  return c ? act(r.method, c, m[2], r.body as Record<string, unknown> | undefined) : { status: 404, body: ERR.call };
}

/** 로그인 + 주소록(testKit) + 일정 1의 가짜 통화 API. list 는 통화 줄들(차례 상관없음 — 목록은 최근 것부터 준다). */
export function stubCalls(list: Call[] = [], role: Role = 'admin', name = '김하늘') {
  stubContacts(role);
  const inner = globalThis.fetch;
  rows = list.map((c) => ({ ...c }));
  transcripts = new Map();
  reqs = [];
  placeQueue = [];
  failQueue = [];
  holds = [];
  onDetail = null;
  personFails = false;
  nextId = 900;
  userName = name;
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const r: Req = { method: init?.method ?? 'GET', url: String(input), body: init?.body ? JSON.parse(String(init.body)) : undefined, at: Date.now() };
      if (personFails && (init?.method ?? 'GET') === 'GET' && /\/contacts\/people\/\d+$/.test(r.url)) return json(500, { code: 'http_error', message: '요청을 처리할 수 없습니다.' });
      if (!r.url.includes('/outreach/calls')) return inner(input, init);
      reqs.push(r);
      const hold = holds.find((h) => h.test(r));
      if (hold) holds.splice(holds.indexOf(hold), 1);
      const fail = failQueue.find((f) => f.test(r));
      if (fail) failQueue.splice(failQueue.indexOf(fail), 1);
      // 서버는 받은 때에 처리하고 답을 그때의 모습으로 굳힌다 — 붙잡아 둔 답은 늦게 닿을 뿐이다.
      const reply = fail ? null : (route(r) ?? { status: 404, body: { code: 'not_found', message: '찾을 수 없습니다.' } });
      const text = reply ? JSON.stringify(reply.body ?? {}) : '';
      if (hold) await hold.gate;
      if (fail?.status === 0) throw new TypeError('network');
      if (fail) return json(fail.status, fail.body);
      if (reply!.status === 204) return new Response(null, { status: 204 });
      if (r.url.endsWith('/recording') && reply!.status === 200) return new Response(new Blob(['RIFF'], { type: 'audio/wav' }), { status: 200 });
      return json(reply!.status, JSON.parse(text));
    }),
  );
}

export const callReqs = () => reqs;
export const callPosts = (verb?: string) => reqs.filter((r) => r.method !== 'GET' && (verb === undefined || r.url.endsWith(`/${verb}`)));
export const callGets = (id?: number) => reqs.filter((r) => r.method === 'GET' && (id === undefined ? true : r.url.endsWith(`/calls/${id}`)));
export const rowOf = (id: number) => find(id);
/** 서버 쪽에서 줄이 바뀜(일꾼이 상태를 적음). */
export const change = (id: number, over: Partial<Call>) => void Object.assign(find(id)!, over);
/** 받아쓰기 줄을 정함 / 한 줄 더함(통화가 이어짐). */
export const setTranscript = (id: number, lines: TranscriptLine[]) => void transcripts.set(id, lines.map((l) => ({ ...l })));
export const speak = (id: number, line: TranscriptLine) => void (transcripts.get(id) ?? transcripts.set(id, []).get(id)!).push({ ...line });
/** 자세히 읽기마다 부른다(그때 줄을 바꿔 통화가 흘러가게). */
export const onEveryDetail = (f: ((c: Call) => void) | null) => void (onDetail = f);
/** 사람 자세히(근무시간·음성) 읽기가 실패한다. */
export const failPerson = () => void (personFails = true);
/** 다음 [전화 걸기] 하나의 판정과 줄의 새 칸. */
export const nextPlace = (outcome: Outcome, row: Partial<Call>) => void placeQueue.push({ outcome, row });
/** 조건에 맞는 다음 요청 하나를 그 상태로 실패시킨다(0 = 연결 끊김). */
export const failCall = (test: (r: Req) => boolean, status: number, body: unknown = { code: 'http_error', message: '요청을 처리할 수 없습니다.' }) =>
  void failQueue.push({ test, status, body });
/** 조건에 맞는 다음 요청 하나를 붙잡아 둔다. 돌려준 함수를 부르면 답이 간다. */
export function holdCall(test: (r: Req) => boolean): () => void {
  let release!: () => void;
  holds.push({ test, gate: new Promise<void>((res) => (release = res)) });
  return release;
}
