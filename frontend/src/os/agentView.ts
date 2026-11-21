// 에이전트 실시간 작업 화면 연출 (Computer Use 뷰) 상태·안무 큐.
// 워크플로우 열림 → 노드 실시간 생성 → 각 단계별 도구 프로그램 스테이지 전환·전면 포커스를 조율한다.
import { create } from 'zustand';
import { scheduleStore } from '../shared/schedule/scheduleStore';
import { useCurrentSchedule } from './currentSchedule';
import { loadPref, savePref } from './prefs';
import { resolveProgram } from './registry';
import { useWindows } from './windowStore';

export type AgentViewMode = 'stage' | 'workflow' | 'off';

export interface AgentFocus {
  active: boolean;
  runId: number | null;
  programId: string | null;
  stepN: number;
  totalSteps: number;
  tool: string | null;
  label: string;
  status: 'workflow' | 'running' | 'done';
}

const EMPTY_FOCUS: AgentFocus = {
  active: false,
  runId: null,
  programId: null,
  stepN: 0,
  totalSteps: 0,
  tool: null,
  label: '',
  status: 'workflow',
};

const TOOL_NAMES: Record<string, string> = {
  'schedule.read': '일정 읽기',
  'schedule.find': '액티비티 찾기',
  'schedule.record_actual': '실적 반영',
  'schedule.import': '공정표 가져오기',
  'calc.cpm': '주공정(CPM) 계산',
  'harness.check': '조건 점검',
  'generate.extract_conditions': '입력 조건 뽑기',
  'generate.run': '스케줄·WBS 생성',
  'delay.record': '지연 기록',
  'delay.analyze': '지연 영향 분석',
  'shorten.make': '만회·단축안 생성',
  'scenario.create': '대안 시나리오 생성',
  'scenario.submit': '시나리오 승인 상신',
  'rules.propose': '내 규칙 제안',
  'out.submit_change': '변경 승인 상신',
  'ask.questionnaire': '질문지 생성',
  'ask.fill_answers': '질문지 답 채우기',
  'files.search': '자료함 검색',
  'files.read': '문서 읽기',
  'evidence.search': '공기·기준 근거 검색',
  'evidence.attach': '근거 연결',
  'info.weather': '기상청 근거 조회',
  'visual.make': '보고서 그림 생성',
  'ui.open_window': '프로그램 창 열기',
};

const TOOL_PROGRAM_FALLBACK: Record<string, string> = {
  'schedule.read': 'schedule-table',
  'schedule.find': 'schedule-table',
  'schedule.record_actual': 'schedule-table',
  'schedule.import': 'schedule-table',
  'calc.cpm': 'cpm',
  'harness.check': 'conditions',
  'generate.extract_conditions': 'conditions',
  'generate.run': 'gantt',
  'delay.record': 'delays',
  'delay.analyze': 'delays',
  'shorten.make': 'delays',
  'scenario.create': 'compare',
  'scenario.submit': 'approvals',
  'rules.propose': 'conditions',
  'out.submit_change': 'approvals',
  'ask.fill_answers': 'questionnaire',
  'files.search': 'library',
  'files.read': 'library',
  'evidence.search': 'library',
  'evidence.attach': 'library',
  'info.weather': 'library',
  'visual.make': 'progress',
};

const STAGE_WORKFLOW_MS = 480;
const STAGE_TOOL_MS = 720;
const STAGE_DONE_MS = 900;

let pacingEnabled = import.meta.env.MODE !== 'test';
let windowSyncEnabled = import.meta.env.MODE !== 'test';
let sawToolInTurn = false;

/** 테스트 전용: 브라우저 시각 딜레이 켜기/끄기. */
export function setAgentViewPacing(on: boolean): void {
  pacingEnabled = on;
}

/** 테스트 전용: 시험 환경에서 스테이지 창 자동 열기/전환 스위치(windowMotion.setWindowMotion 과 같은 규약). */
export function setAgentWindowSync(on: boolean): void {
  windowSyncEnabled = on;
}

function validMode(raw: unknown): AgentViewMode {
  return raw === 'stage' || raw === 'workflow' || raw === 'off' ? raw : 'stage';
}

function parseArgs(argumentsText?: string): Record<string, unknown> | null {
  if (!argumentsText) return null;
  try {
    const parsed = JSON.parse(argumentsText);
    return typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

export function resolveToolTarget(
  tool: string,
  program: string | null,
  argumentsText?: string,
): { programId: string | null; params?: Record<string, string> } {
  const args = parseArgs(argumentsText);
  if (tool === 'ui.open_window' && args && typeof args.program === 'string') {
    const resolved = resolveProgram(args.program);
    const params: Record<string, string> = {};
    if (args.params && typeof args.params === 'object') {
      for (const [k, v] of Object.entries(args.params as Record<string, unknown>)) params[k] = String(v);
    }
    return { programId: resolved.id, params: Object.keys(params).length ? { ...resolved.params, ...params } : resolved.params };
  }

  let mapped: string | null = program ? resolveProgram(program).id : (TOOL_PROGRAM_FALLBACK[tool] ?? null);
  if (tool === 'ask.questionnaire' && !args?.id && !args?.questionnaire_id) {
    mapped = null;
  }
  if (!mapped) return { programId: null };

  const params: Record<string, string> = {};
  const sid = args?.schedule_id ?? useCurrentSchedule.getState().current?.id;
  if (sid !== undefined && sid !== null) params.id = String(sid);
  const act = args?.activity_id ?? args?.id;
  if (typeof act === 'string' && act) params.activity = act;
  if (tool === 'ask.fill_answers' && (args?.questionnaire_id || args?.id)) {
    params.id = String(args.questionnaire_id ?? args.id);
  }
  return { programId: mapped, params: Object.keys(params).length ? params : undefined };
}

interface Cue {
  focus: Omit<AgentFocus, 'active'>;
  windowProgram: string | null;
  windowParams?: Record<string, string>;
  holdMs: number;
  clearAfterMs?: number;
}

let cueQueue: Cue[] = [];
let cueRunning = false;
let cueTimer: ReturnType<typeof setTimeout> | null = null;
let finishTimer: ReturnType<typeof setTimeout> | null = null;
let queueGen = 0;

function clearCueTimers() {
  if (cueTimer !== null) clearTimeout(cueTimer);
  if (finishTimer !== null) clearTimeout(finishTimer);
  cueTimer = null;
  finishTimer = null;
  cueQueue = [];
  cueRunning = false;
  queueGen += 1;
}

function applyCue(cue: Cue, set: (fn: (s: AgentViewState) => Partial<AgentViewState>) => void) {
  set(() => ({ focus: { ...cue.focus, active: true } }));
  if (cue.windowProgram && windowSyncEnabled) {
    useWindows.getState().stageFocus?.(cue.windowProgram, cue.windowParams);
  }
  if (cue.clearAfterMs !== undefined) {
    const gen = queueGen;
    const clear = () => {
      if (gen !== queueGen) return;
      set(() => ({ focus: EMPTY_FOCUS }));
    };
    if (!pacingEnabled || cue.clearAfterMs <= 0) clear();
    else finishTimer = setTimeout(clear, cue.clearAfterMs);
  }
}

function drainQueue(set: (fn: (s: AgentViewState) => Partial<AgentViewState>) => void) {
  if (cueRunning) return;
  const next = cueQueue.shift();
  if (!next) return;
  if (!pacingEnabled || next.holdMs <= 0) {
    applyCue(next, set);
    drainQueue(set);
    return;
  }
  cueRunning = true;
  const gen = queueGen;
  applyCue(next, set);
  cueTimer = setTimeout(() => {
    cueTimer = null;
    if (gen !== queueGen) return;
    cueRunning = false;
    drainQueue(set);
  }, next.holdMs);
}

interface AgentViewState {
  userId: number | null;
  mode: AgentViewMode;
  focus: AgentFocus;
  workflowTick: number;
  lastRunId: number | null;
  load(userId: number | null): void;
  setMode(mode: AgentViewMode): void;
  clearFocus(): void;
  triggerFocus(focus: Omit<AgentFocus, 'active'>, windowProgram?: string | null, windowParams?: Record<string, string>): void;
  onWorkflowEvent(data: Record<string, unknown>): void;
  onToolStart(data: Record<string, unknown>): void;
  onToolEnd(data: Record<string, unknown>): void;
  onTurnDone(): void;
  reset(): void;
}

export const useAgentView = create<AgentViewState>((set, get) => {
  const enqueue = (cue: Cue) => {
    cueQueue.push(cue);
    drainQueue(set);
  };

  return {
    userId: null,
    mode: 'stage',
    focus: EMPTY_FOCUS,
    workflowTick: 0,
    lastRunId: null,

    load(userId) {
      set({ userId, mode: validMode(loadPref('agentView', userId)) });
    },

    setMode(mode) {
      savePref('agentView', get().userId, mode);
      if (mode === 'off') clearCueTimers();
      set({ mode, ...(mode === 'off' ? { focus: EMPTY_FOCUS } : {}) });
    },

    clearFocus() {
      clearCueTimers();
      set({ focus: EMPTY_FOCUS });
    },

    triggerFocus(focus, windowProgram, windowParams) {
      applyCue({ focus, windowProgram: windowProgram ?? focus.programId, windowParams, holdMs: 0 }, set);
    },

    onWorkflowEvent(data) {
      const runId = typeof data.run_id === 'number' ? data.run_id : null;
      set((s) => ({
        workflowTick: s.workflowTick + 1,
        ...(runId !== null ? { lastRunId: runId } : {}),
      }));
    },

    onToolStart(data) {
      const runId = typeof data.run_id === 'number' ? data.run_id : get().lastRunId;
      const stepN = typeof data.n === 'number' ? data.n : 1;
      const tool = typeof data.tool === 'string' ? data.tool : '';
      const program = typeof data.program === 'string' ? data.program : null;
      const argsText = typeof data.arguments === 'string' ? data.arguments : undefined;
      const labelName = TOOL_NAMES[tool] ?? tool;
      const totalSteps = Math.max(stepN, get().focus.totalSteps);

      set((s) => ({
        workflowTick: s.workflowTick + 1,
        ...(runId !== null ? { lastRunId: runId } : {}),
      }));

      const mode = get().mode;
      if (mode === 'off') return;
      sawToolInTurn = true;
      if (!windowSyncEnabled) return;

      const wfParams = runId !== null ? { run: String(runId) } : undefined;
      enqueue({
        windowProgram: 'workflow',
        windowParams: wfParams,
        holdMs: mode === 'stage' ? STAGE_WORKFLOW_MS : 0,
        focus: {
          runId,
          programId: 'workflow',
          stepN,
          totalSteps,
          tool,
          status: 'workflow',
          label: `워크플로우${runId ? ` #${runId}` : ''} · ${stepN}단계 [${labelName}] 노드 생성`,
        },
      });

      if (mode === 'workflow') return;

      const target = resolveToolTarget(tool, program, argsText);
      if (target.programId && target.programId !== 'workflow') {
        enqueue({
          windowProgram: target.programId,
          windowParams: target.params,
          holdMs: STAGE_TOOL_MS,
          focus: {
            runId,
            programId: target.programId,
            stepN,
            totalSteps,
            tool,
            status: 'running',
            label: `${stepN}단계 실행 중 · ${labelName}`,
          },
        });
      }
    },

    onToolEnd(data) {
      const sid = useCurrentSchedule.getState().current?.id;
      if (typeof sid === 'number' && data.ok === true) {
        const store = scheduleStore(sid);
        if (store.getState().view) void store.getState().load();
      }
      set((s) => ({
        workflowTick: s.workflowTick + 1,
        focus: s.focus.active ? { ...s.focus, status: 'done' } : s.focus,
      }));
    },

    onTurnDone() {
      const { mode, lastRunId, focus } = get();
      const ranTools = sawToolInTurn;
      sawToolInTurn = false;
      if (mode === 'off' || lastRunId === null || !ranTools || !windowSyncEnabled) {
        if (focus.active) set({ focus: EMPTY_FOCUS });
        return;
      }
      const total = Math.max(1, focus.totalSteps);
      enqueue({
        windowProgram: 'workflow',
        windowParams: { run: String(lastRunId) },
        holdMs: STAGE_DONE_MS / 2,
        focus: {
          runId: lastRunId,
          programId: 'workflow',
          stepN: total,
          totalSteps: total,
          tool: null,
          status: 'done',
          label: `워크플로우 #${lastRunId} 실행 완료 (${total}단계)`,
        },
      });
      const hasChat = useWindows.getState().wins.some((w) => w.programId === 'chat');
      enqueue({
        windowProgram: hasChat ? 'chat' : null,
        holdMs: 0,
        clearAfterMs: STAGE_DONE_MS,
        focus: {
          runId: lastRunId,
          programId: hasChat ? 'chat' : 'workflow',
          stepN: total,
          totalSteps: total,
          tool: null,
          status: 'done',
          label: '작업 완료 — 결과를 대화창에서 확인하세요',
        },
      });
    },

    reset() {
      clearCueTimers();
      sawToolInTurn = false;
      set({ userId: null, mode: 'stage', focus: EMPTY_FOCUS, workflowTick: 0, lastRunId: null });
    },
  };
});
