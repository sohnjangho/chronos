// 탐색기 API(이 작업의 GET /api/explorer/tree · DELETE /api/schedules/{id})와 일정·버전 API(Task 4).
import { api } from '../../shared/api';

export interface TreeSchedule {
  id: number;
  name: string;
  domain: string;
  level: string;
  version: number;
  /** 화면과 같은 계산값. 계산이 깨진 일정이면 null. */
  finish: string | null;
  updated_at: string;
}

export interface Version {
  n: number;
  note: string;
  by_kind: 'user' | 'agent' | string;
  by_name: string;
  is_plan: boolean;
  created_at: string;
}

/** 일정 보기(ScheduleView)에서 요약에 쓰는 칸만. */
export interface ScheduleSummary {
  id: number;
  version: number;
  finish: string;
  plan_finish: string | null;
  activities: unknown[];
  relations: unknown[];
}

const post = (body: unknown): RequestInit => ({ method: 'POST', body: JSON.stringify(body) });

export const exApi = {
  tree: () => api<{ schedules: TreeSchedule[] }>('/api/explorer/tree'),
  view: (id: number) => api<ScheduleSummary>(`/api/schedules/${id}`),
  versions: (id: number) => api<Version[]>(`/api/schedules/${id}/versions`),
  /** n번 버전의 내용으로 새 버전. base 는 지금 버전(그 사이 바뀌었으면 409). */
  restore: (id: number, n: number, base: number) => api<{ version: number }>(`/api/schedules/${id}/versions/${n}/restore`, post({ base_version: base })),
  /** 관리자만(아니면 403). 모든 버전·변경 이력이 함께 지워진다. */
  remove: (id: number) => api<{ deleted: number }>(`/api/schedules/${id}`, { method: 'DELETE' }),
};

const DOMAINS: Record<string, string> = { construction: '건설', production: '생산', manufacturing: '생산', research: '연구개발', commercialization: '사업화' };
export const domainLabel = (d: string) => DOMAINS[d] ?? d;

// 정밀도 이름은 backend/app/domains/levels.yaml 의 name 과 같다(그 목록을 주는 API 는 아직 없다).
const LEVELS: Record<string, string> = { L1: '마스터', L2: '요약', L3: '관리', L4: '실행', L5: '상세' };
export const levelLabel = (l: string) => (LEVELS[l] ? `${l} ${LEVELS[l]}` : l);

/** "2027-11-28" → "2027.11.28". */
export const dot = (iso: string | null) => (iso ?? '').replace(/^(\d{4})-(\d{2})-(\d{2})$/, '$1.$2.$3');

/** 시각 → "11.20 14:02"(지역 시각). */
export function stamp(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const two = (n: number) => String(n).padStart(2, '0');
  return `${two(d.getMonth() + 1)}.${two(d.getDate())} ${two(d.getHours())}:${two(d.getMinutes())}`;
}

/** 이름·숫자 뒤에 붙일 "을/를". 받침을 모르면 "을(를)". */
export function eulOf(word: string): string {
  const last = word.at(-1) ?? '';
  const code = last.charCodeAt(0) - 0xac00;
  if (code >= 0 && code < 11172) return code % 28 === 0 ? '를' : '을';
  if (/\d$/.test(last)) return /[2459]$/.test(last) ? '를' : '을';
  return '을(를)';
}
