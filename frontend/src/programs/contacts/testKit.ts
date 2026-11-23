// 연락처 시험 전용 도우미: 가상 주소록(5층 사무동 신축 · 대한골조·한빛전기·우리설비)과 가짜 주소록·알림 상태 API.
// 화면 코드는 이 파일을 import 하지 않는다. 사람·회사·번호는 모두 가상이다(010-0000-0000 꼴).
import { vi } from 'vitest';
import type { Role } from '../../os/session';
import { json, signInAsDemo } from '../../test-helpers';
import type { AddressBook, CompanyGroup, NotifyStatus, PersonBrief, PersonDetail } from './contactsApi';

export function person(over: Partial<PersonBrief> = {}): PersonBrief {
  return {
    id: 1, name: '박현장', role_title: '골조 팀장', company_id: 10, phone_masked: '010-****-0000', has_phone: true,
    phone_kind: 'mobile', channels: ['sms', 'kakao', 'call'], unread: 1, do_not_contact: false, phone_invalid: false,
    last_line: '정상 진행 중입니다.', hidden: false, ...over,
  };
}

export const PARK = person();
export const CHOI = person({ id: 2, name: '최반장', role_title: '골조 반장', phone_masked: '번호 없음', has_phone: false, phone_kind: null, channels: [], unread: 0, last_line: null });
export const LEE = person({ id: 3, name: '이전기', role_title: '전기 과장', company_id: 20, phone_masked: '02-****-0000', phone_kind: 'landline', channels: ['call'], unread: 0 });
export const JUNG = person({ id: 4, name: '정배선', role_title: '전기 기사', company_id: 20, phone_masked: '010-****-0001', do_not_contact: true, unread: 0 });
export const KIM = person({ id: 5, name: '김설비', role_title: '설비 소장', company_id: 30, phone_masked: '1588-****', phone_kind: 'rep', channels: ['call'], unread: 0, phone_invalid: true });

const group = (id: number, name: string, trade: string, people: PersonBrief[]): CompanyGroup => ({ id, name, trade, note: '', hidden: false, people });

export const BOOK: AddressBook = {
  companies: [group(10, '대한골조', '골조', [PARK, CHOI]), group(20, '한빛전기', '전기', [LEE, JUNG]), group(30, '우리설비', '설비', [KIM])],
  proposals_pending: 0,
  reports_open: 0,
};

export const EMPTY: AddressBook = { companies: [], proposals_pending: 0, reports_open: 0 };

/** 협력사 8곳에 사람 50명(긴 이름·번호 없음·수신 거부·대표번호 섞음). */
export function bigBook(): AddressBook {
  const companies: CompanyGroup[] = [];
  let id = 100;
  for (let c = 0; c < 8; c++) {
    const people: PersonBrief[] = [];
    const n = c < 2 ? 7 : 6;
    for (let i = 0; i < n; i++) {
      id += 1;
      people.push(
        person({
          id, company_id: 1000 + c, unread: i % 4 === 0 ? 12 : 0,
          name: i === 0 ? `아주아주긴이름을가진가상의현장담당자${c}` : `가상${c}-${i}`,
          role_title: i === 1 ? '전기·통신·소방 설비 총괄 현장 대리인 겸 안전 관리 책임자' : '반장',
          ...(i === 2 ? { has_phone: false, phone_masked: '번호 없음', phone_kind: null, channels: [] } : {}),
          ...(i === 3 ? { do_not_contact: true } : {}),
          ...(i === 4 ? { phone_kind: 'rep', phone_masked: '1588-****', channels: ['call'] } : {}),
        }),
      );
    }
    companies.push(group(1000 + c, c === 0 ? '아주긴이름의가상협력사주식회사건설기계설비' : `가상협력사${c}`, '공종', people));
  }
  return { companies, proposals_pending: 0, reports_open: 0 };
}

export function detail(p: PersonBrief, over: Partial<PersonDetail> = {}): PersonDetail {
  return {
    ...p, hours: null, working_now: true, hours_label: '근무 중 · 18:00 까지', gender: 'unknown', language: 'ko', voice_mode: 'auto',
    voice_id: null, dnc_reason: null, note: '', linked_activities: [], ...over,
  };
}

export const STATUS: NotifyStatus = {
  ready: true, test_mode: true, allow_count: 1, agent: { sms: 'approve', kakao: 'approve', call: 'approve' }, inbound_mode: 'off', kakao_ready: false,
};

type Reply = { status: number; body?: unknown };
interface Call {
  method: string;
  url: string;
  body: unknown;
}

let book: Reply;
let status: Reply;
let details: Map<number, PersonDetail>;
let revealReply: Reply;
let writeQueue: Reply[];
let calls: Call[];

const SID = '/api/schedules/1/contacts';

function route(method: string, url: string): Reply {
  if (url === '/api/notify/status') return status;
  if (method === 'GET' && (url === SID || url.startsWith(`${SID}?`))) return book;
  // 다른 일정(프로젝트를 바꾼 뒤)의 주소록은 비어 있다.
  if (method === 'GET' && /^\/api\/schedules\/\d+\/contacts(\?.*)?$/.test(url)) return { status: 200, body: EMPTY };
  const reveal = /\/people\/(\d+)\/reveal$/.exec(url);
  if (reveal) return revealReply;
  const one = /\/people\/(\d+)$/.exec(url);
  if (method === 'GET' && one) {
    const d = details.get(Number(one[1]));
    return d ? { status: 200, body: d } : { status: 404, body: { code: 'not_found', message: '찾을 수 없습니다.' } };
  }
  // 대화 칸(Task 78)이 읽는 대화 — 이 가짜에서는 늘 비어 있다(아래 쓰기 응답 줄을 먹지 않게 여기서 답한다). 대화 시험은 threadKit.
  const thread = /\/outreach\/threads\/(\d+)/.exec(url);
  if (method === 'GET' && thread) {
    const contact = BOOK.companies.flatMap((c) => c.people).find((p) => p.id === Number(thread[1])) ?? person({ id: Number(thread[1]) });
    return { status: 200, body: { contact: { ...contact, unread: 0 }, messages: [], has_more: false } };
  }
  const queued = writeQueue.shift();
  if (queued) return queued;
  if (one) return { status: 200, body: details.get(Number(one[1])) };
  if (url.endsWith('/people')) return { status: 201, body: detail(person({ id: 99 })) };
  if (url.endsWith('/companies')) return { status: 201, body: { id: 77, name: '새협력사', trade: '', note: '', hidden: false } };
  return { status: 200, body: {} };
}

/** 로그인(기본 관리자) + 일정 1의 가짜 주소록 API. */
export function stubContacts(role: Role = 'admin') {
  signInAsDemo(role);
  book = { status: 200, body: BOOK };
  status = { status: 200, body: STATUS };
  details = new Map([PARK, CHOI, LEE, JUNG, KIM].map((p) => [p.id, detail(p)]));
  details.set(JUNG.id, detail(JUNG, { dnc_reason: '본인 요청' }));
  revealReply = { status: 200, body: { phone: '010-0000-0000' } };
  writeQueue = [];
  calls = [];
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? 'GET';
      calls.push({ method, url, body: init?.body ? JSON.parse(String(init.body)) : undefined });
      const r = route(method, url);
      return Promise.resolve(json(r.status, r.body ?? {}));
    }),
  );
}

export const mockBook = (b: AddressBook) => void (book = { status: 200, body: b });
export const mockStatus = (s: NotifyStatus | null, code = 200) => void (status = { status: code, body: s ?? { code: 'not_found', message: '찾을 수 없습니다.' } });
export const mockDetail = (d: PersonDetail) => void details.set(d.id, d);
export const mockReveal = (code: number, body: unknown) => void (revealReply = { status: code, body });
/** 다음 쓰기(POST·PATCH) 하나의 응답. */
export const mockWrite = (code: number, body: unknown) => void writeQueue.push({ status: code, body });
export const contactCalls = () => calls;
export const writes = () => calls.filter((c) => c.method !== 'GET' && !c.url.endsWith('/reveal'));
export const lastWrite = () => writes().at(-1);
export const reveals = () => calls.filter((c) => c.url.endsWith('/reveal'));
