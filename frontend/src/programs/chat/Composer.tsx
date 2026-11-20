import { useEffect, useState, type FormEvent, type KeyboardEvent } from 'react';
import type { ProgramProps } from '../../os/registry';
import Button from '../../shared/ui/Button';
import { useChat } from './chatStore';
import { useEffectiveUi, useSeeing } from './seeing';

/** 입력창 위 한 줄 알림. 거절된 질문지 이어 가기가 있으면 [다시 이어 가기]. */
function Notice({ text }: { text: string }) {
  const sessionId = useChat((s) => s.currentId);
  const failed = useChat((s) => (s.currentId === null ? null : (s.threads[s.currentId]?.failedResume ?? null)));
  return (
    <div className="ch-notice" role="status">
      <span className="ch-wrap">{text}</span>
      {failed && sessionId !== null && (
        <Button className="ch-notice-btn" onClick={() => void useChat.getState().resume(sessionId, failed)}>
          다시 이어 가기
        </Button>
      )}
    </div>
  );
}

/** 답이 도는 동안 [보내기] 자리에 [중단]. 누르면 멈춤을 알리고, 스트림은 done 까지 받는다. */
function SendOrStop({ streaming, stopping, empty }: { streaming: boolean; stopping: boolean; empty: boolean }) {
  if (!streaming) {
    return (
      <Button type="submit" variant="primary" className="ch-send" disabled={empty}>
        보내기
      </Button>
    );
  }
  return (
    <Button className="ch-send" disabled={stopping} onClick={() => void useChat.getState().stop()}>
      {stopping ? '중단하는 중…' : '중단'}
    </Button>
  );
}

/** 이미 입력창에 넣은 params 객체(같은 창 params 로 다시 그려져도 글을 다시 채우지 않는다). */
const composed = new WeakSet<object>();

/**
 * 입력창. Enter 로 보내고 Shift+Enter 는 줄바꿈(한글 조합 중 Enter 는 보내지 않음).
 * 답이 도는 동안 [보내기]가 [중단]으로 바뀐다. 서버가 거절하면(예: 앞 요청 처리 중) 그 글을 아래에 보이고 적은 글을 돌려준다.
 * 창 params.compose 가 오면(새 params 마다 한 번) 그 글을 입력창에 넣는다. 보내기는 사용자가 누른다.
 */
export default function Composer({ params }: { params?: ProgramProps['params'] }) {
  const [text, setText] = useState('');
  useEffect(() => {
    if (!params?.compose || composed.has(params)) return;
    composed.add(params);
    setText(params.compose);
  }, [params]);
  const thread = useChat((s) => (s.currentId === null ? undefined : s.threads[s.currentId]));
  const notice = useChat((s) => (s.currentId === null ? s.notice : (s.threads[s.currentId]?.notice ?? null)));
  const seeing = useSeeing(useEffectiveUi());
  const streaming = thread?.streaming ?? false;

  async function submit(e?: FormEvent) {
    e?.preventDefault();
    const ask = text.trim();
    if (!ask || streaming) return;
    setText('');
    if (!(await useChat.getState().send(ask))) setText((now) => now || ask);
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void submit();
    }
  }

  return (
    <div className="ch-compose-wrap">
      {notice && <Notice text={notice} />}
      <form className="ch-compose" onSubmit={(e) => void submit(e)}>
        <textarea
          aria-label="에이전트에게 요청"
          placeholder="무엇을 도와드릴까요? 예: 골조가 3주 밀렸어. 만회 계획 세워 줘"
          value={text}
          rows={2}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
        />
        <div className="ch-compose-row">
          {seeing && <span className="ch-seeing ch-ellipsis" title={`보는 중: ${seeing}`}>{`보는 중: ${seeing}`}</span>}
          <span className="ch-gap" />
          <SendOrStop streaming={streaming} stopping={thread?.stopping ?? false} empty={!text.trim()} />
        </div>
      </form>
    </div>
  );
}
