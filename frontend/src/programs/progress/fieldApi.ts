import { api } from '../../shared/api';

export type FieldKind = 'checkin' | 'photo' | 'poll' | 'handoff';

export interface FieldItem {
  id: number;
  schedule_id: number;
  kind: FieldKind;
  activity_id: string;
  activity_name: string;
  trade: string;
  status: 'pending' | 'responded' | 'applied';
  title: string;
  prompt_text: string;
  response_choice: string | null;
  reported_progress: number | null;
  reported_rd: number | null;
  response_note: string;
  payload_json: Record<string, unknown>;
  approval_id: number | null;
  created_at: string;
  updated_at: string;
}

export interface FieldSummary {
  checkin_total: number;
  checkin_responded: number;
  photo_total: number;
  poll_total: number;
  poll_feasible: number;
  poll_conditional: number;
  poll_infeasible: number;
  handoff_total: number;
  handoff_ready: number;
}

export interface FieldActivityOption {
  id: string;
  name: string;
  progress: number;
  rd: number;
}

export interface FieldData {
  schedule_id: number;
  schedule_name: string;
  activities: FieldActivityOption[];
  summary: FieldSummary;
  items: FieldItem[];
  /** 이번 요청의 알림(체크인 일괄 발송에서 건너뛴 것 등). */
  notice?: string | null;
}

const json = (method: string, body?: unknown): RequestInit => ({
  method,
  ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
});

export const fieldApi = {
  list: (sid: number) => api<FieldData>(`/api/schedules/${sid}/field`),
  dispatchCheckins: (sid: number, activityIds?: string[]) =>
    api<FieldData>(`/api/schedules/${sid}/field/checkins/dispatch`, json('POST', { activity_ids: activityIds ?? null })),
  uploadPhoto: (
    sid: number,
    body: { activity_id: string; trade?: string; photo_name: string; photo_data_url?: string; note?: string },
  ) => api<FieldData>(`/api/schedules/${sid}/field/photos`, json('POST', body)),
  createPoll: (
    sid: number,
    body: { activity_id: string; trade?: string; scenario_title: string; target_delta_days: number; prompt_text: string },
  ) => api<FieldData>(`/api/schedules/${sid}/field/polls`, json('POST', body)),
  respond: (
    sid: number,
    itemId: number,
    body: { response_choice: string; reported_progress?: number; reported_rd?: number; response_note: string },
  ) => api<FieldData>(`/api/schedules/${sid}/field/${itemId}/respond`, json('POST', body)),
  updateHandoff: (
    sid: number,
    itemId: number,
    body: { pred_handover_ok: boolean; material: boolean; equipment: boolean; workforce: boolean; response_note: string },
  ) => api<FieldData>(`/api/schedules/${sid}/field/${itemId}/handoff`, json('POST', body)),
  apply: (sid: number, itemId: number) => api<FieldData>(`/api/schedules/${sid}/field/${itemId}/apply`, json('POST')),
};
