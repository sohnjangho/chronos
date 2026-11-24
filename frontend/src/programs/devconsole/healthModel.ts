// 시스템 진단 대응표의 꼴과 공용 도우미(healthChecks · healthContact 가 같이 쓴다).
import type { NotifyDiagnosis } from './devApi';

export type CheckState = 'ok' | 'check' | 'fail' | 'unknown';
export type AreaId = 'ai' | 'contact' | 'data' | 'live' | 'other';

/** 영역 차례 = 화면 2열 묶음 차례(AI·검색 | 문자·카카오톡·전화 / 자료 | 지금 접속·실행 중), 기타는 맨 뒤. */
export const AREAS: { id: AreaId; label: string }[] = [
  { id: 'ai', label: 'AI · 검색' },
  { id: 'contact', label: '문자 · 카카오톡 · 전화' },
  { id: 'data', label: '자료' },
  { id: 'live', label: '지금 접속 · 실행 중' },
  { id: 'other', label: '기타' },
];

export const STATES: { id: CheckState; label: string }[] = [
  { id: 'ok', label: '정상' },
  { id: 'check', label: '확인 필요' },
  { id: 'fail', label: '실패' },
  { id: 'unknown', label: '모름' },
];
export const stateLabel = (s: CheckState | 'info') => STATES.find((x) => x.id === s)?.label ?? '지금';

export interface KvGroup {
  title: string;
  rows: [string, string][];
}

export interface Check {
  id: string;
  /** 서버 응답의 어느 칸에서 왔나(대응표 빠짐 검사용). */
  source: string;
  area: AreaId;
  name: string;
  tech?: string;
  state: CheckState | 'info';
  summary: string;
  todo: string | null;
  impact: string;
  /** 지금 상태 · 설정(키-값 묶음). */
  fields: KvGroup[];
  /** 저장된 마지막 진단 걸음(문자 연결 · AI 전화). */
  steps?: { title: string; diag: NotifyDiagnosis } | null;
  /** 되살리는 길 같은 덧말. */
  note?: string | null;
  /** 그 칸의 서버 응답 그대로(접힌 기계 출력). */
  raw: unknown;
  /** server: 서버가 적은 마지막 확인(null 이면 아직 없음), 아니면 진단을 부른 때. */
  checkedAt: { at: string | null; server: boolean };
}

export const TEST_WORD: Record<string, string> = { ok: '정상', failed: '실패', unknown: '모름' };
export const NOT_YET = '아직 없음';

/** 예전 상태 말 → 넷. off(꺼짐)·warn(주의)은 확인 필요, error·failed(오류·실패)는 실패. */
export function fromStatus(s: unknown): CheckState | null {
  if (s === 'ok') return 'ok';
  if (s === 'warn' || s === 'off' || s === 'check') return 'check';
  if (s === 'error' || s === 'failed') return 'fail';
  if (s === 'unknown') return 'unknown';
  return null;
}

export function when(v: unknown): string {
  if (typeof v !== 'string') return NOT_YET;
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString('ko-KR', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

export function bytesText(bytes: number): string {
  if (bytes <= 0) return '0 B';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export const n = (v: number) => v.toLocaleString('ko-KR');
export const worse = (a: CheckState, b: CheckState): CheckState => (RANK[a] <= RANK[b] ? a : b);
export const RANK: Record<CheckState, number> = { fail: 0, check: 1, unknown: 2, ok: 3 };
export const diagFlags = (d: NotifyDiagnosis | null) => ({
  failed: d?.steps.filter((s) => s.outcome === 'failed') ?? [],
  check: d?.steps.filter((s) => s.outcome === 'check') ?? [],
  unfinished: d?.state === 'sending',
});
