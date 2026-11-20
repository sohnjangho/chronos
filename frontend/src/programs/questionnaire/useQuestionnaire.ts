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
  useEffect(() => {
    live.current = id;
    setLoad({ kind: 'loading' });
    void reload();
  }, [id, reload]);
  return { load, setLoad, reload, live };
}

/**
 * 질문지 하나를 읽고 답하고 제출한다. 답·제출은 한 줄로 차례차례 보낸다(서버는 답을 한 칸에 두므로
 * 둘이 겹치면 한쪽이 사라진다). 돌아온 전체 보기로 다시 그린다. 409(이미 제출됨)면 다시 읽어 읽기 전용으로.
 */
export function useQuestionnaire(id: number | null) {
  const { load, setLoad, reload, live } = useLoad(id);
  const [notice, setNotice] = useState<string | null>(null);
  const chain = useRef<Promise<unknown>>(Promise.resolve());
  useEffect(() => {
    chain.current = Promise.resolve();
    setNotice(null);
  }, [id]);

  /** 앞의 요청이 끝난 뒤 보낸다. 실패하면 알림을 두고 null. */
  const queued = useCallback(
    <T,>(task: (qid: number) => Promise<T>): Promise<T | null> => {
      const run = async (): Promise<T | null> => {
        if (id === null || live.current !== id) return null;
        try {
          const out = await task(id);
          if (live.current === id) setNotice(null);
          return out;
        } catch (e) {
          if (live.current !== id) return null;
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

  /** 답 하나(null 이면 지움). 성공하면 true. */
  const answer = useCallback(
    async (questionId: string, value: string | null) => {
      const view = await queued((qid) => answerQuestion(qid, questionId, value));
      if (view && live.current === id) setLoad({ kind: 'ready', view });
      return view !== null;
    },
    [id, queued, live, setLoad],
  );

  /** 제출. 성공하면 true(대화 잇기·창 닫기는 부르는 쪽). */
  const submit = useCallback(async () => (await queued((qid) => submitQuestionnaire(qid))) !== null, [queued]);

  /** 제출한 뒤 이 화면을 읽기 전용으로(이어 갈 대화가 없을 때). */
  const markSubmitted = useCallback(() => {
    setLoad((l) => (l.kind === 'ready' ? { kind: 'ready', view: { ...l.view, status: 'submitted' } } : l));
  }, [setLoad]);

  return { load, notice, answer, submit, markSubmitted };
}
