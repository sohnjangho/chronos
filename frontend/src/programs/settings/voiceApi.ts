// AI 전화(음성 설정·음성 진단) API — notifyApi.ts 에서 나눔(그 파일의 300줄 권장). 키·번호는 요청 본문(JSON)에만.
import { api } from '../../shared/api';
import { BASE, send, type DiagnosisStep } from './notifyApi';

// Task 90 계약.

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
  /** 음성 설정을 저장한 적이 있는가 — 없으면 넣기 폼, 있으면 카드. */
  saved: boolean;
  /** 실제로 쓰는 모델(구글은 비우면 기본 Live 모델). 다른 공급자는 비우면 "" = SDK 기본. */
  model_effective: string;
  /** 실제로 쓰는 AI 전화 번호(가린 꼴). 따로 넣지 않으면 한국AI통신 연결의 발신번호. */
  agent_number_effective_masked: string | null;
  agent_number_source: 'voice' | 'connection' | null;
}

/** 이 키로 쓸 수 있는 구글 Live 모델. fallback = 구글에서 읽지 못해 고정 목록(reason 에 까닭). */
export interface VoiceModels {
  models: string[];
  default: string;
  fallback: boolean;
  /** 구글이 이 키를 거절했다(400·401·403) — models 는 비어 있고, 진단·시험 전화는 걸기 전에 멈춘다. */
  refused: boolean;
  /** 목록은 읽혔는데 실시간 음성(Live) 모델이 하나도 없다 — models 는 비어 있고, 진단·시험 전화는 걸기 전에 멈춘다. */
  no_live: boolean;
  reason: string | null;
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
  /** 음성 설정과 그 키를 지운다(관리자, 진단 중이면 409). */
  remove: (id: number) => api<void>(voicePath(id), send('DELETE')),
  /** 저장된 구글 키로 쓸 수 있는 Live 모델(못 읽으면 고정 목록 + 까닭). */
  models: (id: number) => api<VoiceModels>(`${voicePath(id)}/models`),
  diagnose: (id: number, body: VoiceDiagnoseIn, signal?: AbortSignal) =>
    api<VoiceDiagnosis>(`${voicePath(id)}/diagnose`, send('POST', body, signal)),
  /** 마지막 음성 진단. 아직 돌린 적이 없으면 null. */
  lastDiagnosis: (id: number) => api<VoiceDiagnosis | null>(`${voicePath(id)}/diagnosis`),
};
