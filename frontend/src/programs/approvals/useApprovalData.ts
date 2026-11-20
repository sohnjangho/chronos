// 승인함 자료: 세 묶음 목록·고른 건의 상세·결정·자동 적용 되돌리기. 결정 뒤에는 목록·상세·메뉴바 배지를 다시 읽는다.
import { useCallback, useEffect, useRef, useState } from 'react';
import { refreshApprovals, useApprovals } from '../../os/approvals';
import { useWindows } from '../../os/windowStore';
import { ApiError } from '../../shared/api';
import type { Revert } from './ApprovalList';
import { ro } from './format';
import { apvApi, groupOf, type ApprovalDetail, type ApprovalItem, type DecideOut, type Decision, type Group, type Mode, type ScheduleItem } from './apvApi';

export interface Notice {
  tone: 'ok' | 'error';
  text: string;
}

type Lists = Record<Group, ApprovalItem[] | null>;
const GROUPS: Group[] = ['pending', 'decided', 'auto'];
const STALE = '그 뒤에 바뀐 버전이 있습니다 — 탐색기에서 버전을 고르세요';
const message = (e: unknown) => (e instanceof ApiError ? e.message : '요청을 처리할 수 없습니다.');

/** 결정이 받아들여진 뒤 보일 글. 다시 짜기는 대화 주인이면 대화 창이 그 건으로 이어 간다(R3). */
function afterDecision(decision: Decision, out: DecideOut, id: number): string {
  if (decision === 'approve') return out.version === null ? '승인했습니다.' : `승인해 버전 ${ro(out.version)} 저장했습니다.`;
  if (decision === 'reject') return '거부했습니다.';
  if (out.chat_session_id === null) return '거부했습니다. 대화에서 나온 건이 아니라 다시 짜게 할 대화가 없습니다.';
  if (!out.owner_is_decider) return '대화 주인에게 다시 짜기 요청을 남겼습니다.';
  useWindows.getState().open('chat', { session: String(out.chat_session_id), resume_approval: String(id) });
  return '거부하고 대화 창에서 다시 짜기를 시작했습니다.';
}

/** 목록·승인 수준·일정 이름과 지금 버전(읽지 못했으면 schedulesFailed). */
function useLists() {
  const [lists, setLists] = useState<Lists>({ pending: null, decided: null, auto: null });
  const [mode, setMode] = useState<Mode | null>(null);
  const [schedules, setSchedules] = useState<Map<number, ScheduleItem> | null>(null);
  const [schedulesFailed, setSchedulesFailed] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const reload = useCallback(async () => {
    const names = apvApi.schedules().then(
      (rows) => {
        setSchedules(new Map(rows.map((r) => [r.id, r])));
        setSchedulesFailed(false);
      },
      () => setSchedulesFailed(true),
    );
    try {
      const [p, d, a] = await Promise.all(GROUPS.map((g) => apvApi.list(g)));
      setLists({ pending: p.items, decided: d.items, auto: a.items });
      setMode(p.mode);
      setLoadError(null);
    } catch (e) {
      setLoadError(message(e));
    }
    await names;
  }, []);
  // 처음 열 때, 그리고 메뉴바 배지(30초마다 다시 읽음)가 바뀔 때마다 다시 읽는다.
  const badge = useApprovals((s) => s.pending);
  useEffect(() => void reload(), [reload, badge]);
  return { lists, mode, schedules, schedulesFailed, loadError, reload };
}

/**
 * 고른 건과 그 상세. 고른 id 는 ref 에도 두고, 다른 id 의 늦은 응답은 버린다(상세는 늘 고른 건만).
 * 같은 건을 다시 고르면 다시 읽는다. params.id 로 고른 건은 그 묶음 탭으로 옮긴다.
 */
function useSelection(lists: Lists, paramId: string | undefined, setNotice: (n: Notice | null) => void) {
  const [tab, setTab] = useState<Group>('pending');
  const [selected, setSelected] = useState<number | null>(null);
  const [detail, setDetail] = useState<ApprovalDetail | null>(null);
  const picked = useRef<number | null>(null);
  const follow = useRef(false);
  const loadDetail = useCallback(
    async (id: number) => {
      try {
        const d = await apvApi.detail(id);
        if (picked.current !== id) return;
        setDetail(d);
        if (follow.current) setTab(groupOf(d.status));
        follow.current = false;
      } catch (e) {
        if (picked.current !== id) return;
        setDetail(null);
        setNotice({ tone: 'error', text: message(e) });
      }
    },
    [setNotice],
  );
  const select = useCallback(
    (id: number | null) => {
      picked.current = id;
      setNotice(null);
      setSelected(id);
      if (id !== null) void loadDetail(id);
    },
    [loadDetail, setNotice],
  );
  useEffect(() => {
    if (!paramId) return;
    follow.current = true;
    select(Number(paramId));
  }, [paramId, select]);
  const items = lists[tab];
  useEffect(() => {
    if (selected === null && !paramId && items?.length) select(items[0].id);
  }, [items, selected, paramId, select]);
  const changeTab = (t: Group) => {
    setTab(t);
    select(lists[t]?.[0]?.id ?? null);
  };
  const isPicked = (id: number) => picked.current === id;
  return { tab, changeTab, selected, select, detail: detail?.id === selected ? detail : null, loadDetail, isPicked };
}

export function useApprovalData(paramId: string | undefined) {
  const [notice, setNotice] = useState<Notice | null>(null);
  const [reverting, setReverting] = useState<number | null>(null);
  const { lists, mode, schedules, schedulesFailed, loadError, reload } = useLists();
  const sel = useSelection(lists, paramId, setNotice);

  async function decide(decision: Decision, note: string) {
    if (!sel.detail) return;
    const id = sel.detail.id;
    try {
      setNotice({ tone: 'ok', text: afterDecision(decision, await apvApi.decide(id, decision, note), id) });
    } catch (e) {
      setNotice({ tone: 'error', text: message(e) });
    }
    // 그 사이 다른 건을 골랐으면 그 건의 상세는 다시 읽지 않는다.
    await Promise.all([reload(), sel.isPicked(id) ? sel.loadDetail(id) : null]);
    void refreshApprovals();
  }

  function revertOf(it: ApprovalItem): Revert {
    if (it.kind === 'rule') return { ok: false, why: '규칙 저장은 되돌리기 대신 내 규칙에서 끄거나 지웁니다' };
    if (it.restore_to === null || it.schedule_id === null) return { ok: false, why: '처음 저장이라 되돌릴 버전이 없습니다' };
    if (schedulesFailed) return { ok: false, why: '일정 버전을 읽지 못했습니다' };
    const current = schedules?.get(it.schedule_id);
    if (schedules === null || reverting !== null) return { ok: false, why: '' };
    if (!current) return { ok: false, why: '지운 일정입니다' };
    return current.version === it.version ? { ok: true } : { ok: false, why: STALE };
  }

  async function revert(it: ApprovalItem) {
    if (it.schedule_id === null || it.restore_to === null || it.version === null) return;
    setReverting(it.id);
    try {
      const view = await apvApi.restore(it.schedule_id, it.restore_to, it.version);
      setNotice({ tone: 'ok', text: `버전 ${it.restore_to}의 내용으로 되돌렸습니다 (새 버전 ${view.version}).` });
    } catch (e) {
      setNotice({ tone: 'error', text: message(e) });
    }
    await reload();
    setReverting(null);
  }

  return { ...sel, lists, mode, schedules, loadError, notice, decide, revertOf, revert };
}
