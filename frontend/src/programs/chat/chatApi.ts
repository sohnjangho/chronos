// 대화 API(Task 10·11)와 이 화면이 읽는 일정·워크플로우 목록.
import { api } from '../../shared/api';
import { streamPost } from '../../shared/sse';
import type { Retry } from './thread';

export interface SessionItem {
  id: number;
  title: string;
  schedule_id: number | null;
  created_at: string;
  /** 대화 주인이 시작할 '다시 짜기 요청' 수(목록만). */
  pending_retries?: number;
}

export interface SessionDetail extends Omit<SessionItem, 'pending_retries'> {
  running: boolean;
  messages: unknown[];
  pending_retries: Retry[];
}

/** 메시지 본문의 ui(모두 없어도 된다). */
export interface UiIn {
  program?: string;
  schedule_id?: number;
  selected_activity?: string;
}

/** text·questionnaire_id·approval_id 가운데 하나만. */
export type TurnInput = { text: string } | { questionnaire_id: number } | { approval_id: number };

export interface ScheduleItem {
  id: number;
  name: string;
  domain: string;
  level: string;
  version: number;
  finish: string | null;
}

export interface RunItem {
  id: number;
  chat_session_id: number | null;
  title: string;
  status: string;
  started_at: string;
  step_count: number;
}

const post = (body?: unknown): RequestInit => ({ method: 'POST', ...(body !== undefined && { body: JSON.stringify(body) }) });

export const listSessions = () => api<SessionItem[]>('/api/chat/sessions');
export const createSession = (scheduleId: number | null) => api<SessionItem>('/api/chat/sessions', post({ schedule_id: scheduleId }));
export const getSession = (id: number) => api<SessionDetail>(`/api/chat/sessions/${id}`);
export const stopTurn = (id: number) => api<{ stopping: boolean }>(`/api/chat/sessions/${id}/stop`, post());

export function postMessage(id: number, body: TurnInput & { ui: UiIn }, onEvent: (type: string, data: unknown) => void, signal: AbortSignal) {
  return streamPost(`/api/chat/sessions/${id}/messages`, body, onEvent, signal);
}

export const listSchedules = () => api<ScheduleItem[]>('/api/schedules');
export const listRuns = () => api<RunItem[]>('/api/workflows/runs');

const activityNames = new Map<number, Promise<Map<string, string>>>();

/** 일정의 액티비티 id → 이름(일정마다 한 번 읽어 둔다). 못 읽으면 빈 표. */
export function activityNamesOf(scheduleId: number): Promise<Map<string, string>> {
  let names = activityNames.get(scheduleId);
  if (!names) {
    names = api<{ activities?: { id: string; name: string }[] }>(`/api/schedules/${scheduleId}`).then(
      (v) => new Map((v.activities ?? []).map((a) => [a.id, a.name])),
      () => {
        activityNames.delete(scheduleId);
        return new Map<string, string>();
      },
    );
    activityNames.set(scheduleId, names);
  }
  return names;
}

export const forgetCachedNames = () => activityNames.clear();
