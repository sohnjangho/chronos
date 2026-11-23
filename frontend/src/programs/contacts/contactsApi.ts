// 주소록 API(Task 72, backend/app/programs/contacts/schemas.py)와 알림 연결 상태(Task 70 GET /api/notify/status).
// 응답의 번호는 가린 꼴(phone_masked)뿐이다. 전체 번호는 reveal 한 곳에서만 오고, 부른 쪽(양식)만 잠깐 쥔다.
import { api } from '../../shared/api';

export type Channel = 'sms' | 'kakao' | 'call';
export type PhoneKind = 'mobile' | 'landline' | 'internet' | 'rep' | 'safe' | 'tollfree' | 'premium';
export type Gender = 'male' | 'female' | 'unknown';
export type Language = 'ko' | 'en' | 'zh' | 'vi';
export type VoiceMode = 'auto' | 'manual';

export interface Hours {
  /** 월=0 … 일=6 */
  days: number[];
  start: string;
  end: string;
}

export interface Company {
  id: number;
  name: string;
  trade: string;
  note: string;
  hidden: boolean;
}

export interface PersonBrief {
  id: number;
  name: string;
  role_title: string;
  company_id: number;
  /** 010-****-0199, 번호가 없으면 「번호 없음」 */
  phone_masked: string;
  has_phone: boolean;
  phone_kind: PhoneKind | null;
  channels: Channel[];
  unread: number;
  /** 번호 기준 — 다른 프로젝트에서 막은 번호도 켜져 온다. */
  do_not_contact: boolean;
  phone_invalid: boolean;
  last_line: string | null;
  hidden: boolean;
}

export interface PersonDetail extends PersonBrief {
  /** null = 프로젝트 기본 */
  hours: Hours | null;
  working_now: boolean;
  hours_label: string;
  gender: Gender;
  language: string;
  voice_mode: VoiceMode;
  voice_id: string | null;
  dnc_reason: string | null;
  note: string;
  linked_activities: { id: string; name: string }[];
}

export interface CompanyGroup extends Company {
  people: PersonBrief[];
}

export interface AddressBook {
  companies: CompanyGroup[];
  proposals_pending: number;
  reports_open: number;
}

/** 사람 만들기(POST) 본문. 채널 칸을 보내지 않으면 번호 종류가 정한다. */
export interface PersonBody {
  name?: string;
  role_title?: string;
  company_id?: number;
  phone?: string | null;
  can_sms?: boolean;
  can_kakao?: boolean;
  can_call?: boolean;
  hours?: Hours | null;
  gender?: Gender;
  language?: Language;
  voice_mode?: VoiceMode;
  voice_id?: string | null;
  do_not_contact?: boolean;
  dnc_reason?: string | null;
  note?: string;
  hidden?: boolean;
}

export interface CompanyBody {
  name?: string;
  trade?: string;
  note?: string;
  hidden?: boolean;
}

/** GET /api/notify/status(Task 70). 길이 없거나 실패하면 null — 화면은 「알림 연결 설정 전」. */
export interface NotifyStatus {
  ready: boolean;
  test_mode: boolean;
  allow_count: number;
  agent: { sms: string; kakao: string; call: string };
  inbound_mode: string;
  kakao_ready: boolean;
}

export const KIND_LABEL: Record<PhoneKind, string> = {
  mobile: '휴대전화',
  landline: '유선',
  internet: '인터넷전화',
  rep: '대표번호',
  safe: '안심번호',
  tollfree: '수신자 부담',
  premium: '정보이용료',
};

export const LANGUAGES: { key: Language; label: string }[] = [
  { key: 'ko', label: '한국어' },
  { key: 'en', label: '영어' },
  { key: 'zh', label: '중국어' },
  { key: 'vi', label: '베트남어' },
];

const base = (sid: number) => `/api/schedules/${sid}/contacts`;
const send = (method: string, body: unknown) => ({ method, body: JSON.stringify(body) });

export const getBook = (sid: number, includeHidden: boolean) =>
  api<AddressBook>(`${base(sid)}${includeHidden ? '?include_hidden=true' : ''}`);
export const getPerson = (sid: number, id: number) => api<PersonDetail>(`${base(sid)}/people/${id}`);
export const postPerson = (sid: number, body: PersonBody) => api<PersonDetail>(`${base(sid)}/people`, send('POST', body));
export const patchPerson = (sid: number, id: number, body: PersonBody) => api<PersonDetail>(`${base(sid)}/people/${id}`, send('PATCH', body));
export const postCompany = (sid: number, body: CompanyBody) => api<Company>(`${base(sid)}/companies`, send('POST', body));
export const patchCompany = (sid: number, id: number, body: CompanyBody) => api<Company>(`${base(sid)}/companies/${id}`, send('PATCH', body));
/** 전체 번호. 부른 쪽은 양식이 닫히면 잊는다(저장·URL·로그에 두지 않는다). 10분에 30번을 넘으면 429. */
export const revealPhone = (sid: number, id: number) =>
  api<{ phone: string | null }>(`${base(sid)}/people/${id}/reveal`, { method: 'POST', cache: 'no-store' });

export async function getNotifyStatus(): Promise<NotifyStatus | null> {
  try {
    const s = await api<NotifyStatus>('/api/notify/status');
    return s && typeof s.test_mode === 'boolean' ? s : null;
  } catch {
    return null;
  }
}
