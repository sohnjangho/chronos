// 질문지 API(Task 8 v2). 질문은 에이전트가 만들고, 답하지 않은 질문은 그 질문의 가정(assumption)으로 넘어간다.
import { api } from '../../shared/api';

export interface QOption {
  value: string;
  label: string;
  hint?: string | null;
  recommended?: boolean;
}

export interface QAnswer {
  value: string;
  /** 선택지의 label, 직접 적은 답이면 그 글. */
  label: string;
}

export interface QQuestion {
  id: string;
  question: string;
  why: string;
  options: QOption[];
  allow_free: boolean;
  /** 답하지 않으면 이렇게 가정한다. */
  assumption: string;
  answer: QAnswer | null;
}

export interface QGroup {
  name: string;
  answered: number;
  total: number;
  questions: QQuestion[];
}

export interface Prefilled {
  label: string;
  value: string;
  source: string;
}

export interface QView {
  id: number;
  title: string;
  purpose: string;
  status: 'open' | 'submitted';
  round: number;
  /** 이 질문지를 만든 대화. 대화 밖에서 만들었으면 null. */
  chat_session_id: number | null;
  progress: { answered: number; total: number };
  prefilled: Prefilled[];
  /** 질문에 처음 나온 차례. */
  groups: QGroup[];
}

const base = (id: number) => `/api/questionnaires/${id}`;

export const getQuestionnaire = (id: number) => api<QView>(base(id));

/** value 가 null 이면 답을 지운다(가정대로 둔다). 돌아온 전체 보기로 다시 그린다. */
export const answerQuestion = (id: number, questionId: string, value: string | null) =>
  api<QView>(`${base(id)}/answers`, { method: 'PATCH', body: JSON.stringify({ question_id: questionId, value }) });

/** 본문(answers·assumed)은 대화가 읽는다. 이 화면은 성공 여부만 본다. */
export const submitQuestionnaire = (id: number) => api<{ id: number; status: 'submitted' }>(`${base(id)}/submit`, { method: 'POST' });
