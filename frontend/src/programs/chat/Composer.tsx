import { useState, type FormEvent, type KeyboardEvent } from 'react';
import Button from '../../shared/ui/Button';
import { useChat } from './chatStore';
import { useEffectiveUi, useSeeing } from './uiContext';

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

/**
 * 입력창. Enter 로 보내고 Shift+Enter 는 줄바꿈(한글 조합 중 Enter 는 보내지 않음).
 * 답이 도는 동안 [보내기]가 [중단]으로 바뀐다. 서버가 거절하면(예: 앞 요청 처리 중) 그 글을 아래에 보이고 적은 글을 돌려준다.
 */
export default function Composer() {
  const [text, setText] = useState('');
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
      {notice && (
        <p className="ch-notice ch-wrap" role="status">
          {notice}
        </p>
      )}
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
