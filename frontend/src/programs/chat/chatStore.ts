// 대화창 상태. 스트림은 창이 아니라 이 store 에 산다 — 대화를 바꾸거나 창을 닫았다 열어도 도는 답이 이어진다.
// 로그아웃(사용자 바뀜)하면 도는 답을 멈추고 비운다.
import { create } from 'zustand';
import { useAiChat } from '../../os/aiChat';
import { useCurrentSchedule, type CurrentSchedule } from '../../os/currentSchedule';
import { useSession } from '../../os/session';
import { useWindows, type Win } from '../../os/windowStore';
import { ApiError } from '../../shared/api';
import * as chatApi from './chatApi';
import type { SessionItem, TurnInput, UiIn } from './chatApi';
import { applyEvent, emptyThread, fromDetail, isObj, nextKey, stopRunning, ZERO_USAGE, type Item, type Json, type Thread } from './thread';

/** 다른 프로그램이 알리는 화면 맥락(Task 10 의 ui). */
export interface UiContext {
  program?: string | null;
  schedule_id?: number | null;
  selected_activity?: string | null;
}

export type ResumeInput = { questionnaire_id: number } | { approval_id: number };

interface ChatState {
  uiContext: UiContext | null;
  sessions: SessionItem[];
  listNotice: string | null;
  currentId: number | null;
  threads: Record<number, Thread>;
  /** 아직 대화가 없을 때(새 대화)의 알림. */
  notice: string | null;
  setUiContext(ctx: UiContext | null): void;
  loadSessions(): Promise<void>;
  openSession(id: number): Promise<void>;
  newChat(): void;
  /** 글을 보낸다. 서버가 받아 첫 사건이 오면 true, 보내기 전에 거절되면 false(글을 입력창에 돌려줄 수 있게). */
  send(text: string): Promise<boolean>;
  /** 제출한 질문지·다시 짜기로 거부한 승인 건으로 대화를 이어 간다. 같은 것은 한 번만. */
  resume(sessionId: number, input: ResumeInput): Promise<void>;
  stop(): Promise<void>;
  reset(): void;
}

const RUNNING_ELSEWHERE = '이 대화의 앞 요청을 처리하는 중입니다. 끝나면 이 화면에 이어서 보입니다.';

const message = (err: unknown) => (err instanceof ApiError ? err.message : '처리 중 문제가 생겼습니다.');

/** 대화창이 아닌 맨 앞 창(최소화 안 함). 다른 프로그램이 맥락을 알리지 않았을 때 "보는 것"으로 본다. */
function frontOther(wins: Win[]): Win | null {
  let top: Win | null = null;
  for (const w of wins) if (w.programId !== 'chat' && !w.minimized && (!top || w.z > top.z)) top = w;
  return top;
}

/** 보낼 ui: 알린 맥락 → 없으면 맨 앞 다른 창. schedule_id 가 없으면 OS 의 지금 일정. */
export function effectiveUi(ctx: UiContext | null, wins: Win[], current: CurrentSchedule | null): UiIn {
  const front = ctx ? null : frontOther(wins);
  const program = ctx ? ctx.program : front?.programId;
  const activity = ctx ? ctx.selected_activity : front?.params?.activity;
  const scheduleId = ctx?.schedule_id ?? current?.id;
  return {
    ...(program && { program }),
    ...(typeof scheduleId === 'number' && { schedule_id: scheduleId }),
    ...(activity && { selected_activity: activity }),
  };
}

const uiNow = () => effectiveUi(useChat.getState().uiContext, useWindows.getState().wins, useCurrentSchedule.getState().current);

const controllers = new Map<number, AbortController>();
const handled = new Set<string>();
let generation = 0;

const initial = { uiContext: null, sessions: [], listNotice: null, currentId: null, threads: {}, notice: null };

/** 그 대화가 아직 있을 때만 고친다(로그아웃 뒤 늦게 온 사건은 버린다). */
function patch(id: number, change: (t: Thread) => Thread) {
  useChat.setState((s) => (s.threads[id] ? { threads: { ...s.threads, [id]: change(s.threads[id]) } } : {}));
}

function onEvent(id: number, type: string, data: unknown) {
  if (!isObj(data)) return;
  const open = useWindows.getState().open;
  if (type === 'open_window' && typeof data.program === 'string') {
    const params = isObj(data.params) ? Object.fromEntries(Object.entries(data.params).map(([k, v]) => [k, String(v)])) : {};
    // 질문지 창은 이 대화를 알아야 제출 뒤 이어 갈 수 있다(Task 15).
    open(data.program, data.program === 'questionnaire' && params.id ? { ...params, session: String(id) } : params);
    return;
  }
  if (type === 'questionnaire' && data.id !== undefined) open('questionnaire', { id: String(data.id), session: String(id) });
  patch(id, (t) => applyEvent(t, type, data));
}

/** 턴 하나를 돌린다. 돌려주는 약속은 "서버가 받았나"만 알린다 — 스트림은 뒤에서 이어진다. */
function runTurn(id: number, body: TurnInput, item: Item): Promise<boolean> {
  const gen = generation;
  const controller = new AbortController();
  controllers.set(id, controller);
  patch(id, (t) => ({ ...t, items: [...t.items, item], streaming: true, stopping: false, notice: null, workflow: null }));
  let started = false;
  return new Promise<boolean>((resolve) => {
    const live = (type: string, data: unknown) => {
      if (gen !== generation) return;
      if (!started) {
        started = true;
        resolve(true);
        void useChat.getState().loadSessions(); // 서버가 첫 메시지로 정한 제목을 바로 보인다
      }
      onEvent(id, type, data);
    };
    chatApi
      .postMessage(id, { ...body, ui: uiNow() }, live, controller.signal)
      .then(() => resolve(true))
      .catch((err: unknown) => {
        if (gen !== generation) return;
        if (started) patch(id, (t) => applyEvent(t, 'error', { code: 'network_error', message: message(err) }));
        else patch(id, (t) => ({ ...t, items: t.items.filter((i) => i !== item), notice: message(err) }));
        resolve(false);
      })
      .finally(() => {
        if (controllers.get(id) === controller) controllers.delete(id);
        if (gen !== generation) return;
        patch(id, (t) => ({ ...stopRunning(t), streaming: false, stopping: false }));
        void useChat.getState().loadSessions();
      });
  });
}

async function loadSessions() {
  const gen = generation;
  try {
    const sessions = await chatApi.listSessions();
    if (gen === generation) useChat.setState({ sessions, listNotice: null });
  } catch (err) {
    if (gen === generation) useChat.setState({ listNotice: message(err) });
  }
}

/** 대화를 고르고 저장된 메시지를 읽는다. 답이 도는 대화는 다시 읽지 않는다(도는 상태를 덮지 않게). */
async function openSession(id: number) {
  const gen = generation;
  useChat.setState((s) => ({ currentId: id, notice: null, threads: s.threads[id] ? s.threads : { ...s.threads, [id]: emptyThread() } }));
  if (useChat.getState().threads[id].streaming) return;
  try {
    const detail = await chatApi.getSession(id);
    if (gen !== generation || useChat.getState().threads[id]?.streaming) return;
    // 다른 곳(Context 패널 AI 탭 등)에서 보낸 턴이 아직 돌면 그 스트림은 여기로 오지 않는다 — 알리고, 끝나면 다시 읽는다.
    const notice = detail.running ? RUNNING_ELSEWHERE : null;
    useChat.setState((s) => ({ threads: { ...s.threads, [id]: { ...fromDetail(detail), usage: s.threads[id]?.usage ?? ZERO_USAGE, notice } } }));
  } catch (err) {
    if (gen === generation) patch(id, (t) => ({ ...t, notice: message(err) }));
  }
}

/** 지금 대화(없으면 새로 만들어)에 글을 보낸다. */
async function send(text: string): Promise<boolean> {
  let id = useChat.getState().currentId;
  if (id !== null && useChat.getState().threads[id]?.streaming) return false;
  if (id === null) {
    try {
      const created = await chatApi.createSession(uiNow().schedule_id ?? null);
      id = created.id;
      useChat.setState((s) => ({
        sessions: [{ ...created, pending_retries: 0 }, ...s.sessions.filter((x) => x.id !== created.id)],
        currentId: created.id,
        threads: { ...s.threads, [created.id]: { ...emptyThread(), loaded: true } },
        notice: null,
      }));
    } catch (err) {
      useChat.setState({ notice: message(err) });
      return false;
    }
  }
  return runTurn(id, { text }, { kind: 'user', key: nextKey(), text });
}

/** 이어 가기를 알리는 시스템 카드 내용(승인 건이면 기다리던 요청에서 지운다). */
function resumeContent(sessionId: number, t: Thread, input: ResumeInput): Json {
  if ('questionnaire_id' in input) return { kind: 'questionnaire_submitted', questionnaire_id: input.questionnaire_id };
  const retry = t.retries.find((r) => r.approval_id === input.approval_id);
  patch(sessionId, (x) => ({ ...x, retries: x.retries.filter((r) => r.approval_id !== input.approval_id) }));
  return { kind: 'approval_rejected', approval_id: input.approval_id, title: retry?.title ?? '', note: retry?.note ?? '' };
}

async function resume(sessionId: number, input: ResumeInput) {
  const key = 'questionnaire_id' in input ? `q:${sessionId}:${input.questionnaire_id}` : `a:${sessionId}:${input.approval_id}`;
  if (handled.has(key)) return;
  handled.add(key);
  await openSession(sessionId);
  const t = useChat.getState().threads[sessionId];
  if (!t || t.streaming) {
    handled.delete(key);
    if (t) patch(sessionId, (x) => ({ ...x, notice: '앞의 요청을 처리하는 중입니다.' }));
    return;
  }
  const ok = await runTurn(sessionId, input, { kind: 'system', key: nextKey(), content: resumeContent(sessionId, t, input) });
  if (!ok) handled.delete(key);
}

async function stop() {
  const id = useChat.getState().currentId;
  const t = id === null ? undefined : useChat.getState().threads[id];
  if (id === null || !t?.streaming || t.stopping) return;
  patch(id, (x) => ({ ...x, stopping: true }));
  try {
    await chatApi.stopTurn(id);
  } catch (err) {
    patch(id, (x) => ({ ...x, stopping: false, notice: message(err) }));
  }
}

function reset() {
  generation += 1;
  controllers.forEach((c) => c.abort());
  controllers.clear();
  handled.clear();
  chatApi.forgetCachedNames();
  useChat.setState(initial);
}

export const useChat = create<ChatState>((set) => ({
  ...initial,
  setUiContext: (uiContext) => set({ uiContext }),
  loadSessions,
  openSession,
  newChat: () => set({ currentId: null, notice: null }),
  send,
  resume,
  stop,
  reset,
}));

/** 지시서 이름. 다른 프로그램은 import할 수 없으므로(프로그램끼리 import 금지) 보고서의 우려 참고. */
export const chatStore = useChat;

// Context 패널 「AI」 탭의 답이 끝나면, 그 대화를 여기서 열어 두었을 때(「전체 화면으로」) 다시 읽어 잇는다.
useAiChat.subscribe((s, prev) => {
  const { currentId, threads } = useChat.getState();
  if (prev.busy && !s.busy && s.sessionId !== null && s.sessionId === currentId && !threads[currentId]?.streaming) void openSession(currentId);
});

// 사용자가 바뀌면(로그아웃 포함) 앞 사람의 대화·도는 답을 지운다.
useSession.subscribe((s, prev) => {
  if (s.session?.user.id !== prev.session?.user.id) useChat.getState().reset();
});
