import { api } from '../../shared/api';
import type { LlmError } from './model';

// 키·Account ID·번호는 요청 본문(JSON)에만 싣는다. 주소·기록·저장소에는 넣지 않는다.
export const send = (method: string, body?: unknown, signal?: AbortSignal): RequestInit => ({
  method,
  ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  ...(signal ? { signal } : {}),
});

export const BASE = '/api/notify/connections';

/** 제공사 기본 주소(서버가 base_url 을 비우면 쓰는 값과 같다). */
export const KAT_BASE_URL = 'https://api.koreaaitel.com';

export type Permission = 'approve' | 'delegate';
export type PhoneKind = 'mobile' | 'landline' | 'internet' | 'rep' | 'safe' | 'tollfree';

/** 허용 번호 한 줄. 번호는 가린 꼴만 온다. 지울 때는 index 와 목록 판(allow_numbers_version)을 보낸다. */
export interface AllowNumber {
  index: number;
  number_masked: string;
  /** 번호 종류를 알 수 없으면 "". */
  kind: PhoneKind | '';
  can_test_sms: boolean;
}

/** 승인된 발신번호 하나. label 은 「발신번호 n」(제공사 목록 차례 — 끝 4자리가 같아도 가를 수 있게). */
export interface Sender {
  index: number;
  number_masked: string;
  kind: PhoneKind | '';
  label: string;
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
  senders: Sender[];
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
  /** 오늘(서울) 나간 문자·전화. 기본 연결이 아니면 null. */
  used_today: { sms: number; call: number } | null;
}

/** 저장 결과. 이번에 부른 연결 테스트가 실패했으면 error 가 있다. */
export interface NotifySaved extends NotifyConnection {
  error: LlmError | null;
}

/** 연결 테스트 결과. 실패도 200 으로 오고 ok:false 와 error 가 있다. */
export interface NotifyProbe {
  ok: boolean;
  latency_ms: number | null;
  senders: Sender[];
  error: LlmError | null;
}

export type StepId = 'P1' | 'P2' | 'P3' | 'P4';

/** 진단 걸음 한 줄. label·detail 은 서버의 한국어 글(가린 것) 그대로. 판정은 칸으로만 가른다(detail 글로 가르지 않는다). */
export interface DiagnosisStep {
  id: StepId;
  label: string;
  ok: boolean;
  skipped: boolean;
  detail: string;
  latency_ms: number | null;
  notes: string[];
  /** 걸음마다 고정된 기계 코드(timeout · not_finished …). */
  code: string;
  /** P2: 보내기 요청이 나갔고 결과가 분명한 거절이 아님 — 보냈는지 알 수 없음. */
  maybe_sent: boolean;
  /** P3: 아직 「접수됨」 — 실패가 아니라 확인 중. */
  pending: boolean;
}

/** 실제 시험 문자 한 건의 기록(번호 없음). */
export interface SendRecord {
  at: string;
  by: string | null;
  outcome: 'sending' | 'accepted' | 'unknown' | 'not_sent';
}

export interface Diagnosis {
  ran_at: string;
  /** sending = 시험 문자를 보내는 중(끝나지 않은 기록). */
  state: 'sending' | 'done';
  by: string | null;
  /** 실제 시험 문자 기록, 오래된 것부터(최근 20개). */
  sends: SendRecord[];
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
  /** send 면 꼭 — 확인 창을 열 때 본 허용 번호 목록의 판. */
  allow_numbers_version?: string;
  /** 「보냈는지 모름」 뒤에 사람이 따로 확인하고 다시 보낼 때만. */
  confirm_resend?: true;
}

// ── 카카오톡 채널·문안 상태(Task 101 계약) — 읽기와 쓰는 곳 잇기만. 보내기·켜기는 없다. ──

/** 채널 한 줄. status 는 제공사 말(connected …), 모르면 unknown. */
export type KakaoChannel = { id: string; name: string; status: string };

export type KakaoTemplateStatus = 'approved' | 'reviewing' | 'rejected' | 'dormant';

/** 문안 한 줄(TemplateOut). body 의 번호는 끝 4자리만 남긴 가린 꼴. reply_line = 「문자로 답하라」 줄이 있는가(서버가 지금 발신번호로 본 값). */
export interface KakaoTemplate {
  id: number;
  channel: string;
  provider_template_id: string;
  use: string | null;
  body: string;
  variables: string[];
  status: KakaoTemplateStatus;
  reply_line: boolean;
  usable: boolean;
  fallback_body: string | null;
}

/** GET …/kakao(KakaoOut). available = 목록 읽는 길이 확인됐는가, ready = 카카오톡 준비(지금은 늘 false). */
export interface KakaoState {
  available: boolean;
  reason: string | null;
  channels: KakaoChannel[];
  templates: KakaoTemplate[];
  synced_at: string | null;
  ready: boolean;
}

const kakaoPath = (id: number) => `${BASE}/${id}/kakao`;

/** 카카오톡 채널·문안 상태(관리자만). sync 는 지금 늘 501 kakao_listing_unconfirmed(SyncOut 의 truncated = 상한 뒤를 읽지 않음). PATCH 는 use 만. */
export const kakaoApi = {
  get: (id: number) => api<KakaoState>(kakaoPath(id)),
  sync: (id: number) => api<KakaoState & { truncated: boolean }>(`${kakaoPath(id)}/sync`, send('POST')),
  setUse: (id: number, tid: number, use: string | null) => api<KakaoTemplate>(`${kakaoPath(id)}/templates/${tid}`, send('PATCH', { use })),
};

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
