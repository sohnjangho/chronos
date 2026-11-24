// 대화창 상태. 스트림은 창이 아니라 이 store 에 산다 — 대화를 바꾸거나 창을 닫았다 열어도 도는 답이 이어진다.
// 로그아웃(사용자 바뀜)하면 도는 답을 멈추고 비운다.
import { create } from 'zustand';
import { useAgentView } from '../../os/agentView';
import { useAiChat } from '../../os/aiChat';
import { useCurrentSchedule } from '../../os/currentSchedule';
import { useSession } from '../../os/session';
import { useWindows } from '../../os/windowStore';
import { ApiError } from '../../shared/api';
import * as chatApi from './chatApi';
import type { ChatModel, SessionItem, TurnInput } from './chatApi';
import { currentUi } from './seeing';
import { applyEvent, emptyThread, fromDetail, isObj, nextKey, stopRunning, submissionFromView, type Item, type Json, type Retry, type ResumeInput, type Thread } from './thread';

export type { ResumeInput };

interface ChatState {
  sessions: SessionItem[];
  listNotice: string | null;
  currentId: number | null;
  threads: Record<number, Thread>;
  /** 새 대화에서 고른 모델(첫 보내기 때 세션 생성 직후 PUT). */
  pendingModel: ChatModel | null;
  /** 새 대화에 고정할 일정 id(null 이면 새 프로젝트 생성 격리, undefined 면 UI 기본 규칙). */
  pendingScheduleId: number | null | undefined;
  /** 아직 대화가 없을 때(새 대화)의 알림. */
  notice: string | null;
  loadSessions(): Promise<void>;
  openSession(id: number): Promise<void>;
  newChat(explicitScheduleId?: number | null): void;
  bindSessionSchedule(sessionId: number, scheduleId: number): void;
  /** 글을 보낸다. 서버가 받아 첫 사건이 오면 true, 보내기 전에 거절되면 false(글을 입력창에 돌려줄 수 있게). */
  send(text: string, fileIds?: number[], fileNames?: string[]): Promise<boolean>;
  setModel(model: ChatModel): Promise<void>;
  clearModel(): Promise<void>;
  /** 제출한 질문지·다시 짜기로 거부한 승인 건으로 대화를 이어 간다. 같은 것은 한 번만(거절되면 다시 할 수 있다). */
  resume(sessionId: number, input: ResumeInput): Promise<void>;
  stop(): Promise<void>;
  reset(): void;
}

const RUNNING_ELSEWHERE = '이 대화의 앞 요청을 처리하는 중입니다. 끝나면 이 화면에 이어서 보입니다.';
const BUSY = '앞의 요청을 처리하는 중입니다.';

const message = (err: unknown) => (err instanceof ApiError ? err.message : '처리 중 문제가 생겼습니다.');

const controllers = new Map<number, AbortController>();
const handled = new Set<string>();
let generation = 0;

const initial = {
  sessions: [],
  listNotice: null,
  currentId: null,
  threads: {},
  pendingModel: null,
  pendingScheduleId: undefined as number | null | undefined,
  notice: null,
};

/** 그 대화가 아직 있을 때만 고친다(로그아웃 뒤 늦게 온 사건은 버린다). */
function patch(id: number, change: (t: Thread) => Thread) {
  useChat.setState((s) => (s.threads[id] ? { threads: { ...s.threads, [id]: change(s.threads[id]) } } : {}));
}

function syncCreatedSchedule(chatId: number, scheduleId: number, explicitName?: string) {
  const cs = useCurrentSchedule.getState();
  cs.bumpReload();
  useChat.getState().bindSessionSchedule(chatId, scheduleId);
  if (explicitName) {
    cs.setCurrent({ id: scheduleId, name: explicitName });
    return;
  }
  if (cs.current?.id === scheduleId) return;
  void chatApi.listSchedules().then(
    (list) => {
      const found = list.find((s) => s.id === scheduleId);
      if (found) useCurrentSchedule.getState().setCurrent({ id: found.id, name: found.name });
    },
    () => {},
  );
}

function onEvent(id: number, type: string, data: unknown) {
  if (!isObj(data)) return;
  const open = useWindows.getState().open;
  if (type === 'open_window' && typeof data.program === 'string') {
    // 「워크플로우 창만 포커스」: 도구 프로그램 창은 열지 않는다(질문지는 답이 필요해 예외).
    if (useAgentView.getState().mode === 'workflow' && data.program !== 'questionnaire' && data.program !== 'workflow') return;
    const params = isObj(data.params) ? Object.fromEntries(Object.entries(data.params).map(([k, v]) => [k, String(v)])) : {};
    // 질문지 창은 이 대화를 알아야 제출 뒤 이어 갈 수 있다(Task 15).
    open(data.program, data.program === 'questionnaire' && params.id ? { ...params, session: String(id) } : params);
    return;
  }
  if (type === 'questionnaire' && data.id !== undefined) open('questionnaire', { id: String(data.id), session: String(id) });
  const av = useAgentView.getState();
  if (type === 'card') {
    av.onCardEvent(data);
    if (data.kind === 'project_created' && typeof data.schedule_id === 'number') {
      syncCreatedSchedule(id, data.schedule_id, typeof data.name === 'string' ? data.name : `일정 ${data.schedule_id}`);
    } else if (data.kind === 'auto_applied' && typeof data.schedule_id === 'number') {
      syncCreatedSchedule(id, data.schedule_id);
    }
  }
  if (type === 'workflow') av.onWorkflowEvent(data);
  else if (type === 'tool_start') av.onToolStart(data);
  else if (type === 'tool_end') av.onToolEnd(data);
  else if (type === 'done') av.onTurnDone();
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
      .postMessage(id, { ...body, ui: currentUi() }, live, controller.signal)
      .then(() => resolve(gen === generation)) // reset(로그아웃)으로 끊겼으면 보내지 않은 것으로
      .catch((err: unknown) => {
        if (gen !== generation) return resolve(false);
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
    useChat.setState((s) => ({ threads: { ...s.threads, [id]: { ...fromDetail(detail), usage: s.threads[id]?.usage ?? null, notice } } }));
  } catch (err) {
    if (gen === generation) patch(id, (t) => ({ ...t, notice: message(err) }));
  }
}

/** 지금 대화(없으면 새로 만들어)에 글을 보낸다. */
async function send(text: string, fileIds?: number[], fileNames?: string[]): Promise<boolean> {
  let id = useChat.getState().currentId;
  if (id !== null && useChat.getState().threads[id]?.streaming) return false;
  if (id === null) {
    const pending = useChat.getState().pendingModel;
    const pendingSid = useChat.getState().pendingScheduleId;
    const initialScheduleId =
      pendingSid !== undefined
        ? pendingSid
        : useCurrentSchedule.getState().creatingNewProject
          ? null
          : (currentUi().schedule_id ?? null);
    try {
      const created = await chatApi.createSession(initialScheduleId);
      id = created.id;
      let appliedModel: ChatModel | null = null;
      if (pending) {
        try {
          appliedModel = await chatApi.setChatModel(id, pending);
        } catch {
          // 모델 저장 실패해도 대화 보내기는 이어 간다
        }
      }
      // 만드는 사이 다른 대화로 옮겼으면 그대로 둔다(글은 새 대화에서 돈다).
      useChat.setState((s) => ({
        sessions: [{ ...created, pending_retries: 0 }, ...s.sessions.filter((x) => x.id !== created.id)],
        threads: { ...s.threads, [created.id]: { ...emptyThread(), model: appliedModel, loaded: true } },
        pendingModel: null,
        pendingScheduleId: undefined,
        ...(s.currentId === null && { currentId: created.id, notice: null }),
      }));
    } catch (err) {
      useChat.setState({ notice: message(err) });
      return false;
    }
  }
  const hasFiles = !!fileIds && fileIds.length > 0;
  const input: TurnInput = hasFiles ? { text, file_ids: fileIds } : { text };
  const userItem: Item = { kind: 'user', key: nextKey(), text, ...(fileNames?.length ? { fileNames } : {}) };
  const ok = await runTurn(id, input, userItem);
  if (ok && hasFiles) {
    const sid = id;
    void chatApi.getSession(sid).then((detail) => {
      if (Array.isArray(detail.files)) patch(sid, (t) => ({ ...t, files: detail.files ?? t.files }));
    }, () => {});
  }
  return ok;
}

async function setModel(model: ChatModel): Promise<void> {
  const id = useChat.getState().currentId;
  if (id === null) {
    useChat.setState({ pendingModel: model });
    return;
  }
  try {
    const saved = await chatApi.setChatModel(id, model);
    patch(id, (t) => ({ ...t, model: saved, notice: null }));
  } catch (err) {
    patch(id, (t) => ({ ...t, notice: message(err) }));
  }
}

async function clearModel(): Promise<void> {
  const id = useChat.getState().currentId;
  if (id === null) {
    useChat.setState({ pendingModel: null });
    return;
  }
  try {
    await chatApi.clearChatModel(id);
    patch(id, (t) => ({ ...t, model: null, notice: null }));
  } catch (err) {
    patch(id, (t) => ({ ...t, notice: message(err) }));
  }
}

/** 질문지 이어 가기 카드: 질문지를 읽어 답·가정을 바로 보인다(못 읽으면 번호만). */
async function submissionContent(questionnaireId: number): Promise<Json> {
  try {
    return submissionFromView(questionnaireId, await chatApi.getQuestionnaire(questionnaireId));
  } catch {
    return { kind: 'questionnaire_submitted', questionnaire_id: questionnaireId };
  }
}

const withRetry = (t: Thread, retry: Retry): Thread =>
  t.retries.some((r) => r.approval_id === retry.approval_id)
    ? t
    : { ...t, retries: [...t.retries, retry].sort((a, b) => a.decided_at.localeCompare(b.decided_at)) };

/** 이어 가기 카드 내용과, 승인 건이면 기다리던 요청(거절되면 되돌린다). */
async function resumeItem(sessionId: number, t: Thread, input: ResumeInput): Promise<{ content: Json; retry?: Retry }> {
  if ('questionnaire_id' in input) return { content: await submissionContent(input.questionnaire_id) };
  const retry = t.retries.find((r) => r.approval_id === input.approval_id);
  patch(sessionId, (x) => ({ ...x, retries: x.retries.filter((r) => r.approval_id !== input.approval_id) }));
  return { content: { kind: 'approval_rejected', approval_id: input.approval_id, title: retry?.title ?? '', note: retry?.note ?? '' }, retry };
}

async function resume(sessionId: number, input: ResumeInput) {
  const key = 'questionnaire_id' in input ? `q:${sessionId}:${input.questionnaire_id}` : `a:${sessionId}:${input.approval_id}`;
  if (handled.has(key)) return;
  handled.add(key);
  const gen = generation;
  await openSession(sessionId);
  const t = useChat.getState().threads[sessionId];
  const failed = 'questionnaire_id' in input ? input : null;
  if (gen !== generation || !t || t.streaming) {
    handled.delete(key);
    if (t && gen === generation) patch(sessionId, (x) => ({ ...x, notice: BUSY, failedResume: failed ?? x.failedResume }));
    return;
  }
  patch(sessionId, (x) => ({ ...x, failedResume: null }));
  const { content, retry } = await resumeItem(sessionId, t, input);
  if (gen !== generation) return;
  if (await runTurn(sessionId, input, { kind: 'system', key: nextKey(), content })) return;
  handled.delete(key);
  if (gen !== generation) return;
  // 거절됐다(409·422 등): 다시 짜기 요청 카드를 돌려놓고, 질문지는 [다시 이어 가기]를 보인다.
  patch(sessionId, (x) => (retry ? withRetry(x, retry) : { ...x, failedResume: failed }));
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
  loadSessions,
  openSession,
  newChat: (explicitScheduleId) =>
    set({
      currentId: null,
      pendingModel: null,
      notice: null,
      pendingScheduleId: explicitScheduleId,
    }),
  bindSessionSchedule: (sessionId, scheduleId) =>
    set((s) => ({
      sessions: s.sessions.map((item) => (item.id === sessionId ? { ...item, schedule_id: scheduleId } : item)),
    })),
  send,
  setModel,
  clearModel,
  resume,
  stop,
  reset,
}));

// Context 패널 「AI」 탭의 답이 끝나면, 그 대화를 여기서 열어 두었을 때(「전체 화면으로」) 다시 읽어 잇는다.
useAiChat.subscribe((s, prev) => {
  const { currentId, threads } = useChat.getState();
  if (prev.busy && !s.busy && s.sessionId !== null && s.sessionId === currentId && !threads[currentId]?.streaming) void openSession(currentId);
});

// 다른 곳(승인함 등)에서 프로젝트가 승인되면 서버가 묶은 대화의 일정을 목록에 다시 읽어 온다.
useCurrentSchedule.subscribe((s, prev) => {
  if (s.reloadToken !== prev.reloadToken && useChat.getState().sessions.length > 0) void loadSessions();
});

// 사용자가 바뀌면(로그아웃 포함) 앞 사람의 대화·도는 답을 지운다.
useSession.subscribe((s, prev) => {
  if (s.session?.user.id !== prev.session?.user.id) useChat.getState().reset();
});
