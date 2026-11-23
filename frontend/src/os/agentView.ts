// 에이전트 실시간 작업 화면 연출 (Computer Use 뷰) · 상단 얇은 워크플로우 진행 리본 상태·안무 큐.
import { create } from 'zustand';
import { scheduleStore } from '../shared/schedule/scheduleStore';
import { toolLabel } from '../shared/toolLabels';
import { useCurrentSchedule } from './currentSchedule';
import { loadPref, savePref } from './prefs';
import { resolveProgram } from './registry';
import { useSession } from './session';
import { RIBBON_H, SCHEDULE_BOUND_PROGRAMS, useWindows } from './windowStore';

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

export interface RibbonStep {
  n: number;
  tool: string;
  label: string;
  program: string | null;
  status: 'running' | 'done' | 'failed' | 'stopped';
}

export interface WorkflowRibbonState {
  visible: boolean;
  collapsed: boolean;
  runId: number | null;
  status: 'idle' | 'running' | 'waiting' | 'done' | 'stopped' | 'failed';
  waitReason: 'answer' | 'approval' | null;
  steps: RibbonStep[];
  genStage: string | null;
  creatingNewProject: boolean;
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

const EMPTY_RIBBON: WorkflowRibbonState = {
  visible: false,
  collapsed: false,
  runId: null,
  status: 'idle',
  waitReason: null,
  steps: [],
  genStage: null,
  creatingNewProject: false,
};


const TOOL_PROGRAM_FALLBACK: Record<string, string> = {
  'schedule.read': 'schedule-table',
  'schedule.find': 'schedule-table',
  'schedule.activity_detail': 'schedule-table',
  'schedule.record_actual': 'schedule-table',
  'schedule.import': 'schedule-table',
  'schedule.create_project': 'schedule-table',
  'schedule.list': 'explorer',
  'calc.cpm': 'cpm',
  'harness.check': 'conditions',
  'conditions.list': 'conditions',
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
  'files.set_axes': 'library',
  'evidence.search': 'library',
  'evidence.attach': 'library',
  'info.weather': 'library',
  'progress.read': 'progress',
  'report.learn_template': 'reports',
  'report.generate': 'reports',
  'report.list_templates': 'reports',
  'report.revise': 'reports',
  'visual.make': 'progress',
};

/** 새 프로젝트 생성 중에는 기존 일정의 조건·간트·자료실 창을 자동으로 띄우지 않는다. */
const NEW_PROJECT_GENERATION_TOOLS = new Set([
  'generate.extract_conditions',
  'generate.run',
  'evidence.search',
  'evidence.attach',
]);

const STAGE_WORKFLOW_MS = 900;
const STAGE_TOOL_MS = 1200;
const STAGE_DONE_MS = 1000;
const RIBBON_COLLAPSE_MS = 1800;

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
  creatingNewProject = false,
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

  if (NEW_PROJECT_GENERATION_TOOLS.has(tool) && !args?.schedule_id) {
    return { programId: null };
  }

  if (tool === 'ask.questionnaire') {
    const questions = args?.questions;
    if (Array.isArray(questions) && questions.length <= 2) return { programId: null };
    if (!args?.id && !args?.questionnaire_id) return { programId: null };
  }

  let mapped: string | null = program ? resolveProgram(program).id : (TOOL_PROGRAM_FALLBACK[tool] ?? null);
  if (!mapped) return { programId: null };

  const params: Record<string, string> = {};
  const explicitSid = args?.schedule_id;
  const fallbackSid =
    creatingNewProject && SCHEDULE_BOUND_PROGRAMS.has(mapped)
      ? undefined
      : useCurrentSchedule.getState().current?.id;
  const sid = explicitSid ?? fallbackSid;
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
let ribbonCollapseTimer: ReturnType<typeof setTimeout> | null = null;
let queueGen = 0;

function clearRibbonTimer() {
  if (ribbonCollapseTimer !== null) {
    clearTimeout(ribbonCollapseTimer);
    ribbonCollapseTimer = null;
  }
}

function clearCueTimers() {
  if (cueTimer !== null) clearTimeout(cueTimer);
  if (finishTimer !== null) clearTimeout(finishTimer);
  clearRibbonTimer();
  cueTimer = null;
  finishTimer = null;
  cueQueue = [];
  cueRunning = false;
  queueGen += 1;
}

function syncTopInset(ribbon: WorkflowRibbonState) {
  if (!windowSyncEnabled) return;
  const open = ribbon.visible && !ribbon.collapsed && ribbon.steps.length > 0;
  useWindows.getState().setInsetTop?.(open ? RIBBON_H : 0);
}

function applyCue(cue: Cue, set: (fn: (s: AgentViewState) => Partial<AgentViewState>) => void) {
  set(() => ({ focus: { ...cue.focus, active: true } }));
  if (cue.windowProgram && windowSyncEnabled) {
    const winState = useWindows.getState();
    (winState.stageLayout ?? winState.stageFocus)?.(cue.windowProgram, cue.windowParams);
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
  ribbon: WorkflowRibbonState;
  workflowTick: number;
  lastRunId: number | null;
  load(userId: number | null): void;
  setMode(mode: AgentViewMode): void;
  clearFocus(): void;
  toggleRibbon(): void;
  collapseRibbon(): void;
  openFullWorkflow(): void;
  triggerFocus(focus: Omit<AgentFocus, 'active'>, windowProgram?: string | null, windowParams?: Record<string, string>): void;
  onCardEvent(data: Record<string, unknown>): void;
  onWorkflowEvent(data: Record<string, unknown>): void;
  onToolStart(data: Record<string, unknown>): void;
  onToolEnd(data: Record<string, unknown>): void;
  onTurnDone(): void;
  completeWaitingWorkflow(status?: 'done' | 'stopped'): void;
  reset(): void;
}

function mergeStep(steps: RibbonStep[], nextStep: RibbonStep): RibbonStep[] {
  const idx = steps.findIndex((s) => s.n === nextStep.n);
  if (idx === -1) return [...steps, nextStep].sort((a, b) => a.n - b.n);
  return steps.map((s, i) => (i === idx ? nextStep : s));
}

function validStepStatus(raw: unknown): RibbonStep['status'] {
  return raw === 'done' || raw === 'failed' || raw === 'stopped' ? raw : 'running';
}

function validRibbonStatus(raw: unknown): WorkflowRibbonState['status'] {
  return raw === 'waiting' || raw === 'done' || raw === 'stopped' || raw === 'failed' ? raw : 'running';
}

function inferWaitReason(steps: RibbonStep[]): 'answer' | 'approval' | null {
  for (let i = steps.length - 1; i >= 0; i -= 1) {
    const tool = steps[i].tool;
    if (tool === 'ask.questionnaire') return 'answer';
    // schedule.import 는 만든 초안을 승인함에 낸다(서버 loop 가 승인을 기다릴 때만 waiting 으로 둔다).
    if (tool === 'out.submit_change' || tool === 'scenario.submit' || tool === 'rules.propose' || tool === 'schedule.import') {
      return 'approval';
    }
  }
  return null;
}

/** 현재 실행/대기 중인 일정 생성 흐름에서 아직 남아 있는 후속 예정 단계를 돌려준다. */
export function plannedGhostSteps(
  steps: RibbonStep[],
  status: WorkflowRibbonState['status'],
  creatingNewProject: boolean,
): string[] {
  if (status !== 'running' && status !== 'waiting') return [];
  const hasAsk = steps.some((s) => s.tool === 'ask.questionnaire');
  const hasExtract = steps.some((s) => s.tool === 'generate.extract_conditions');
  const hasGenerate = steps.some((s) => s.tool === 'generate.run');
  const hasSubmit = steps.some(
    (s) => s.tool === 'out.submit_change' || s.tool === 'scenario.submit' || s.tool === 'rules.propose',
  );
  if (hasSubmit) {
    return status === 'waiting' ? ['최종 승인'] : [];
  }
  const nonGenFlow = steps.some((s) => s.tool.startsWith('delay.') || s.tool.startsWith('shorten.'));
  if (creatingNewProject || hasExtract || hasGenerate || (status === 'waiting' && hasAsk && !nonGenFlow)) {
    const planned: string[] = [];
    if (!hasExtract && !hasGenerate) planned.push('조건 뽑기');
    if (!hasGenerate) planned.push('스케줄·WBS 생성');
    planned.push('승인 상신');
    return planned;
  }
  return [];
}

export const useAgentView = create<AgentViewState>((set, get) => {
  const enqueue = (cue: Cue) => {
    cueQueue.push(cue);
    drainQueue(set);
  };

  const scheduleRibbonCollapse = () => {
    clearRibbonTimer();
    if (!pacingEnabled) return;
    ribbonCollapseTimer = setTimeout(() => {
      ribbonCollapseTimer = null;
      const next = { ...get().ribbon, collapsed: true };
      set({ ribbon: next });
      syncTopInset(next);
    }, RIBBON_COLLAPSE_MS);
  };

  return {
    userId: null,
    mode: 'stage',
    focus: EMPTY_FOCUS,
    ribbon: EMPTY_RIBBON,
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
      const nextRibbon = { ...EMPTY_RIBBON };
      set({ focus: EMPTY_FOCUS, ribbon: nextRibbon });
      syncTopInset(nextRibbon);
    },

    toggleRibbon() {
      clearRibbonTimer();
      const cur = get().ribbon;
      if (!cur.visible && cur.steps.length === 0) {
        if (get().lastRunId !== null) {
          useWindows.getState().open('workflow', { run: String(get().lastRunId) });
        }
        return;
      }
      const collapsed = !cur.visible ? false : !cur.collapsed;
      const next: WorkflowRibbonState = { ...cur, visible: true, collapsed };
      set({ ribbon: next });
      syncTopInset(next);
    },

    collapseRibbon() {
      clearRibbonTimer();
      const next: WorkflowRibbonState = { ...get().ribbon, collapsed: true };
      set({ ribbon: next });
      syncTopInset(next);
    },

    openFullWorkflow() {
      const rid = get().ribbon.runId ?? get().lastRunId;
      useWindows.getState().open('workflow', rid !== null ? { run: String(rid) } : undefined);
    },

    triggerFocus(focus, windowProgram, windowParams) {
      applyCue({ focus, windowProgram: windowProgram ?? focus.programId, windowParams, holdMs: 0 }, set);
    },

    onCardEvent(data) {
      if (data.kind === 'generation' && typeof data.stage === 'string') {
        set((s) => ({ ribbon: { ...s.ribbon, genStage: data.stage as string } }));
      }
    },

    onWorkflowEvent(data) {
      const runId = typeof data.run_id === 'number' ? data.run_id : null;
      const status = validRibbonStatus(data.status);
      const serverWait = data.wait_reason === 'answer' || data.wait_reason === 'approval' ? data.wait_reason : null;
      const rawSteps = Array.isArray(data.steps) ? data.steps : [];
      const steps: RibbonStep[] = rawSteps
        .filter((r): r is Record<string, unknown> => typeof r === 'object' && r !== null)
        .map((r) => {
          const tool = typeof r.tool === 'string' ? r.tool : '';
          return {
            n: typeof r.n === 'number' ? r.n : 1,
            tool,
            label: toolLabel(tool),
            program: typeof r.program === 'string' ? r.program : null,
            status: validStepStatus(r.status),
          };
        });

      const cur = get().ribbon;
      const nextRunId = runId ?? cur.runId;
      const resetSteps = cur.runId !== null && nextRunId !== null && cur.runId !== nextRunId;
      const mergedSteps = steps.length > 0 ? steps : resetSteps ? [] : cur.steps;
      const keepOpen = status === 'running' || status === 'waiting';
      const nextRibbon: WorkflowRibbonState = {
        ...cur,
        visible: mergedSteps.length > 0 ? true : cur.visible,
        collapsed: keepOpen ? false : cur.collapsed,
        runId: nextRunId,
        status,
        // 서버가 실은 까닭(answer·approval)이 먼저 — 없으면(예전 사건) 마지막 단계로 짐작
        waitReason: status === 'waiting' ? (serverWait ?? inferWaitReason(mergedSteps)) : null,
        steps: mergedSteps,
        creatingNewProject: keepOpen ? (resetSteps ? false : cur.creatingNewProject) : false,
        ...(status !== 'running' ? { genStage: null } : {}),
      };
      if (keepOpen) clearRibbonTimer();
      set((s) => ({
        workflowTick: s.workflowTick + 1,
        ...(runId !== null ? { lastRunId: runId } : {}),
        ribbon: nextRibbon,
      }));
      syncTopInset(nextRibbon);
      if (!keepOpen && nextRibbon.visible && nextRibbon.steps.length > 0) scheduleRibbonCollapse();
    },

    onToolStart(data) {
      clearRibbonTimer();
      const runId = typeof data.run_id === 'number' ? data.run_id : get().lastRunId;
      const stepN = typeof data.n === 'number' ? data.n : 1;
      const tool = typeof data.tool === 'string' ? data.tool : '';
      const program = typeof data.program === 'string' ? data.program : null;
      const argsText = typeof data.arguments === 'string' ? data.arguments : undefined;
      const args = parseArgs(argsText);
      const labelName = toolLabel(tool);
      const totalSteps = Math.max(stepN, get().focus.totalSteps);

      // 현장 관리자는 새 일정을 만들 수 없다(서버 도구가 거절, F4) — 「새 프로젝트 생성 중」으로 바꾸지 않는다.
      const isGenCreation =
        (tool === 'generate.extract_conditions' ||
          tool === 'generate.run' ||
          tool === 'schedule.create_project' ||
          (tool === 'ask.questionnaire' && args?.purpose === 'generate')) &&
        !args?.schedule_id &&
        useSession.getState().session?.user.role !== 'field';

      if (isGenCreation && !useCurrentSchedule.getState().creatingNewProject) {
        useCurrentSchedule.getState().enterNewProjectMode();
      }

      const prevRibbon = get().ribbon;
      const isNewRun = prevRibbon.runId !== null && runId !== null && prevRibbon.runId !== runId;
      const creatingNewProject = isGenCreation || (!isNewRun && (prevRibbon.creatingNewProject || useCurrentSchedule.getState().creatingNewProject));
      const baseSteps = isNewRun ? [] : prevRibbon.steps;
      const nextSteps = mergeStep(baseSteps, {
        n: stepN,
        tool,
        label: labelName,
        program,
        status: 'running',
      });
      const nextRibbon: WorkflowRibbonState = {
        visible: true,
        collapsed: false,
        runId,
        status: 'running',
        waitReason: null,
        steps: nextSteps,
        genStage: isNewRun ? null : prevRibbon.genStage,
        creatingNewProject,
      };

      set((s) => ({
        workflowTick: s.workflowTick + 1,
        ...(runId !== null ? { lastRunId: runId } : {}),
        ribbon: nextRibbon,
      }));
      syncTopInset(nextRibbon);

      const mode = get().mode;
      if (mode === 'off') return;
      sawToolInTurn = true;
      if (!windowSyncEnabled) return;

      if (mode === 'workflow') {
        const wfParams = runId !== null ? { run: String(runId) } : undefined;
        enqueue({
          windowProgram: 'workflow',
          windowParams: wfParams,
          holdMs: 0,
          focus: {
            runId,
            programId: 'workflow',
            stepN,
            totalSteps,
            tool,
            status: 'workflow',
            label: `워크플로우${runId ? ` #${runId}` : ''} · ${stepN}단계 [${labelName}]`,
          },
        });
        return;
      }

      const target = resolveToolTarget(tool, program, argsText, creatingNewProject);
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
      } else {
        set({
          focus: {
            active: true,
            runId,
            programId: null,
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
      // 지연 기록 도구는 버전을 바꾸지 않는다 — 기록된 지연 띠가 다시 세게 따로 알린다.
      if (data.ok === true && typeof data.tool === 'string' && data.tool.startsWith('delay.')) useCurrentSchedule.getState().bumpDelays();
      const stepN = typeof data.n === 'number' ? data.n : null;
      const ok = data.ok !== false;
      set((s) => ({
        workflowTick: s.workflowTick + 1,
        focus: s.focus.active ? { ...s.focus, status: 'done' } : s.focus,
        ribbon: {
          ...s.ribbon,
          steps: s.ribbon.steps.map((st) =>
            stepN === null || st.n === stepN ? { ...st, status: ok ? 'done' : 'failed' } : st,
          ),
        },
      }));
    },

    onTurnDone() {
      const { mode, lastRunId, focus, ribbon } = get();
      const ranTools = sawToolInTurn;
      sawToolInTurn = false;
      const waitReason =
        ribbon.status === 'waiting' ? (ribbon.waitReason ?? inferWaitReason(ribbon.steps)) : null;
      const nextStatus: WorkflowRibbonState['status'] =
        ribbon.status === 'stopped' || ribbon.status === 'failed' || ribbon.status === 'waiting'
          ? ribbon.status
          : 'done';
      const completedRibbon: WorkflowRibbonState = {
        ...ribbon,
        status: nextStatus,
        waitReason,
        genStage: null,
        steps: ribbon.steps.map((st) => (st.status === 'running' ? { ...st, status: 'done' } : st)),
        ...(nextStatus === 'waiting' ? {} : { creatingNewProject: false }),
      };
      set({ ribbon: completedRibbon });
      syncTopInset(completedRibbon);
      if (completedRibbon.visible && completedRibbon.steps.length > 0 && nextStatus !== 'waiting') {
        scheduleRibbonCollapse();
      }

      if (mode === 'off' || lastRunId === null || !ranTools || !windowSyncEnabled) {
        if (focus.active) set({ focus: EMPTY_FOCUS });
        return;
      }
      const total = Math.max(1, focus.totalSteps);
      if (mode === 'workflow') {
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
      }
      const hasChat = useWindows.getState().wins.some((w) => w.programId === 'chat');
      enqueue({
        windowProgram: hasChat ? 'chat' : null,
        holdMs: 0,
        clearAfterMs: STAGE_DONE_MS,
        focus: {
          runId: lastRunId,
          programId: hasChat ? 'chat' : mode === 'workflow' ? 'workflow' : null,
          stepN: total,
          totalSteps: total,
          tool: null,
          status: 'done',
          label:
            nextStatus === 'waiting'
              ? waitReason === 'approval'
                ? '승인 대기 — 승인함에서 검토 후 결정해 주세요'
                : '답변 대기 — 질문에 답하면 이어서 생성합니다'
              : '작업 완료 — 결과를 대화창에서 확인하세요',
        },
      });
    },

    completeWaitingWorkflow(status = 'done') {
      const cur = get().ribbon;
      set((s) => ({ workflowTick: s.workflowTick + 1 }));
      if (cur.status !== 'waiting' && cur.status !== 'running') return;
      clearRibbonTimer();
      const nextRibbon: WorkflowRibbonState = {
        ...cur,
        status,
        waitReason: null,
        genStage: null,
        creatingNewProject: false,
        steps: cur.steps.map((st) =>
          st.status === 'running' ? { ...st, status: status === 'stopped' ? 'stopped' : 'done' } : st,
        ),
      };
      set({ ribbon: nextRibbon });
      syncTopInset(nextRibbon);
      if (nextRibbon.visible && nextRibbon.steps.length > 0) {
        scheduleRibbonCollapse();
      }
    },

    reset() {
      clearCueTimers();
      sawToolInTurn = false;
      set({ userId: null, mode: 'stage', focus: EMPTY_FOCUS, ribbon: EMPTY_RIBBON, workflowTick: 0, lastRunId: null });
    },
  };
});
