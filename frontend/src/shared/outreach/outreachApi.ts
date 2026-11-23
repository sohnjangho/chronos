// 메시지 API(Task 73, backend/app/programs/outreach/schemas.py) — 한 사람과의 대화 읽기, 초안 고치기·지우기, 보내기, 예약 취소,
// 다시 보내기. 연락처 창의 대화 칸과 대화 카드 등 다른 프로그램이 함께 쓴다. 응답에 전화번호 칸은 없다(연락처는 가린 꼴만).
// 보내기는 막힌 것도 결과라 늘 200 이고 outcome 이 무엇이 됐는지 말한다 — 화면은 그 글을 그대로 보이고, 줄의 상태는 다시 읽어 그린다.
import { api, ApiError } from '../api';

/** received 는 받은 줄. sending 은 내부 상태(잠깐). unconfirmed = 보냈는지 알 수 없음(자동으로 다시 보내지 않는다). */
export type MessageStatus = 'draft' | 'scheduled' | 'sending' | 'accepted' | 'delivered' | 'failed' | 'unconfirmed' | 'blocked_test' | 'received';
export type MessageChannel = 'sms' | 'kakao';

/** 하네스 사건 한 줄. detail 은 서버가 번호·비밀을 지운 글이거나 정해 둔 코드(rule 에 따라). */
export interface OutreachEvent {
  rule: string;
  verdict: string;
  detail: string | null;
}

export interface Message {
  id: number;
  direction: 'in' | 'out';
  channel: MessageChannel;
  kind: 'normal' | 'auto_reply' | 'notice' | 'dnc_confirm';
  /** 받은 줄은 서버가 번호를 가린 글. 늘 글로만 그린다(HTML 아님). */
  body: string;
  body_ko: string | null;
  has_media: boolean;
  origin: 'user' | 'agent' | 'peer';
  origin_name: string;
  send_mode: 'manual' | 'approved' | 'delegated' | null;
  /** 문이 보낼 때(예약할 때) 적는다. 고치기(PATCH)는 승인이 아니고, 예약을 취소하면 비워진다. */
  approved_by: string | null;
  status: MessageStatus;
  fail_reason: string | null;
  fallback_sms: boolean;
  template_id: number | null;
  reply_to_id: number | null;
  /** name 은 지금 버전의 작업 이름, 그 작업이 지금 버전에 없으면 null. */
  activity: { id: string; name: string | null } | null;
  field_item_id: number | null;
  approval_id: number | null;
  /** title 은 그 대화를 만든 사람에게만, 다른 사람에게는 빈 글. */
  chat: { id: number; title: string } | null;
  batch: { id: number; total: number; replied: number } | null;
  events: OutreachEvent[];
  /** 시각은 모두 UTC 를 붙인 ISO. */
  scheduled_at: string | null;
  sent_at: string | null;
  delivered_at: string | null;
  created_at: string;
}

/** 나가는 문의 판정 그대로. scheduled_at 은 예약됐을 때 그 시각(KST +09:00). */
export interface Outcome {
  code: string;
  message: string;
  scheduled_at: string | null;
}

export interface MessageResult {
  message: Message;
  /** 보내지 않았으면(초안만 만들었으면) null */
  outcome: Outcome | null;
}

export interface ResendOut {
  /** 같은 글의 새 초안 — 보내지 않았다. */
  message: Message;
  /** 옛 줄이 「확인 필요」였으면 「이미 나갔을 수 있습니다」 */
  warning: string | null;
}

/** 주소록 API 의 PersonBrief 와 같은 칸. */
export interface ContactBrief {
  id: number;
  name: string;
  role_title: string;
  company_id: number;
  phone_masked: string;
  has_phone: boolean;
  phone_kind: string | null;
  channels: string[];
  unread: number;
  do_not_contact: boolean;
  phone_invalid: boolean;
  last_line: string | null;
  hidden: boolean;
}

export interface Thread {
  contact: ContactBrief;
  /** 오래된 것부터 */
  messages: Message[];
  /** 더 앞의 메시지가 있음(before = messages[0].id 로 더 읽는다) */
  has_more: boolean;
}

export interface MessageIn {
  contact_id: number;
  channel: MessageChannel;
  body: string;
  template_id?: number;
  template_vars?: Record<string, string>;
  activity_id?: string;
  field_item_id?: number;
  approval_id?: number;
  send?: boolean;
}

/** [에이전트에게 초안 맡기기](Task 82): hint 는 담당자 요청(≤500자). 보내지 않는다 — 답은 새 초안 줄(origin agent). */
export interface AgentDraftIn {
  contact_id: number;
  channel: MessageChannel;
  activity_id?: string;
  hint?: string;
}

/** 보낸 칸만 바뀐다. null 로 비울 수 있는 것은 activity_id 뿐. */
export interface MessagePatch {
  body?: string;
  channel?: MessageChannel;
  activity_id?: string | null;
}

/** 보내기 요청(만들며 보내기·초안 보내기)이 나갔는지 모르는 실패인가: 답이 없음(연결 끊김, status 0) · 서버 오류(5xx) · 200 인데 몸을
 *  읽지 못함(bad_response — 줄이 만들어져 나간 뒤일 수도 있다). 이때 화면은 실패가 아니라 「확인하지 못했습니다」를 보이고 다시 읽는다. */
export const sendOutcomeUnknown = (e: unknown) =>
  e instanceof ApiError && (e.status === 0 || e.status >= 500 || e.code === 'bad_response');

const base = (sid: number) => `/api/schedules/${sid}/outreach`;
const post = (body?: unknown) => ({ method: 'POST', ...(body === undefined ? {} : { body: JSON.stringify(body) }) });

export const outreachApi = {
  /** 가장 새 것부터 limit 개(기본 50, 1..100). before 를 주면 그 id 보다 앞의 것. */
  thread: (sid: number, contactId: number, page: { before?: number; limit?: number } = {}) => {
    const q = new URLSearchParams();
    if (page.before !== undefined) q.set('before', String(page.before));
    if (page.limit !== undefined) q.set('limit', String(page.limit));
    const qs = q.toString();
    return api<Thread>(`${base(sid)}/threads/${contactId}${qs ? `?${qs}` : ''}`, { cache: 'no-store' });
  },
  /** 초안을 만든다. send 면 곧바로 문에 넣는다(outcome 이 온다). */
  create: (sid: number, body: MessageIn) => api<MessageResult>(`${base(sid)}/messages`, post(body)),
  /** 모델이 쓴 초안 줄을 만든다 — 보내지 않는다. 409 draft_busy(만드는 중)·do_not_contact 등, 503 draft_failed·llm_not_ready, 404. */
  agentDraft: (sid: number, body: AgentDraftIn) => api<Message>(`${base(sid)}/messages/agent-draft`, post(body)),
  /** 초안만(아니면 409 not_draft). 승인이 아니다. */
  patch: (sid: number, id: number, body: MessagePatch) => api<Message>(`${base(sid)}/messages/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  /** 초안만(아니면 409 not_draft). */
  remove: (sid: number, id: number) => api<void>(`${base(sid)}/messages/${id}`, { method: 'DELETE' }),
  /** 늘 200 + outcome. 끝난 줄은 409 not_sendable. */
  send: (sid: number, id: number) => api<MessageResult>(`${base(sid)}/messages/${id}/send`, post()),
  /** 예약 → 초안(승인한 사람도 비워진다). 예약이 아니면 409 not_scheduled. */
  cancel: (sid: number, id: number) => api<Message>(`${base(sid)}/messages/${id}/cancel`, post()),
  /** 실패·확인 필요 줄에서 같은 글의 새 초안을 만든다 — 보내지 않는다. 그 밖은 409 not_resendable. */
  resend: (sid: number, id: number) => api<ResendOut>(`${base(sid)}/messages/${id}/resend`, post()),
  /** 그 사람에게서 받은 글을 읽음으로(주소록 API, Task 72). */
  markRead: (sid: number, contactId: number) => api<{ read: number }>(`/api/schedules/${sid}/contacts/people/${contactId}/read`, post()),
};
