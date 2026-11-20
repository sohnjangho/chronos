// 일정 저장소: 일정 id 마다 하나. 그 일정을 보는 창(스케줄·간트차트·CPM·공정률)이 함께 쓴다 — 고침·되돌리기·쓰기 줄·고른 액티비티.
// 고치면 서버가 돌려준 ScheduleView 로 통째로 바꾼다. 창은 holdSchedule 로 잡고, 마지막 창이 놓으면 비우고 잊는다.
import { createStore, type StoreApi } from 'zustand';
import { ApiError } from '../api';
import * as sapi from './scheduleApi';
import type { ActivityFields, NewActivity, PredItem, ScheduleView, WeightMode } from './scheduleApi';
import { errorText, reader, type GetState, type Queue, type SetState } from './scheduleRead';

export const CONFLICT_NOTICE = '그 사이 일정이 바뀌어 다시 불러왔습니다';

export interface Notice {
  tone: 'error' | 'info';
  text: string;
  /** 창 안의 동작에서 난 안내(틀린 칸 글·오늘이 기간 밖 등)면 그 창 id — 그 창에만 보인다. 없으면(서버 거절·되돌리기 등) 모든 창. */
  windowId?: string;
}

/** 되돌리기·다시 하기 한 칸: 일정이 expect 버전일 때 restore 버전의 내용으로 새 버전을 만든다. */
export interface UndoStep {
  restore: number;
  expect: number;
  /** 바꾼 것의 버전 메모(서버 note). 읽기 전이면 빈 글. */
  note: string;
}

/** 버전을 바꾼 마지막 고침(이 일정 창 어디서든): 고치기 전·뒤 일정과 고친 액티비티(없으면 null). 지연 알림이 쓴다. */
export interface LastChange {
  before: ScheduleView;
  after: ScheduleView;
  aid: string | null;
}

/** 보낼 차례가 왔을 때의 일정으로 선행 목록을 만든다. null 이면 보내지 않는다. */
export type PredsFrom = (view: ScheduleView) => PredItem[] | null;

export interface ScheduleState {
  scheduleId: number;
  view: ScheduleView | null;
  /** 읽지 못했을 때 서버 글. */
  loadError: string | null;
  selected: string | null;
  /** 고른 창의 id. 다른 창은 그 줄로 따라간다(초점은 옮기지 않는다). 창이 아닌 곳에서 골랐으면 null. */
  selectedBy: string | null;
  /** 고를 때마다 하나씩 는다 — 같은 줄을 다시 골라도 다른 창이 다시 따라가게. */
  selectedN: number;
  /** 그 행을 보이게 하라는 요청(n 이 바뀔 때마다 한 번). by = 요청한 창(null 이면 모든 창). */
  reveal: { aid: string; n: number; by: string | null } | null;
  notice: Notice | null;
  /** 줄 서 있거나 가는 중인 쓰기 수. */
  pending: number;
  /** 이 일정을 보는 창들에서 고친 것이 쌓인다. */
  undo: UndoStep[];
  redo: UndoStep[];
  lastChange: LastChange | null;
  /** 서버에서 다시 읽는다. 읽는 중이면 그 요청을 같이 기다린다. */
  load(): Promise<void>;
  patchActivity(aid: string, fields: ActivityFields): Promise<boolean>;
  /** items 가 함수면 차례가 왔을 때의 일정으로 목록을 만든다(앞 요청의 결과를 반영). null 이면 보내지 않는다. */
  setPredecessors(aid: string, items: PredItem[] | PredsFrom): Promise<boolean>;
  /** 새 액티비티 id(못 넣었으면 null). 넣으면 그 행을 고르고 모든 창에서 보이게 한다. */
  addActivity(input: NewActivity): Promise<string | null>;
  deleteActivity(aid: string): Promise<boolean>;
  /** Data Date 바꾸기(null 이면 지움). 다른 고침처럼 새 버전·되돌리기. */
  setDataDate(date: string | null): Promise<boolean>;
  /** 가중치 방식 바꾸기. 버전 밖이라 되돌리기에 쌓지 않고, 바꾼 뒤 일정을 다시 읽는다. */
  setWeightMode(mode: WeightMode): Promise<boolean>;
  /** 마지막 고침의 지연 알림을 닫는다(이 일정을 보는 모든 창에서, 다음 고침까지). */
  dismissChange(): void;
  undoLast(): Promise<boolean>;
  redoLast(): Promise<boolean>;
  select(aid: string | null, by?: string | null): void;
  revealActivity(aid: string, by?: string | null): void;
  setNotice(notice: Notice | null): void;
  /** 비운다. 줄 서 있던 쓰기는 보내지 않고 늦게 온 답은 버린다. */
  reset(): void;
}

export type ScheduleStore = StoreApi<ScheduleState>;

const INITIAL = {
  view: null,
  loadError: null,
  selected: null,
  selectedBy: null,
  selectedN: 0,
  reveal: null,
  notice: null,
  pending: 0,
  undo: [],
  redo: [],
  lastChange: null,
};

/** 쓰기는 한 번에 하나. */
function writer(id: number, get: GetState, set: SetState) {
  const q: Queue = { chain: Promise.resolve(), epoch: 0, loadSeq: 0, tickets: 0, cutoff: 0, loading: null };
  const { apply, fetchView, load } = reader(id, get, set, q);

  /** 쓰기를 한 줄로 세운다. 앞 요청이 끝난 뒤 그때의 일정 버전으로 보낸다. */
  function enqueue<T>(job: (view: ScheduleView) => Promise<T>, fallback: T): Promise<T> {
    const mine = q.epoch;
    const ticket = ++q.tickets;
    set((s) => ({ pending: s.pending + 1 }));
    const run = q.chain.then(() => {
      const { view } = get();
      return mine !== q.epoch || ticket <= q.cutoff || !view ? fallback : job(view);
    });
    q.chain = run.catch(() => undefined);
    return run.finally(() => {
      if (mine === q.epoch) set((s) => ({ pending: s.pending - 1 }));
    });
  }

  /** 보내고 성공하면 새 일정으로. 409 는 다시 불러오고 알림, 그 밖은 서버 글을 알림. */
  async function write(send: () => Promise<ScheduleView>): Promise<ScheduleView | null> {
    const mine = q.epoch;
    set({ notice: null });
    try {
      const next = await send();
      if (mine !== q.epoch) return null;
      apply(next);
      return next;
    } catch (e) {
      if (mine !== q.epoch) return null;
      if (e instanceof ApiError && e.code === 'version_conflict') {
        q.cutoff = q.tickets;
        set({ notice: { tone: 'info', text: CONFLICT_NOTICE }, undo: [], redo: [] });
        await fetchView();
      } else set({ notice: { tone: 'error', text: errorText(e) } });
      return null;
    }
  }

  function reset() {
    q.epoch += 1;
    q.loadSeq += 1;
    q.chain = Promise.resolve();
    q.loading = null;
    set(INITIAL);
  }

  /** 버전 밖의 쓰기(가중치 방식): 줄을 서서 보내고, 성공하면 일정을 다시 읽는다. 실패하면 서버 글을 알림. */
  function sideWrite(send: () => Promise<unknown>): Promise<boolean> {
    return enqueue(async () => {
      const mine = q.epoch;
      set({ notice: null });
      try {
        await send();
      } catch (e) {
        if (mine === q.epoch) set({ notice: { tone: 'error', text: errorText(e) } });
        return false;
      }
      if (mine === q.epoch) await fetchView();
      return true;
    }, false);
  }

  return { load, enqueue, write, sideWrite, reset, epoch: () => q.epoch };
}

/** 이 일정 창들에서 고친 것·되돌리기·다시 하기. */
function editing(id: number, get: GetState, set: SetState, w: ReturnType<typeof writer>) {
  async function noteFor(n: number) {
    const mine = w.epoch();
    try {
      const note = (await sapi.getVersions(id)).find((v) => v.n === n)?.note;
      if (note && mine === w.epoch()) set((s) => ({ undo: s.undo.map((u) => (u.expect === n ? { ...u, note } : u)) }));
    } catch {
      // 메모 없이 둔다(되돌리기는 그대로 된다).
    }
  }

  /**
   * build 는 차례가 왔을 때의 일정(view)으로 보낼 요청을 만든다(null 이면 보내지 않음). 버전이 바뀌면 되돌리기에 쌓고
   * 마지막 고침(lastChange, aid = 고친 액티비티)으로 둔다.
   */
  function change(build: (view: ScheduleView) => (() => Promise<ScheduleView>) | null, aid: string | null = null) {
    return w.enqueue(async (view) => {
      const send = build(view);
      if (!send) return null;
      const next = await w.write(send);
      if (next && next.version !== view.version) {
        const lastChange = { before: view, after: next, aid };
        set((s) => ({ undo: [...s.undo, { restore: view.version, expect: next.version, note: '' }], redo: [], lastChange }));
        void noteFor(next.version);
      }
      return next;
    }, null);
  }

  /** 되돌리기(undo → redo) · 다시 하기(redo → undo). 일정이 그 칸의 expect 버전일 때만. */
  function travel(from: 'undo' | 'redo') {
    const to = from === 'undo' ? 'redo' : 'undo';
    return w.enqueue(async (view) => {
      const step = get()[from].at(-1);
      if (!step || step.expect !== view.version) return false;
      const next = await w.write(() => sapi.restoreVersion(id, step.restore, view.version));
      if (!next) return false;
      const done = from === 'undo' ? '되돌렸습니다' : '다시 했습니다';
      // 남은 칸 가운데 맨 위 칸은 방금 되살린 내용(step.restore)을 기다리고 있었다 — 그 내용은 이제 새 버전에 있다.
      const rest = get()[from].slice(0, -1).map((u, i, all) =>
        i === all.length - 1 && u.expect === step.restore ? { ...u, expect: next.version } : u,
      );
      set((s) => ({
        [from]: rest,
        [to]: [...s[to], { restore: step.expect, expect: next.version, note: step.note }],
        lastChange: null, // 되돌린 고침의 지연 알림은 거둔다
        notice: { tone: 'info', text: step.note ? `${done}: ${step.note}` : done },
      }));
      return true;
    }, false);
  }

  return { change, travel };
}

function makeStore(id: number): ScheduleStore {
  return createStore<ScheduleState>((set, get) => {
    const w = writer(id, get, set);
    const { change, travel } = editing(id, get, set, w);
    return {
      scheduleId: id,
      ...INITIAL,
      load: w.load,
      patchActivity: async (aid, fields) => (await change((view) => () => sapi.patchActivity(id, aid, fields, view.version), aid)) !== null,
      async setPredecessors(aid, items) {
        const sent = await change((view) => {
          const list = typeof items === 'function' ? items(view) : items;
          return list && (() => sapi.putPredecessors(id, aid, list, view.version));
        }, aid);
        return sent !== null;
      },
      async addActivity(input) {
        let before = new Set<string>();
        const next = await change((view) => {
          before = new Set(view.activities.map((a) => a.id));
          return () => sapi.postActivity(id, input, view.version);
        });
        const added = next?.activities.find((a) => !before.has(a.id))?.id ?? null;
        if (added) get().revealActivity(added);
        return added;
      },
      async deleteActivity(aid) {
        const ok = (await change((view) => () => sapi.deleteActivity(id, aid, view.version))) !== null;
        if (ok) set({ notice: { tone: 'info', text: `${aid} 을(를) 지웠습니다. 되돌리기로 살릴 수 있습니다.` } });
        return ok;
      },
      setDataDate: async (data_date) => (await change((view) => () => sapi.patchSchedule(id, { data_date, base_version: view.version }))) !== null,
      setWeightMode: (mode) => w.sideWrite(() => sapi.putWeightMode(id, mode)),
      dismissChange: () => set({ lastChange: null }),
      undoLast: () => travel('undo'),
      redoLast: () => travel('redo'),
      select: (aid, by = null) => set((s) => ({ selected: aid, selectedBy: aid === null ? null : by, selectedN: s.selectedN + 1 })),
      revealActivity: (aid, by = null) =>
        set((s) => ({ selected: aid, selectedBy: by, selectedN: s.selectedN + 1, reveal: { aid, n: (s.reveal?.n ?? 0) + 1, by } })),
      setNotice: (notice) => set({ notice }),
      reset: w.reset,
    };
  });
}

// 일정 id → 저장소와 그것을 잡은 창들.
const stores = new Map<number, { store: ScheduleStore; holders: Set<string> }>();

/** 그 일정의 저장소(처음 부르면 만든다). */
export function scheduleStore(id: number): ScheduleStore {
  let entry = stores.get(id);
  if (!entry) {
    entry = { store: makeStore(id), holders: new Set() };
    stores.set(id, entry);
  }
  return entry.store;
}

/**
 * 창 owner 가 store 를 쓴다. 돌려준 함수로 놓는다. 마지막 창이 놓으면 비우고(줄 선 쓰기·늦은 답 버림) 잊는다.
 * 잊힌 store 를 다시 잡으면(StrictMode 가 효과를 두 번 돌릴 때) 그 store 를 다시 그 일정의 저장소로 둔다.
 */
export function holdSchedule(store: ScheduleStore, owner: string): () => void {
  const id = store.getState().scheduleId;
  let entry = stores.get(id);
  if (entry?.store !== store) {
    entry = { store, holders: new Set() };
    stores.set(id, entry);
  }
  entry.holders.add(owner);
  const mine = entry;
  return () => {
    mine.holders.delete(owner);
    if (mine.holders.size > 0) return;
    store.getState().reset();
    if (stores.get(id) === mine) stores.delete(id);
  };
}

/** 모든 일정 저장소를 비우고 잊는다(시험). */
export function forgetSchedules(): void {
  for (const { store } of stores.values()) store.getState().reset();
  stores.clear();
}
