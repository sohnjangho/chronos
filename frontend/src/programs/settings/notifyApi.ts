import { api } from '../../shared/api';
import type { LlmError } from './model';

// 키·Account ID·번호는 요청 본문(JSON)에만 싣는다. 주소·기록·저장소에는 넣지 않는다.
const send = (method: string, body?: unknown): RequestInit => ({
  method,
  ...(body === undefined ? {} : { body: JSON.stringify(body) }),
});

const BASE = '/api/notify/connections';

/** 제공사 기본 주소(서버가 base_url 을 비우면 쓰는 값과 같다). */
export const KAT_BASE_URL = 'https://api.koreaaitel.com';

export type Permission = 'approve' | 'delegate';
export type PhoneKind = 'mobile' | 'landline' | 'internet' | 'rep' | 'safe' | 'tollfree';

/** 허용 번호 한 줄. 번호는 가린 꼴만 온다. 지울 때는 index 와 목록 판(allow_numbers_version)을 보낸다. */
export interface AllowNumber {
  index: number;
  number_masked: string;
  kind: PhoneKind;
  can_test_sms: boolean;
}

/** 서버의 알림 연결 한 줄(Task 70 계약 ConnectionOut). 키는 끝 4자리, Account ID·번호는 가린 꼴만. */
export interface NotifyConnection {
  id: number;
  name: string;
  provider: 'koreaaitel';
  base_url: string;
  secret_last4: string;
  account_id_masked: string;
  sender_number_masked: string | null;
  sender_index: number | null;
  senders: string[];
  kakao_channel: string | null;
  test_mode: boolean;
  allow_numbers: AllowNumber[];
  allow_numbers_version: string;
  /** 시험 문자가 갈 허용 번호의 index. 보낼 수 없으면 null. */
  test_sms_index: number | null;
  limits: Record<string, number>;
  agent_sms: Permission;
  agent_kakao: Permission;
  agent_call: Permission;
  inbound_mode: 'off' | 'known' | 'all';
  handoff_number_masked: string | null;
  is_default: boolean;
  status: 'ok' | 'failed' | 'unknown';
  checked_at: string | null;
  latency_ms: number | null;
  used_today: { sms: number; call: number };
}

/** 저장 결과. 이번에 부른 연결 테스트가 실패했으면 error 가 있다. */
export interface NotifySaved extends NotifyConnection {
  error: LlmError | null;
}

/** 연결 테스트 결과. 실패도 200 으로 오고 ok:false 와 error 가 있다. */
export interface NotifyProbe {
  ok: boolean;
  latency_ms: number | null;
  senders: string[];
  error: LlmError | null;
}

export type StepId = 'P1' | 'P2' | 'P3' | 'P4';

/** 진단 걸음 한 줄. detail·notes 는 서버가 가린 글. skipped 를 먼저 보고 그다음 ok. */
export interface DiagnosisStep {
  id: StepId;
  label: string;
  ok: boolean;
  skipped: boolean;
  detail: string;
  latency_ms: number | null;
  notes: string[];
}

export interface Diagnosis {
  ran_at: string;
  steps: DiagnosisStep[];
  /** 시험 문자가 제공사에 접수됨. */
  sent_real: boolean;
  /** 보냈는지 알 수 없음(보낸 뒤 끊김·시간 초과). */
  sent_unknown: boolean;
}

export interface NewNotifyConnection {
  name: string;
  base_url: string;
  secret: string;
  account_id: string;
}

export type NotifyPatch = Partial<{
  name: string;
  base_url: string;
  secret: string;
  account_id: string;
  sender_index: number;
  test_mode: boolean;
  allow_numbers_add: string[];
  allow_numbers_remove: number[];
  allow_numbers_version: string;
  agent_sms: Permission;
  agent_call: Permission;
}>;

export interface DiagnoseIn {
  steps?: StepId[];
  send: boolean;
}

/** 알림 연결(관리자만). 상한은 shared/outreach/limitsApi 의 길로만. */
export const notifyApi = {
  list: () => api<NotifyConnection[]>(BASE),
  create: (body: NewNotifyConnection) => api<NotifySaved>(BASE, send('POST', body)),
  update: (id: number, body: NotifyPatch) => api<NotifySaved>(`${BASE}/${id}`, send('PATCH', body)),
  remove: (id: number) => api<void>(`${BASE}/${id}`, send('DELETE')),
  /** 저장된 키로 다시 시험하고 결과를 연결에 적는다. */
  test: (id: number) => api<NotifyProbe>(`${BASE}/${id}/test`, send('POST')),
  diagnose: (id: number, body: DiagnoseIn) => api<Diagnosis>(`${BASE}/${id}/diagnose`, send('POST', body)),
  /** 마지막 진단. 아직 돌린 적이 없으면 null. */
  lastDiagnosis: (id: number) => api<Diagnosis | null>(`${BASE}/${id}/diagnosis`),
};
