// 대화 한 개의 화면 상태. 실시간 SSE 사건과 다시 연 대화의 저장 메시지를 같은 모양으로 만든다(같은 카드로 보이게).

import type { ChatFile, ChatModel } from './chatApi';

export type Json = Record<string, unknown>;
export type StepStatus = 'running' | 'done' | 'failed' | 'stopped';

/** 도구 한 번(tool_start → tool_end). 서버가 보낸 도구 이름 그대로. */
export interface Step {
  callId: string;
  tool: string;
  status: StepStatus;
  ms: number | null;
  error: string | null;
}

export interface ErrorAction {
  open: string;
  params: Record<string, string>;
}

export type Part =
  | { type: 'text'; text: string }
  | { type: 'notice'; text: string }
  | { type: 'card'; event: 'card' | 'questionnaire' | 'approval'; data: Json }
  | { type: 'error'; code: string; message: string; action: ErrorAction | null };

export type Item =
  | { kind: 'user'; key: string; text: string; fileNames?: string[] }
  /** 질문지 제출(questionnaire_submitted)·승인 거부 뒤 이어 가기(approval_rejected) 사용자 메시지. */
  | { kind: 'system'; key: string; content: Json }
  /** 한 턴의 에이전트 답: 도구 단계는 한 줄로 접고, 글·카드·오류는 온 차례대로. */
  | { kind: 'agent'; key: string; steps: Step[]; parts: Part[]; textOpen: boolean };

export interface WorkflowInfo {
  run_id: number;
  status: string;
  steps: { n: number; tool: string; program: string | null; status: string }[];
}

export interface Usage {
  input_tokens: number;
  output_tokens: number;
  calls: number;
  cost: number | null;
}

/** 다른 사람이 '거부하고 다시 짜기' 로 결정해 대화 주인을 기다리는 승인 건(Task 11). */
export interface Retry {
  approval_id: number;
  title: string;
  note: string;
  decided_by_name: string;
  decided_at: string;
}

/** 제출한 질문지·다시 짜기로 거부한 승인 건으로 이어 가기. */
export type ResumeInput = { questionnaire_id: number } | { approval_id: number };

export interface Thread {
  items: Item[];
  retries: Retry[];
  model: ChatModel | null;
  files: ChatFile[];
  workflow: WorkflowInfo | null;
  /** 이 창에서 받은 usage 사건의 합. 받은 적이 없으면 null(다시 연 대화의 앞 사용량은 모른다). */
  usage: Usage | null;
  /** 서버가 거절한 질문지 이어 가기([다시 이어 가기]로 다시 보낸다). */
  failedResume: ResumeInput | null;
  streaming: boolean;
  stopping: boolean;
  /** 보내기 전에 거절된 요청의 서버 글(예: 409) 같은 한 줄 알림. */
  notice: string | null;
  loaded: boolean;
}

const ZERO_USAGE: Usage = { input_tokens: 0, output_tokens: 0, calls: 0, cost: null };

export const emptyThread = (): Thread => ({
  items: [],
  retries: [],
  model: null,
  files: [],
  workflow: null,
  usage: null,
  failedResume: null,
  streaming: false,
  stopping: false,
  notice: null,
  loaded: false,
});

let seq = 0;
export const nextKey = () => `k${++seq}`;

export const isObj = (v: unknown): v is Json => typeof v === 'object' && v !== null && !Array.isArray(v);
const str = (v: unknown) => (typeof v === 'string' ? v : null);
const num = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? v : null);

type Agent = Extract<Item, { kind: 'agent' }>;

/** 마지막 항목이 에이전트 답이면 그것을, 아니면 새 답을 만들어 고친다. */
function withAgent(t: Thread, change: (a: Agent) => Agent): Thread {
  const last = t.items[t.items.length - 1];
  if (last?.kind === 'agent') return { ...t, items: [...t.items.slice(0, -1), change(last)] };
  return { ...t, items: [...t.items, change({ kind: 'agent', key: nextKey(), steps: [], parts: [], textOpen: false })] };
}

/** 바로 앞이 글이면 잇는다(같은 답의 조각). 도구·카드 뒤의 글은 새 문단. */
function addText(a: Agent, text: string): Agent {
  const last = a.parts[a.parts.length - 1];
  if (a.textOpen && last?.type === 'text') return { ...a, parts: [...a.parts.slice(0, -1), { type: 'text', text: last.text + text }] };
  return { ...a, parts: [...a.parts, { type: 'text', text }], textOpen: true };
}

/** 생성 단계 카드는 한 장을 고쳐 간다(단계마다 쌓지 않음). */
function addCard(a: Agent, event: 'card' | 'questionnaire' | 'approval', data: Json): Agent {
  const last = a.parts[a.parts.length - 1];
  const isGeneration = (p?: Part) => p?.type === 'card' && p.event === 'card' && p.data.kind === 'generation';
  const parts = event === 'card' && data.kind === 'generation' && isGeneration(last) ? a.parts.slice(0, -1) : a.parts;
  return { ...a, parts: [...parts, { type: 'card', event, data }], textOpen: false };
}

function endStep(a: Agent, data: Json): Agent {
  const callId = str(data.call_id);
  if (!a.steps.some((s) => s.callId === callId)) return a;
  const status: StepStatus = data.ok === true ? 'done' : 'failed';
  const steps = a.steps.map((s) => (s.callId === callId ? { ...s, status, ms: num(data.ms), error: str(data.error) } : s));
  return { ...a, steps, textOpen: false };
}

function errorPart(data: Json): Part {
  const action = isObj(data.action) && typeof data.action.open === 'string' ? data.action : null;
  const params = action && isObj(action.params) ? Object.fromEntries(Object.entries(action.params).map(([k, v]) => [k, String(v)])) : {};
  return {
    type: 'error',
    code: str(data.code) ?? 'error',
    message: str(data.message) ?? '처리 중 문제가 생겼습니다.',
    action: action ? { open: String(action.open), params } : null,
  };
}

function addUsage(u: Usage, data: Json): Usage {
  const cost = num(data.cost);
  return {
    input_tokens: u.input_tokens + (num(data.input_tokens) ?? 0),
    output_tokens: u.output_tokens + (num(data.output_tokens) ?? 0),
    calls: u.calls + (num(data.calls) ?? 0),
    cost: cost === null ? u.cost : (u.cost ?? 0) + cost,
  };
}

/** SSE 사건 하나를 반영한 새 상태. 모르는 사건·깨진 data 는 그냥 넘긴다(던지지 않음). */
export function applyEvent(t: Thread, type: string, data: unknown): Thread {
  if (!isObj(data)) return t;
  switch (type) {
    case 'text': {
      const text = str(data.text);
      return text ? withAgent(t, (a) => addText(a, text)) : t;
    }
    case 'tool_start': {
      const callId = str(data.call_id);
      const tool = str(data.tool);
      if (!callId || !tool) return t;
      return withAgent(t, (a) => ({ ...a, steps: [...a.steps, { callId, tool, status: 'running', ms: null, error: null }], textOpen: false }));
    }
    case 'tool_end':
      return t.items[t.items.length - 1]?.kind === 'agent' ? withAgent(t, (a) => endStep(a, data)) : t;
    case 'card':
    case 'questionnaire':
    case 'approval':
      return withAgent(t, (a) => addCard(a, type, data));
    case 'notice': {
      const text = str(data.text);
      return text ? withAgent(t, (a) => ({ ...a, parts: [...a.parts, { type: 'notice', text }], textOpen: false })) : t;
    }
    case 'error':
      return withAgent(t, (a) => ({ ...a, parts: [...a.parts, errorPart(data)], textOpen: false }));
    case 'workflow':
      return Array.isArray(data.steps) ? { ...t, workflow: { run_id: num(data.run_id) ?? 0, status: str(data.status) ?? '', steps: data.steps.filter(isObj) as WorkflowInfo['steps'] } } : t;
    case 'usage':
      return { ...t, usage: addUsage(t.usage ?? ZERO_USAGE, data) };
    default:
      return t;
  }
}

/** 끝나지 않은 단계를 멈춘 것으로(턴이 끝났는데 결과가 없는 도구). */
export function stopRunning(t: Thread): Thread {
  const items = t.items.map((i) =>
    i.kind === 'agent' && i.steps.some((s) => s.status === 'running')
      ? { ...i, steps: i.steps.map((s) => (s.status === 'running' ? { ...s, status: 'stopped' as const } : s)) }
      : i,
  );
  return { ...t, items };
}

function toolError(content: unknown): string | null {
  try {
    const parsed: unknown = JSON.parse(String(content));
    return isObj(parsed) ? str(parsed.error) : null;
  } catch {
    return null;
  }
}

/** 저장된 메시지 하나(Task 10 의 role·content 모양)를 반영한다. */
function applyMessage(t: Thread, role: unknown, c: Json): Thread {
  if (role === 'user') {
    if (c.kind === 'text') return { ...t, items: [...t.items, { kind: 'user', key: nextKey(), text: String(c.text ?? '') }] };
    if (c.kind === 'questionnaire_submitted' || c.kind === 'approval_rejected') return { ...t, items: [...t.items, { kind: 'system', key: nextKey(), content: c }] };
    return t;
  }
  if (role === 'assistant') {
    const next = applyEvent(t, 'text', { text: c.text });
    if (c.kind !== 'tool_calls' || !Array.isArray(c.tool_calls)) return next;
    return c.tool_calls.filter(isObj).reduce((acc, call) => applyEvent(acc, 'tool_start', { call_id: call.id, tool: call.name }), next);
  }
  if (role === 'tool' && c.kind === 'tool_result') {
    return applyEvent(t, 'tool_end', { call_id: c.tool_call_id, ok: c.ok, ms: null, error: c.ok === true ? null : toolError(c.content) });
  }
  if (role === 'event' && typeof c.type === 'string') return applyEvent(t, c.type, c.data);
  return t;
}

/** GET /api/chat/sessions/{id} 의 messages·running·pending_retries·model·files 로 만든 상태. */
export function fromDetail(detail: {
  messages?: unknown;
  running?: unknown;
  pending_retries?: unknown;
  model?: ChatModel | null;
  files?: ChatFile[];
}): Thread {
  const messages = Array.isArray(detail.messages) ? detail.messages.filter(isObj) : [];
  let t = messages.reduce((acc, m) => (isObj(m.content) ? applyMessage(acc, m.role, m.content) : acc), emptyThread());
  if (detail.running !== true) t = stopRunning(t);
  const retries = Array.isArray(detail.pending_retries) ? (detail.pending_retries.filter(isObj) as unknown as Retry[]) : [];
  const files = Array.isArray(detail.files) ? detail.files : [];
  const model = detail.model ?? null;
  return { ...t, retries, model, files, loaded: true };
}

/**
 * 질문지 보기(GET /api/questionnaires/{id})로 만든 제출 카드 내용 — 이어 가기를 보내는 순간부터 답·가정 수를 보인다.
 * 저장되는 questionnaire_submitted 메시지와 같은 모양(answers·assumed).
 */
export function submissionFromView(questionnaireId: number, view: unknown): Json {
  const questions = (isObj(view) && Array.isArray(view.groups) ? view.groups : [])
    .filter(isObj)
    .flatMap((g) => (Array.isArray(g.questions) ? g.questions.filter(isObj) : []));
  const answered = questions.filter((q) => isObj(q.answer));
  return {
    kind: 'questionnaire_submitted',
    questionnaire_id: questionnaireId,
    answers: answered.map((q) => ({ question_id: q.id, question: q.question, value: (q.answer as Json).value, label: (q.answer as Json).label })),
    assumed: questions.filter((q) => !isObj(q.answer)).map((q) => ({ question_id: q.id, question: q.question, assumption: q.assumption })),
  };
}
