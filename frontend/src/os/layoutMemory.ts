// 열어 둔 창·탭의 모양(화면 형태 desktop·tablet·phone 마다). 저장·서버 맞춤은 layoutSync.ts.
// 되살릴 때마다 다시 거른다: 그 사람이 지금 열 수 있는 프로그램만(관리자 전용·현장 제외·없어진 id 는 버림),
// params 는 프로그램이 이미 받는 id·탭 이름만(보낼 글·통화 초안·물어볼 말·이어 가기·새 기록 양식은 남기지 않는다 —
// 다시 열었을 때 보내기·걸기·묻기가 다시 시작되면 안 된다). 번호 꼴 값(8자리 이상)은 id 칸에 들어가지 못한다.
// 모양이 틀리면 null(→ 첫 화면). 서버 검사(app/programs/ui_state/schemas.py)와 같은 모양이다.
import { programs, resolveProgram } from './registry';
import type { Role } from './session';
import { tabletCatalog } from './tabletRailStore';
import { isClosing } from './windowMotion';
import type { RestoredWin, Win } from './windowStore';

export type LayoutMode = 'desktop' | 'tablet' | 'phone';
export type Params = Record<string, string>;
/** 한 화면 형태에서 맨 앞에 있던 프로그램(다른 기기에서 이어 열 것). */
export interface Focus {
  program: string;
  params?: Params;
}

const NUM = /^[1-9]\d{0,6}$/; // id 는 7자리까지 — 가장 짧은 전화번호(8자리)가 들어갈 수 없다
const NAME = /^[a-z][a-z-]{0,30}$/;
const NUM_KEYS = new Set(['id', 'contact', 'session', 'run']);
/** 프로그램마다 남기는 params. 여기 없는 프로그램·칸은 남기지 않는다. */
const KEEP: Record<string, readonly string[]> = {
  chat: ['session'],
  questionnaire: ['id', 'session'],
  workflow: ['run'],
  approvals: ['id'],
  settings: ['section'],
  devconsole: ['tab'],
  'schedule-table': ['id'],
  gantt: ['id'],
  cpm: ['id'],
  compare: ['id'],
  conditions: ['id'],
  delays: ['id'],
  progress: ['view'],
  contacts: ['id', 'contact', 'tab'],
};
const ENUMS: Record<string, Record<string, readonly string[]>> = {
  contacts: { tab: ['messages', 'calls'] },
  progress: { view: ['field', 'dashboard'] },
};

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v);

/** 남겨도 되는 params 만. 없으면 undefined. */
export function keptParams(programId: string, params: unknown): Params | undefined {
  if (!isObj(params)) return undefined;
  const out: Params = {};
  for (const key of KEEP[programId] ?? []) {
    const v = params[key];
    if (typeof v !== 'string') continue;
    const allowed = ENUMS[programId]?.[key];
    if (allowed ? allowed.includes(v) : (NUM_KEYS.has(key) ? NUM : NAME).test(v)) out[key] = v;
  }
  return Object.keys(out).length ? out : undefined;
}

/** 지금 이 사람이 열 수 있는 프로그램 id(옛 id 는 지금 id 로). 없으면 null. */
export function allowedProgram(role: Role, id: unknown): string | null {
  if (typeof id !== 'string') return null;
  const resolved = resolveProgram(id).id;
  return programs(role).some((p) => p.id === resolved) ? resolved : null;
}

const withParams = (params: Params | undefined) => (params ? { params } : {});
const withoutView = (params: Params | undefined) => {
  if (!params) return undefined;
  const rest = { ...params };
  delete rest.view;
  return Object.keys(rest).length ? rest : undefined;
};

// ── 데스크톱 ──

export interface SavedWin {
  program: string;
  x: number;
  y: number;
  w: number;
  h: number;
  min: boolean;
  max: boolean;
  params?: Params;
}
export interface DesktopLayout {
  v: 1;
  /** 뒤 → 앞 차례. */
  wins: SavedWin[];
  deactivated: boolean;
}

const LIMIT = 20000;
const bound = (n: number, lo: number) => Math.max(lo, Math.min(LIMIT, Math.round(n)));

const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);

/** 저장할 창 하나. 자리가 깨진 창(NaN·무한)은 null — 서버가 거절할 모양을 보내지 않는다. */
function toSaved(w: RestoredWin): SavedWin | null {
  if (![w.x, w.y, w.w, w.h].every(finite)) return null;
  return {
    program: w.programId,
    x: bound(w.x, -LIMIT),
    y: bound(w.y, -LIMIT),
    w: bound(w.w, 0),
    h: bound(w.h, 0),
    min: w.minimized,
    max: w.maximized,
    ...withParams(keptParams(w.programId, w.params)),
  };
}

/** 되살릴 창 목록(뒤 → 앞)을 저장 모양으로. 화면에 맞추기 전 자리 그대로다. */
export function savedDesktop(l: { wins: RestoredWin[]; deactivated: boolean }): DesktopLayout {
  return { v: 1, wins: l.wins.map(toSaved).filter((w): w is SavedWin => w !== null), deactivated: l.deactivated };
}

/** 지금 창 배치(닫히는 중인 창은 뺀다). */
export function desktopLayout(s: { wins: Win[]; deactivated: boolean }): DesktopLayout {
  return savedDesktop({ wins: s.wins.filter((w) => !isClosing(w)).sort((a, b) => a.z - b.z), deactivated: s.deactivated });
}

/** 저장된 배치 → 되살릴 창. 모양이 틀리면 null. 열 수 없는 프로그램·겹친 프로그램은 뺀다. */
export function readDesktop(raw: unknown, role: Role): { wins: RestoredWin[]; deactivated: boolean } | null {
  if (!isObj(raw) || raw.v !== 1 || !Array.isArray(raw.wins) || raw.wins.length > 40 || typeof raw.deactivated !== 'boolean') return null;
  const wins: RestoredWin[] = [];
  for (const e of raw.wins) {
    if (!isObj(e) || ![e.x, e.y, e.w, e.h].every(finite) || typeof e.min !== 'boolean' || typeof e.max !== 'boolean') return null;
    const programId = allowedProgram(role, e.program);
    if (!programId || wins.some((w) => w.programId === programId)) continue;
    const params = keptParams(programId, e.params);
    wins.push({ programId, x: e.x as number, y: e.y as number, w: e.w as number, h: e.h as number, minimized: e.min, maximized: e.max, ...withParams(params) });
  }
  return { wins, deactivated: raw.deactivated };
}

function desktopFocus(l: { wins: RestoredWin[] }): Focus | null {
  const top = l.wins.filter((w) => !w.minimized).pop();
  return top ? { program: top.programId, ...withParams(top.params) } : null;
}

// ── 태블릿 ──

export interface TabletLayout {
  v: 1;
  /** 레일 항목 id(프로그램 id 또는 'field' = 공정률의 현장 점검). */
  active: string;
  params?: Params;
}

const tabletProgram = (active: string) => (active === 'field' ? 'progress' : active);

function tabletAllowed(role: Role): Set<string> {
  const allowed = programs(role);
  const ids = new Set(tabletCatalog(role, allowed).map((e) => e.id));
  if (allowed.some((p) => p.id === 'settings')) ids.add('settings');
  return ids;
}

export function tabletLayout(active: string, params: Params | undefined): TabletLayout {
  return { v: 1, active, ...withParams(withoutView(keptParams(tabletProgram(active), params))) };
}

export function readTablet(raw: unknown, role: Role): TabletLayout | null {
  if (!isObj(raw) || raw.v !== 1 || typeof raw.active !== 'string') return null;
  if (!tabletAllowed(role).has(raw.active)) return null;
  return tabletLayout(raw.active, isObj(raw.params) ? (raw.params as Params) : undefined);
}

/** 다른 기기에서 맨 앞이던 프로그램을 태블릿에서 열 자리. 열 수 없으면 null. */
export function tabletFor(f: Focus, role: Role): TabletLayout | null {
  const active = f.program === 'progress' && f.params?.view === 'field' ? 'field' : f.program;
  return tabletAllowed(role).has(active) ? tabletLayout(active, f.params) : null;
}

// ── 스마트폰 ──

export type PhoneTab = 'chat' | 'schedule' | 'approvals' | 'contacts' | 'more';
export interface PhoneLayout {
  v: 1;
  tab: PhoneTab;
  sub: string;
  more?: string;
  params?: Params;
}

const PHONE_TABS: readonly PhoneTab[] = ['chat', 'schedule', 'approvals', 'contacts', 'more'];
const PHONE_SUBS = ['schedule-table', 'gantt', 'progress', 'delays', 'field'];
const PHONE_FIELD_SUBS = ['gantt', 'schedule-table', 'field'];
const SCHEDULE_IDS = new Set(['schedule-table', 'gantt', 'progress', 'delays']);

/** 프로그램이 스마트폰의 어느 탭에 열리는지. */
export function phoneTabFor(programId: string): PhoneTab {
  if (programId === 'chat' || programId === 'approvals' || programId === 'contacts') return programId;
  if (SCHEDULE_IDS.has(programId)) return 'schedule';
  return 'more';
}

/** 그 탭에서 보이는 프로그램. 「전체」 목록이면 null. */
export function phoneProgram(l: Pick<PhoneLayout, 'tab' | 'sub' | 'more'>): string | null {
  if (l.tab === 'schedule') return l.sub === 'field' ? 'progress' : l.sub;
  if (l.tab === 'more') return l.more ?? null;
  return l.tab;
}

export function phoneLayout(tab: PhoneTab, sub: string, more: string | null, params: Params | undefined): PhoneLayout {
  const shown = phoneProgram({ tab, sub, more: more ?? undefined });
  return {
    v: 1,
    tab,
    sub,
    ...(tab === 'more' && more ? { more } : {}),
    ...withParams(shown ? withoutView(keptParams(shown, params)) : undefined),
  };
}

export function readPhone(raw: unknown, role: Role): PhoneLayout | null {
  if (!isObj(raw) || raw.v !== 1 || typeof raw.tab !== 'string' || typeof raw.sub !== 'string') return null;
  const tab = raw.tab as PhoneTab;
  const field = role === 'field';
  if (!PHONE_TABS.includes(tab) || (field && tab !== 'chat' && tab !== 'schedule')) return null;
  if (!(field ? PHONE_FIELD_SUBS : PHONE_SUBS).includes(raw.sub)) return null;
  let more: string | null = null;
  if (tab === 'more' && raw.more !== undefined) {
    more = allowedProgram(role, raw.more);
    if (!more || phoneTabFor(more) !== 'more') return null;
  }
  const shown = phoneProgram({ tab, sub: raw.sub, more: more ?? undefined });
  if (shown && !allowedProgram(role, shown)) return null;
  return phoneLayout(tab, raw.sub, more, isObj(raw.params) ? (raw.params as Params) : undefined);
}

/** 다른 기기에서 맨 앞이던 프로그램을 스마트폰에서 열 자리(지금 일정 보기는 그대로). 열 수 없으면 null. */
export function phoneFor(f: Focus, role: Role, current: PhoneLayout): PhoneLayout | null {
  const program = allowedProgram(role, f.program);
  if (!program) return null;
  const fieldView = program === 'progress' && f.params?.view === 'field';
  const tab = fieldView ? 'schedule' : phoneTabFor(program);
  const sub = tab === 'schedule' ? (fieldView ? 'field' : program) : current.sub;
  return readPhone(phoneLayout(tab, sub, tab === 'more' ? program : null, f.params), role);
}

// ── 공통 ──

/** 저장된 상태에서 맨 앞이던 프로그램(다른 기기에서 이어 열 것). 읽을 수 없으면 null. */
export function focusOf(mode: LayoutMode, raw: unknown, role: Role): Focus | null {
  if (mode === 'desktop') {
    const l = readDesktop(raw, role);
    return l ? desktopFocus(l) : null;
  }
  if (mode === 'tablet') {
    const l = readTablet(raw, role);
    if (!l) return null;
    return { program: tabletProgram(l.active), ...withParams(l.active === 'field' ? { ...l.params, view: 'field' } : l.params) };
  }
  const l = readPhone(raw, role);
  const program = l && phoneProgram(l);
  if (!l || !program) return null;
  return { program, ...withParams(l.sub === 'field' && l.tab === 'schedule' ? { ...l.params, view: 'field' } : l.params) };
}
