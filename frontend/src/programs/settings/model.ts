import type { Role } from '../../os/session';
import type { Tone } from '../../shared/ui/Badge';

export type Provider = 'liner' | 'openai_compatible';
export type Purpose = 'light' | 'normal' | 'hard' | 'longdoc';
export type Strategy = 'cost' | 'balanced' | 'quality';
export type ApprovalMode = 'all' | 'important' | 'auto';

/** 서버의 연결 한 줄. 키는 끝 4자리(secret_last4)만 온다. */
export interface Connection {
  id: number;
  name: string;
  provider: Provider;
  base_url: string;
  secret_last4: string;
  is_default: boolean;
  status: 'ok' | 'failed' | 'unknown';
  model_count: number | null;
  /** 대화용 모델 수. 시험에 성공한 적이 없으면 null. */
  chat_model_count?: number | null;
  checked_at: string | null;
  latency_ms: number | null;
}

/** 공개 가격(USD / 100만 토큰). 모델은 값 하나씩, 라우터(range)는 고르는 모델들의 최소~최대. */
export type Price =
  | { kind: 'model'; as_of: string; input: number; output: number; cached_input: number }
  | { kind: 'range'; as_of: string; input_min: number; input_max: number; output_min: number; output_max: number };

/** 모델 한 개. vendor 는 업체 열쇠(owned_by), vendor_name 은 보일 업체 이름, chat 은 대화 API 를 받는지. */
export interface ModelInfo {
  id: string;
  name: string;
  vendor: string;
  vendor_name: string;
  context_length: number | null;
  chat: boolean;
  /** 참고용 공개 가격. 가격표에 없으면 null. */
  price: Price | null;
}

export interface LlmError {
  code: string;
  message: string;
}

/** 저장 결과. 저장할 때 한 연결 시험이 실패했으면 error 가 있다. */
export interface ConnectionSaved extends Connection {
  error: LlmError | null;
}

/** 연결 시험 결과. 실패도 200 으로 오고 ok:false 와 error 가 있다. */
export interface Probe {
  ok: boolean;
  latency_ms: number;
  models: ModelInfo[];
  error: LlmError | null;
}

export interface Assignment {
  purpose: Purpose;
  connection_id: number | null;
  model: string;
  routing_strategy: Strategy | null;
}

export interface Account {
  id: number;
  name: string;
  role: Role;
  login_id: string;
}

export const PROVIDERS: { value: Provider; label: string; defaultBaseUrl: string | null }[] = [
  { value: 'liner', label: 'Liner', defaultBaseUrl: 'https://platform.liner.com/api/v1' },
  { value: 'openai_compatible', label: '직접 URL (OpenAI 호환)', defaultBaseUrl: null },
];

export const providerLabel = (p: Provider) => PROVIDERS.find((x) => x.value === p)?.label ?? p;

export function statusView(c: Pick<Connection, 'status' | 'model_count'>): { tone: Tone; text: string } {
  if (c.status === 'ok') return { tone: 'success', text: `연결됨 · 모델 ${c.model_count ?? 0}개` };
  if (c.status === 'failed') return { tone: 'danger', text: '연결 실패' };
  return { tone: 'neutral', text: '미확인' };
}

/** 작업 종류(시안 「작업별 모델 배정」의 글). 서버가 주는 차례(light·normal·hard·longdoc)와 같다. */
export const PURPOSES: Record<Purpose, { label: string; desc: string }> = {
  light: { label: '가벼운 일', desc: '조건 뽑기, 분야 읽기, 문서에서 변화 뽑기' },
  normal: { label: '보통 일', desc: '대화, 워크플로우 짜기, 보고서 초안' },
  hard: { label: '어려운 일', desc: 'WBS·스케줄 생성, 단축안, 위반 고치기' },
  longdoc: { label: '긴 문서 읽기', desc: '계약서·회의록 통째로' },
};

/** 라우팅 기준. 저장 값은 Liner 의 값 이름 그대로, 화면 글은 한국어. */
export const STRATEGIES: { value: Strategy; label: string }[] = [
  { value: 'cost', label: '비용 우선' },
  { value: 'balanced', label: '균형' },
  { value: 'quality', label: '품질 우선' },
];

/** 라우터 모델(이름이 -router 로 끝남)만 라우팅 기준을 받는다. */
export const isRouter = (model: string) => /.-router$/.test(model);

export const APPROVAL_MODES: { value: ApprovalMode; label: string; desc: string }[] = [
  { value: 'all', label: '모두 승인', desc: '에이전트가 일정을 바꿀 때마다 승인을 받습니다.' },
  {
    value: 'important',
    label: '중요한 것만',
    desc: '첫 저장, 준공·마일스톤·주공정·조건·구조가 바뀔 때와 조건 위반이 있을 때만 승인을 받습니다.',
  },
  { value: 'auto', label: '자동', desc: '조건 위반이 있을 때만 승인을 받고, 나머지는 바로 반영합니다.' },
];

export const approvalLabel = (m: ApprovalMode) => APPROVAL_MODES.find((x) => x.value === m)?.label ?? m;

export type SectionId = 'me' | 'llm' | 'assign' | 'account' | 'approval';

/** 설정 구역. 차례는 왼쪽 목록·메뉴 차례. */
export const SECTIONS: { id: SectionId; label: string; adminOnly: boolean }[] = [
  { id: 'me', label: '내 정보', adminOnly: false },
  { id: 'llm', label: 'LLM 연결', adminOnly: true },
  { id: 'assign', label: '작업별 모델 배정', adminOnly: true },
  { id: 'account', label: '계정 (관리자·사용자)', adminOnly: true },
  { id: 'approval', label: '승인 수준', adminOnly: true },
];

export const visibleSections = (role: Role) => SECTIONS.filter((s) => role === 'admin' || !s.adminOnly);

/**
 * params.section 을 구역으로. 볼 수 없는 구역(사용자가 부른 관리자 구역)이면 내 정보.
 * 없거나 모르는 구역이면 관리자는 LLM 연결(시안), 사용자는 내 정보.
 */
export function resolveSection(section: string | undefined, role: Role): SectionId {
  const found = visibleSections(role).find((s) => s.id === section);
  if (found) return found.id;
  return role === 'admin' ? 'llm' : 'me';
}

const pad = (n: number) => String(n).padStart(2, '0');

/**
 * 연결 확인 시각. 예 "오늘 21:32 · 응답 412ms", "11월 19일 21:32".
 * 서버 시각에 시간대가 없으면 UTC 로 읽는다(SQLite 는 시간대를 지운다).
 */
export function checkedText(checkedAt: string | null, latencyMs: number | null, now = new Date()): string {
  if (!checkedAt) return '확인한 적 없음';
  const hasZone = /(Z|[+-]\d\d:?\d\d)$/.test(checkedAt);
  const at = new Date(hasZone ? checkedAt : `${checkedAt}Z`);
  const sameDay = at.toDateString() === now.toDateString();
  const day = sameDay ? '오늘' : `${at.getMonth() + 1}월 ${at.getDate()}일`;
  const text = `${day} ${pad(at.getHours())}:${pad(at.getMinutes())}`;
  return latencyMs === null ? text : `${text} · 응답 ${latencyMs}ms`;
}
