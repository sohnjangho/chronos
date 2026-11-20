// 조건 창 하나의 상태: 불러온 겹·바꿔 보는 값·미리 보기·확정. 창마다 따로라서 React 상태로 둔다.
// 값을 바꾸면 300ms 뒤 미리 보기를 부르고, 가장 나중 요청의 응답만 쓴다(앞 응답·창을 닫은 뒤·로그아웃 뒤 응답은 버린다).
// 미리 보기 일정은 OS 저장소(schedulePreview)로 일정판에 넘기고, 되돌리기·확정·창 닫기에서 지운다.
import { useCallback, useEffect, useRef, useState } from 'react';
import { useSchedulePreview } from '../../os/schedulePreview';
import { getToken } from '../../os/session';
import { useWindows } from '../../os/windowStore';
import { ApiError } from '../../shared/api';
import { askAgent, commitConditions, getConditions, previewConditions, type Change, type Cond, type CondView, type Preview } from './condApi';
import { allConds } from './labels';

export const DEBOUNCE_MS = 300;
export const CONFLICT_NOTE = '그 사이 일정이 바뀌어 다시 불러왔습니다.';

export type Load = { kind: 'loading' } | { kind: 'ready'; view: CondView } | { kind: 'failed'; message: string };
export interface Notice {
  text: string;
  tone: 'info' | 'error';
  /** 승인함으로 간 확정이면 그 승인 건([승인함 열기]). */
  approvalId?: number;
}
/** 조건 하나에 넣는 바꿈. params 가 null 이면 값 바꿈을 뺀다(입력 칸이 틀렸거나 비었음). invalid 는 그 칸이 틀렸는가. */
export interface EditPatch {
  params?: Record<string, unknown> | null;
  enabled?: boolean;
  invalid?: boolean;
}

const messageOf = (e: unknown) => (e instanceof ApiError ? e.message : '요청을 처리할 수 없습니다.');
const isConflict = (e: unknown) => e instanceof ApiError && e.code === 'version_conflict';
const clearShared = (scheduleId: number | null) => scheduleId !== null && useSchedulePreview.getState().clear(scheduleId);

/** 저장된 값과 같아진 바꿈인가(그러면 바꿈에서 뺀다). */
function sameAsSaved(change: Change, saved: Cond | undefined): boolean {
  if (!saved) return false;
  const params = !change.params || Object.entries(change.params).every(([k, v]) => saved.params[k] === v);
  return params && (change.enabled === undefined || change.enabled === saved.enabled);
}

function merged(prev: Change | undefined, id: string, patch: EditPatch): Change {
  const next: Change = { id };
  const params = patch.params === undefined ? prev?.params : (patch.params ?? undefined);
  const enabled = patch.enabled === undefined ? prev?.enabled : patch.enabled;
  if (params) next.params = params;
  if (enabled !== undefined) next.enabled = enabled;
  return next;
}

function useLoad(scheduleId: number | null) {
  const [load, setLoad] = useState<Load>({ kind: 'loading' });
  const live = useRef(scheduleId);
  const reload = useCallback(async () => {
    if (scheduleId === null) return;
    try {
      const view = await getConditions(scheduleId);
      if (live.current === scheduleId) setLoad({ kind: 'ready', view });
    } catch (e) {
      if (live.current === scheduleId) setLoad({ kind: 'failed', message: messageOf(e) });
    }
  }, [scheduleId]);
  useEffect(() => {
    live.current = scheduleId;
    setLoad({ kind: 'loading' });
    void reload();
  }, [scheduleId, reload]);
  return { load, reload };
}

/** 바꾼 값 → 300ms 뒤 미리 보기. 가장 나중 요청의 응답만 쓴다. */
function usePreview(scheduleId: number | null, view: CondView | null, edits: Record<string, Change>, onConflict: () => void) {
  const [preview, setPreview] = useState<Preview | null>(null);
  const [pending, setPending] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const seq = useRef(0);
  useEffect(() => {
    const my = ++seq.current;
    const changes = Object.values(edits);
    if (!view || scheduleId === null || changes.length === 0) {
      setPreview(null);
      setPending(false);
      setProblem(null);
      clearShared(scheduleId);
      return;
    }
    setPending(true);
    const token = getToken();
    const stale = () => my !== seq.current || getToken() !== token; // 더 나중 요청·창 닫힘·로그아웃
    const timer = setTimeout(async () => {
      try {
        const p = await previewConditions(scheduleId, view.version, changes);
        if (stale()) return;
        setPreview(p);
        setProblem(null);
        useSchedulePreview.getState().set({ scheduleId, view: p.view, moved: p.moved, source: 'conditions' });
      } catch (e) {
        if (stale()) return;
        if (isConflict(e)) return onConflict();
        setPreview(null);
        setProblem(messageOf(e));
        clearShared(scheduleId);
      }
      setPending(false);
    }, DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      seq.current += 1; // 다음 바꿈이나 창 닫기(언마운트) 뒤에 온 응답은 쓰지 않는다
    };
  }, [scheduleId, view, edits, onConflict]);
  return { preview, pending, problem };
}

export function useConditionsModel(scheduleId: number | null) {
  const { load, reload } = useLoad(scheduleId);
  const view = load.kind === 'ready' ? load.view : null;
  const [edits, setEdits] = useState<Record<string, Change>>({});
  const [notice, setNotice] = useState<Notice | null>(null);
  const [busy, setBusy] = useState(false);
  const [invalid, setInvalid] = useState<Record<string, true>>({}); // 값이 틀린 칸(확정을 막는다)
  const [generation, setGeneration] = useState(0); // 바뀌면 입력 칸이 저장된 값으로 돌아간다
  const refill = useCallback(() => setGeneration((g) => g + 1), []);

  const revert = useCallback(() => {
    setEdits({});
    setInvalid({});
    refill();
  }, [refill]);
  /** 다시 불러온 뒤에 칸을 새 저장값으로 채운다(불러오기가 늦어도). */
  const reloadAndRefill = useCallback(async () => {
    await reload();
    refill();
  }, [reload, refill]);
  const conflict = useCallback(async () => {
    revert();
    await reloadAndRefill();
    setNotice({ text: CONFLICT_NOTE, tone: 'info' });
  }, [revert, reloadAndRefill]);
  const onConflict = useCallback(() => void conflict(), [conflict]);
  const { preview, pending, problem } = usePreview(scheduleId, view, edits, onConflict);

  useEffect(() => {
    revert(); // 다른 일정으로 바뀌면 바꾸던 값을 버린다
    setNotice(null);
    return () => void clearShared(scheduleId); // 창을 닫거나 일정이 바뀌면 일정판의 미리 보기도 지운다
  }, [scheduleId, revert]);

  const edit = useCallback(
    (id: string, patch: EditPatch) => {
      setNotice(null);
      if (patch.invalid !== undefined) {
        setInvalid((prev) => {
          const next = { ...prev };
          if (patch.invalid) next[id] = true;
          else delete next[id];
          return next;
        });
      }
      setEdits((prev) => {
        const next = merged(prev[id], id, patch);
        const out = { ...prev };
        const empty = !next.params && next.enabled === undefined;
        if (empty || sameAsSaved(next, view ? allConds(view).find((c) => c.id === id) : undefined)) delete out[id];
        else out[id] = next;
        return out;
      });
    },
    [view],
  );

  /** 서버에 보내는 일(확정·에이전트). 충돌이면 다시 불러오고, 다른 오류는 알림으로. */
  async function send(work: (version: number, changes: Change[]) => Promise<void>) {
    if (!view || scheduleId === null) return;
    setBusy(true);
    setNotice(null);
    try {
      await work(view.version, Object.values(edits));
    } catch (e) {
      if (isConflict(e)) await conflict();
      else setNotice({ text: messageOf(e), tone: 'error' });
    } finally {
      setBusy(false);
    }
  }

  const commit = () =>
    send(async (version, changes) => {
      const r = await commitConditions(scheduleId!, version, changes);
      revert();
      if (!r.applied) return setNotice({ text: '승인함으로 보냈습니다. 승인되면 반영됩니다.', tone: 'info', approvalId: r.approval_id });
      await reloadAndRefill();
      setNotice({ text: `확정했습니다 · 버전 ${r.version}`, tone: 'info' });
    });

  const ask = () =>
    send(async (version, changes) => {
      const r = await askAgent(scheduleId!, version, changes);
      useWindows.getState().open('chat', { session: String(r.chat_session_id), compose: r.text });
    });

  return {
    load,
    view,
    shown: preview?.conditions ?? view,
    edits,
    preview,
    pending,
    problem,
    notice,
    busy,
    hasInvalid: Object.keys(invalid).length > 0,
    /** 입력 칸의 열쇠: 되돌리기·다시 불러오기·저장 버전이 바뀌면 칸을 저장값으로 새로 그린다. */
    fieldsKey: `${generation}.${view?.version ?? 0}`,
    edit,
    revert,
    commit,
    ask,
  };
}

export type ConditionsModel = ReturnType<typeof useConditionsModel>;
