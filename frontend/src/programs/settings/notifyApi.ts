import { api } from '../../shared/api';
import type { LlmError } from './model';

// 키·Account ID·번호는 요청 본문(JSON)에만 싣는다. 주소·기록·저장소에는 넣지 않는다.
const send = (method: string, body?: unknown, signal?: AbortSignal): RequestInit => ({
  method,
  ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  ...(signal ? { signal } : {}),
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

// ── AI 전화(음성 설정·음성 진단, Task 90 계약) ──

/** google = 구글 Gemini Live(기본), openai = OpenAI Realtime, dashboard = 대시보드 에이전트(진단 없음). */
export type VoiceProvider = 'google' | 'openai' | 'dashboard';

/** 음성 설정(VoiceOut). 키는 끝 4자리, 번호는 가린 꼴만 온다. */
export interface VoiceSettings {
  connection_id: number;
  provider: VoiceProvider;
  has_secret: boolean;
  secret_last4: string;
  /** "" = SDK 기본 모델. */
  model: string;
  agent_number_masked: string | null;
  agent_number_kind: string;
  voice_male_contact: string | null;
  voice_female_contact: string | null;
  voice_unknown: string | null;
  voices_by_language: Record<string, Record<string, string>>;
  status: 'ok' | 'failed' | 'unknown';
  checked_at: string | null;
  /** 음성 SDK 가 서버에 있는가(없으면 화면이 띠를 보이고 전화 단추를 잠근다). */
  sdk_installed: boolean;
  /** 시험 전화가 갈(받는 통화에서 받아 줄) 허용 번호의 index. 걸 수 없으면 null. */
  test_call_index: number | null;
  /** 구글이면 늘 — 키 칸 옆에 서버 글 그대로. */
  key_notice: { code: string; message: string } | null;
  call_limits: {
    calls_per_request: number;
    ring_seconds: number;
    call_seconds: number;
    inbound_wait_default: number;
    inbound_wait_min: number;
    inbound_wait_max: number;
  };
}

/** 보낸 칸만 바꾼다. 공급자를 google·openai 로 바꾸면 secret 도 꼭. */
export type VoicePatch = Partial<{
  provider: VoiceProvider;
  secret: string;
  model: string;
  agent_number: string | null;
}>;

export type VoiceStepId = 'P5' | 'P6' | 'P7' | 'P8' | 'P9' | 'P10' | 'P11' | 'P12' | 'P13' | 'P14';
export type VoicePart = 'connection' | 'call' | 'inbound';

/** 음성 진단 걸음 한 줄 = 알림 연결 걸음 줄 + data·ran_at. maybe_sent = 전화가 걸렸을 수 있다. */
export interface VoiceStep extends Omit<DiagnosisStep, 'id'> {
  id: VoiceStepId;
  data: Record<string, unknown>;
  /** 이 줄을 마지막으로 돌린 때. 한 번도 안 돌렸으면 null. */
  ran_at: string | null;
}

/** 실제 시험 전화 한 통의 기록(번호 없음). */
export interface CallRecord {
  at: string;
  by: string | null;
  outcome: 'calling' | 'placed' | 'unknown' | 'not_placed';
}

export interface VoiceDiagnosis {
  state: 'running' | 'done';
  part: VoicePart | null;
  ran_at: string;
  by: string | null;
  /** 늘 P5~P14 열 줄(걸음마다 마지막 결과). running 이면 []. */
  steps: VoiceStep[];
  called_real: boolean;
  /** 전화가 걸렸는지·끊겼는지 모름 — [시험 전화]를 곧바로 다시 누르지 못하게. */
  call_unknown: boolean;
  calls: CallRecord[];
}

export interface VoiceDiagnoseIn {
  steps?: VoiceStepId[];
  call?: true;
  inbound?: true;
  /** call·inbound 면 꼭 — 확인 창을 열 때 본 허용 번호 목록의 판. */
  allow_numbers_version?: string;
  /** 앞선 시험 전화의 결과를 모르는 채로 사람이 따로 확인하고 다시 걸 때만. */
  confirm_recall?: true;
  wait_inbound_s?: number;
}

const voicePath = (id: number) => `${BASE}/${id}/voice`;

/** AI 전화 묶음(관리자만). 키·번호는 PUT 본문에만. */
export const voiceApi = {
  get: (id: number) => api<VoiceSettings>(voicePath(id)),
  save: (id: number, body: VoicePatch) => api<VoiceSettings>(voicePath(id), send('PUT', body)),
  diagnose: (id: number, body: VoiceDiagnoseIn, signal?: AbortSignal) =>
    api<VoiceDiagnosis>(`${voicePath(id)}/diagnose`, send('POST', body, signal)),
  /** 마지막 음성 진단. 아직 돌린 적이 없으면 null. */
  lastDiagnosis: (id: number) => api<VoiceDiagnosis | null>(`${voicePath(id)}/diagnosis`),
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
