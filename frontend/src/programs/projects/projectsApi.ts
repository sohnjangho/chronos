// 프로젝트 관리 API(/api/projects). 이름과 에이전트가 쓰는 소개 — 통화·문자에서 AI 가 부를 이름·현장 주소·한 줄 소개·발주처·시공사.
import { api } from '../../shared/api';

export interface Project {
  id: number;
  name: string;
  /** 적어 둔 「AI 가 부를 이름」(비었으면 빈 글). */
  spoken_name: string;
  /** AI 가 실제로 부르는 이름: spoken_name, 비었으면 서버가 날짜·판 표시를 뗀 이름. */
  spoken: string;
  site_address: string;
  summary: string;
  client_builder: string;
  updated_at: string | null;
  updated_by: string;
}

export type ProjectFields = Pick<Project, 'name' | 'spoken_name' | 'site_address' | 'summary' | 'client_builder'>;

export const FIELD_KEYS: (keyof ProjectFields)[] = ['name', 'spoken_name', 'site_address', 'summary', 'client_builder'];

/** 서버 상한과 같다(app.programs.projects.service.LIMITS). */
export const LIMITS: Record<keyof ProjectFields, number> = { name: 120, spoken_name: 40, site_address: 120, summary: 200, client_builder: 80 };

export const listProjects = () => api<Project[]>('/api/projects');

/** 바뀐 칸만 보낸다. */
export const patchProject = (id: number, body: Partial<ProjectFields>) =>
  api<Project>(`/api/projects/${id}`, { method: 'PATCH', body: JSON.stringify(body) });
