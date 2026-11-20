// 일정판의 일정 상태. 탭(스케줄표·간트·CPM·진행)이 함께 쓴다. 고치면 서버가 돌려준 ScheduleView 로 통째로 바꾼다.
import { create } from 'zustand';
import { ApiError } from '../../shared/api';
import * as sapi from './scheduleApi';
import type { ActivityFields, NewActivity, PredItem, ScheduleView } from './scheduleApi';

export const CONFLICT_NOTICE = '그 사이 일정이 바뀌어 다시 불러왔습니다';

export interface Notice {
  tone: 'error' | 'info';
  text: string;
}

/** 되돌리기·다시 하기 한 칸: 일정이 expect 버전일 때 restore 버전의 내용으로 새 버전을 만든다. */
export interface UndoStep {
  restore: number;
  expect: number;
  /** 바꾼 것의 버전 메모(서버 note). 읽기 전이면 빈 글. */
  note: string;
}

/** 보낼 차례가 왔을 때의 일정으로 선행 목록을 만든다. null 이면 보내지 않는다. */
export type PredsFrom = (view: ScheduleView) => PredItem[] | null;

export interface ScheduleState {
  scheduleId: number | null;
  view: ScheduleView | null;
  /** 읽지 못했을 때 서버 글. */
  loadError: string | null;
  selected: string | null;
  /** 그 행을 보이게 하라는 요청(n 이 바뀔 때마다 한 번). */
  reveal: { aid: string; n: number } | null;
  notice: Notice | null;
  /** 줄 서 있거나 가는 중인 쓰기 수. */
  pending: number;
  /** 이 창에서 고친 것만 쌓인다. */
  undo: UndoStep[];
  redo: UndoStep[];
  load(id: number): Promise<void>;
  patchActivity(aid: string, fields: ActivityFields): Promise<boolean>;
  /** items 가 함수면 차례가 왔을 때의 일정으로 목록을 만든다(앞 요청의 결과를 반영). null 이면 보내지 않는다. */
  setPredecessors(aid: string, items: PredItem[] | PredsFrom): Promise<boolean>;
  /** 새 액티비티 id(못 넣었으면 null). 넣으면 그 행을 고르고 보이게 한다. */
  addActivity(input: NewActivity): Promise<string | null>;
  deleteActivity(aid: string): Promise<boolean>;
  undoLast(): Promise<boolean>;
  redoLast(): Promise<boolean>;
  select(aid: string | null): void;
  revealActivity(aid: string): void;
  setNotice(notice: Notice | null): void;
  reset(): void;
}

const INITIAL = {
  scheduleId: null,
  view: null,
  loadError: null,
  selected: null,
  reveal: null,
  notice: null,
  pending: 0,
  undo: [],
  redo: [],
};

// 쓰기 줄(한 번에 하나). epoch 가 바뀌면(다른 일정·reset) 줄 서 있던 쓰기는 보내지 않고, 늦게 온 답은 버린다.
// 409 가 나면 그때까지 줄 선 쓰기(표 번호 ≤ cutoff)도 보내지 않는다 — 다시 불러온 일정 위에 옛 고침을 얹지 않게.
let chain: Promise<unknown> = Promise.resolve();
let epoch = 0;
let loadSeq = 0;
let tickets = 0;
let cutoff = 0;

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
const errorText = (e: unknown) => (e instanceof ApiError ? e.message : '요청을 처리하지 못했습니다.');

/** 바뀌지 않은 액티비티는 앞의 객체를 그대로 쓴다(그 행은 다시 그리지 않는다). */
function share(prev: ScheduleView | null, next: ScheduleView): ScheduleView {
  if (!prev || prev.id !== next.id) return next;
  const old = new Map(prev.activities.map((a) => [a.id, a]));
  const activities = next.activities.map((a) => {
    const o = old.get(a.id);
    return o && same(o, a) ? o : a;
  });
  return { ...next, activities };
}

const get = (): ScheduleState => useSchedule.getState();
const set = (patch: Partial<ScheduleState> | ((s: ScheduleState) => Partial<ScheduleState>)): void => useSchedule.setState(patch);

function apply(next: ScheduleView) {
  set((s) => {
    const view = share(s.view, next);
    const selected = s.selected && view.activities.some((a) => a.id === s.selected) ? s.selected : null;
    return { view, selected, loadError: null };
  });
}

async function fetchView(id: number) {
  const seq = ++loadSeq;
  try {
    const view = await sapi.getSchedule(id);
    if (seq === loadSeq && get().scheduleId === id) apply(view);
  } catch (e) {
    if (seq !== loadSeq || get().scheduleId !== id) return;
    // 보던 일정이 있으면 그대로 두고 알림만, 없으면 화면에 오류를 보인다.
    if (get().view) set({ notice: { tone: 'error', text: errorText(e) } });
    else set({ loadError: errorText(e) });
  }
}

/** 쓰기를 한 줄로 세운다. 앞 요청이 끝난 뒤 그때의 일정 버전으로 보낸다. */
function enqueue<T>(job: (id: number, view: ScheduleView) => Promise<T>, fallback: T): Promise<T> {
  const mine = epoch;
  const ticket = ++tickets;
  set((s) => ({ pending: s.pending + 1 }));
  const run = chain.then(() => {
    const { scheduleId, view } = get();
    return mine !== epoch || ticket <= cutoff || scheduleId === null || !view ? fallback : job(scheduleId, view);
  });
  chain = run.catch(() => undefined);
  return run.finally(() => {
    if (mine === epoch) set((s) => ({ pending: s.pending - 1 }));
  });
}

/** 보내고 성공하면 새 일정으로. 409 는 다시 불러오고 알림, 그 밖은 서버 글을 알림. */
async function write(id: number, send: () => Promise<ScheduleView>): Promise<ScheduleView | null> {
  const mine = epoch;
  set({ notice: null });
  try {
    const next = await send();
    if (mine !== epoch) return null;
    apply(next);
    return next;
  } catch (e) {
    if (mine !== epoch) return null;
    if (e instanceof ApiError && e.code === 'version_conflict') {
      cutoff = tickets;
      set({ notice: { tone: 'info', text: CONFLICT_NOTICE }, undo: [], redo: [] });
      await fetchView(id);
    } else set({ notice: { tone: 'error', text: errorText(e) } });
    return null;
  }
}

async function noteFor(id: number, n: number) {
  const mine = epoch;
  try {
    const note = (await sapi.getVersions(id)).find((v) => v.n === n)?.note;
    if (note && mine === epoch) set((s) => ({ undo: s.undo.map((u) => (u.expect === n ? { ...u, note } : u)) }));
  } catch {
    // 메모 없이 둔다(되돌리기는 그대로 된다).
  }
}

/**
 * 이 창에서 고친 것: build 는 차례가 왔을 때의 일정(view)으로 보낼 요청을 만든다(null 이면 보내지 않음).
 * 버전이 바뀌면 되돌리기에 쌓고 그 버전의 메모를 읽어 붙인다.
 */
function change(build: (id: number, view: ScheduleView) => (() => Promise<ScheduleView>) | null) {
  return enqueue(async (id, view) => {
    const send = build(id, view);
    if (!send) return null;
    const next = await write(id, send);
    if (next && next.version !== view.version) {
      set((s) => ({ undo: [...s.undo, { restore: view.version, expect: next.version, note: '' }], redo: [] }));
      void noteFor(id, next.version);
    }
    return next;
  }, null);
}

/** 되돌리기(undo → redo) · 다시 하기(redo → undo). 일정이 그 칸의 expect 버전일 때만. */
function travel(from: 'undo' | 'redo') {
  const to = from === 'undo' ? 'redo' : 'undo';
  return enqueue(async (id, view) => {
    const step = get()[from].at(-1);
    if (!step || step.expect !== view.version) return false;
    const next = await write(id, () => sapi.restoreVersion(id, step.restore, view.version));
    if (!next) return false;
    const done = from === 'undo' ? '되돌렸습니다' : '다시 했습니다';
    // 남은 칸 가운데 맨 위 칸은 방금 되살린 내용(step.restore)을 기다리고 있었다 — 그 내용은 이제 새 버전에 있다.
    const rest = get()[from].slice(0, -1).map((u, i, all) =>
      i === all.length - 1 && u.expect === step.restore ? { ...u, expect: next.version } : u,
    );
    set((s) => ({
      [from]: rest,
      [to]: [...s[to], { restore: step.expect, expect: next.version, note: step.note }],
      notice: { tone: 'info', text: step.note ? `${done}: ${step.note}` : done },
    }));
    return true;
  }, false);
}

async function addActivity(input: NewActivity): Promise<string | null> {
  let before = new Set<string>();
  const next = await change((id, view) => {
    before = new Set(view.activities.map((a) => a.id));
    return () => sapi.postActivity(id, input, view.version);
  });
  const added = next?.activities.find((a) => !before.has(a.id))?.id ?? null;
  if (added) get().revealActivity(added);
  return added;
}

async function deleteActivity(aid: string): Promise<boolean> {
  const ok = (await change((id, view) => () => sapi.deleteActivity(id, aid, view.version))) !== null;
  if (ok) set({ notice: { tone: 'info', text: `${aid} 을(를) 지웠습니다. 되돌리기로 살릴 수 있습니다.` } });
  return ok;
}

export const useSchedule = create<ScheduleState>(() => ({
  ...INITIAL,
  async load(id) {
    if (get().scheduleId !== id) {
      epoch += 1;
      chain = Promise.resolve();
      set({ ...INITIAL, scheduleId: id });
    }
    await fetchView(id);
  },
  patchActivity: async (aid, fields) => (await change((id, view) => () => sapi.patchActivity(id, aid, fields, view.version))) !== null,
  async setPredecessors(aid, items) {
    const sent = await change((id, view) => {
      const list = typeof items === 'function' ? items(view) : items;
      return list && (() => sapi.putPredecessors(id, aid, list, view.version));
    });
    return sent !== null;
  },
  addActivity,
  deleteActivity,
  undoLast: () => travel('undo'),
  redoLast: () => travel('redo'),
  select: (aid) => set({ selected: aid }),
  revealActivity: (aid) => set((s) => ({ selected: aid, reveal: { aid, n: (s.reveal?.n ?? 0) + 1 } })),
  setNotice: (notice) => set({ notice }),
  reset() {
    epoch += 1;
    loadSeq += 1;
    chain = Promise.resolve();
    set(INITIAL);
  },
}));
