import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '../../shared/api';
import { answerQuestion, getQuestionnaire, submitQuestionnaire, type QView } from './qApi';

export type Load =
  | { kind: 'loading' }
  | { kind: 'missing' }
  | { kind: 'failed'; message: string }
  | { kind: 'ready'; view: QView };

const messageOf = (e: unknown) => (e instanceof ApiError ? e.message : '요청을 처리할 수 없습니다.');

/** 질문지를 읽는다. id 가 바뀌면 처음부터. live 는 지금 id(늦게 온 앞 id 의 응답을 버리는 데 쓴다). */
function useLoad(id: number | null) {
  const [load, setLoad] = useState<Load>({ kind: 'loading' });
  const live = useRef(id);
  const reload = useCallback(async () => {
    if (id === null) return setLoad({ kind: 'missing' });
    try {
      const view = await getQuestionnaire(id);
      if (live.current === id) setLoad({ kind: 'ready', view });
    } catch (e) {
      if (live.current !== id) return;
      setLoad(e instanceof ApiError && e.status === 404 ? { kind: 'missing' } : { kind: 'failed', message: messageOf(e) });
    }
  }, [id]);
  /** 처음부터 다시 읽기(읽기 실패 뒤 [다시 읽기]). */
  const retry = useCallback(() => {
    setLoad({ kind: 'loading' });
    void reload();
  }, [reload]);
  useEffect(() => {
    live.current = id;
    retry();
  }, [id, retry]);
  return { load, setLoad, reload, retry, live };
}

/**
 * 질문마다 마지막으로 보낸 값(그 응답이 오기 전까지). 화면은 서버 답보다 이것을 먼저 보인다 —
 * 앞 응답이 오기 전에 다시 고른 것도 보이고 다시 보낼 수 있게(A→B→A 가 A 로 끝난다).
 */
function usePending(id: number | null) {
  const [pending, setPending] = useState<Record<string, string | null>>({});
  const seqs = useRef<Record<string, number>>({});
  useEffect(() => {
    seqs.current = {};
    setPending({});
  }, [id]);
  /** 보내기 시작. 돌려준 함수는 응답 뒤에 부른다(그 사이 같은 질문을 또 보냈으면 아무것도 안 함). */
  const begin = useCallback((questionId: string, value: string | null) => {
    const n = (seqs.current[questionId] ?? 0) + 1;
    seqs.current[questionId] = n;
    setPending((p) => ({ ...p, [questionId]: value }));
    return () => {
      if (seqs.current[questionId] !== n) return;
      setPending((p) => {
        const next = { ...p };
        delete next[questionId];
        return next;
      });
    };
  }, []);
  return { pending, begin };
}

/**
 * 요청 한 줄: 앞의 요청이 끝난 뒤 보낸다. 실패하면 알림을 두고 null(task 가 null 을 주면 보내지 않은 것 — 알림은 그대로).
 * 409(이미 제출됨)면 다시 읽어 읽기 전용으로, 404 면 없음으로. failed 는 마지막으로 비운 뒤 실패가 있었는지.
 */
function useQueue(id: number | null, { live, reload, setLoad }: Pick<ReturnType<typeof useLoad>, 'live' | 'reload' | 'setLoad'>) {
  const [notice, setNotice] = useState<string | null>(null);
  const chain = useRef<Promise<unknown>>(Promise.resolve());
  const failed = useRef(false);
  useEffect(() => {
    chain.current = Promise.resolve();
    setNotice(null);
  }, [id]);
  const queued = useCallback(
    <T,>(task: (qid: number) => Promise<T>): Promise<T | null> => {
      const run = async (): Promise<T | null> => {
        if (id === null || live.current !== id) return null;
        try {
          const out = await task(id);
          if (live.current === id && out !== null) setNotice(null);
          return out;
        } catch (e) {
          if (live.current !== id) return null;
          failed.current = true;
          if (e instanceof ApiError && e.status === 409) await reload();
          else if (e instanceof ApiError && e.status === 404) setLoad({ kind: 'missing' });
          else setNotice(messageOf(e));
          return null;
        }
      };
      const next = chain.current.then(run);
      chain.current = next;
      return next;
    },
    [id, reload, live, setLoad],
  );
  return { notice, queued, failed };
}

/**
 * 질문지 하나를 읽고 답하고 제출한다. 답·제출은 한 줄로 차례차례 보낸다(서버는 답을 한 칸에 두므로
 * 둘이 겹치면 한쪽이 사라진다). 돌아온 전체 보기로 다시 그린다.
 */
export function useQuestionnaire(id: number | null) {
  const loader = useLoad(id);
  const { load, setLoad, retry, live } = loader;
  const { pending, begin } = usePending(id);
  const { notice, queued, failed } = useQueue(id, loader);

  /** 답 하나(null 이면 지움). 성공하면 true. */
  const answer = useCallback(
    async (questionId: string, value: string | null) => {
      const settle = begin(questionId, value);
      const view = await queued((qid) => answerQuestion(qid, questionId, value));
      if (live.current !== id) return false;
      if (view) setLoad({ kind: 'ready', view });
      settle();
      return view !== null;
    },
    [id, queued, live, setLoad, begin],
  );

  /** 제출. 성공하면 true(대화 잇기·창 닫기는 부르는 쪽). 앞에 줄 선 답(칸을 나갈 때 저장 등)이 실패했으면 보내지 않는다. */
  const submit = useCallback(async () => {
    failed.current = false;
    const out = await queued((qid) => (failed.current ? Promise.resolve(null) : submitQuestionnaire(qid)));
    return out !== null;
  }, [queued, failed]);

  /** 제출한 뒤 이 화면을 읽기 전용으로(이어 갈 대화가 없을 때). */
  const markSubmitted = useCallback(() => {
    setLoad((l) => (l.kind === 'ready' ? { kind: 'ready', view: { ...l.view, status: 'submitted' } } : l));
  }, [setLoad]);

  return { load, notice, pending, answer, submit, markSubmitted, retry };
}
