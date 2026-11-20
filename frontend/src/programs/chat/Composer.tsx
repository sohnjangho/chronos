import { useEffect, useState, type ClipboardEvent, type DragEvent, type FormEvent, type KeyboardEvent } from 'react';
import type { ProgramProps } from '../../os/registry';
import Button from '../../shared/ui/Button';
import AttachButton from './AttachButton';
import { useAttach } from './attachStore';
import { useChat } from './chatStore';
import FileChips from './FileChips';
import { useEffectiveUi, useSeeing } from './seeing';

const DEFAULT_FILE_TEXT = '붙인 파일을 봐 주세요.';

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
const attachedParams = new WeakSet<object>();

export default function Composer({ params }: { params?: ProgramProps['params'] }) {
  const [text, setText] = useState('');
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    if (params?.compose && !composed.has(params)) {
      composed.add(params);
      setText(params.compose);
    }
    if (params?.attach && !attachedParams.has(params)) {
      const id = Number(params.attach);
      if (Number.isInteger(id) && id > 0) {
        attachedParams.add(params);
        void useAttach.getState().attachExisting(id);
      }
    }
  }, [params]);

  const thread = useChat((s) => (s.currentId === null ? undefined : s.threads[s.currentId]));
  const notice = useChat((s) => (s.currentId === null ? s.notice : (s.threads[s.currentId]?.notice ?? null)));
  const items = useAttach((s) => s.items);
  const attachNotice = useAttach((s) => s.notice);
  const seeing = useSeeing(useEffectiveUi());
  const streaming = thread?.streaming ?? false;
  const uploading = items.some((i) => i.status === 'uploading');
  const readyIds = items.filter((i) => i.fileId !== null && i.status !== 'failed' && i.status !== 'uploading').map((i) => i.fileId as number);
  const canSend = !uploading && (text.trim().length > 0 || readyIds.length > 0);

  async function submit(e?: FormEvent) {
    e?.preventDefault();
    if (!canSend || streaming) return;
    const rawText = text.trim();
    const ask = rawText || DEFAULT_FILE_TEXT;
    const fileIds = readyIds.length > 0 ? readyIds : undefined;
    const fileNames = readyIds.length > 0 ? items.filter((i) => i.fileId !== null && readyIds.includes(i.fileId)).map((i) => i.name) : undefined;
    setText('');
    const ok = await useChat.getState().send(ask, fileIds, fileNames);
    if (ok) {
      if (fileIds) useAttach.getState().clear();
    } else if (rawText) {
      setText((now) => now || rawText);
    }
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void submit();
    }
  }

  function onPaste(e: ClipboardEvent<HTMLTextAreaElement>) {
    const files = Array.from(e.clipboardData?.files ?? []);
    if (files.length > 0) {
      e.preventDefault();
      void useAttach.getState().addFiles(files);
    }
  }

  function onDrop(e: DragEvent<HTMLFormElement>) {
    e.preventDefault();
    setDragging(false);
    const files = Array.from(e.dataTransfer?.files ?? []);
    if (files.length > 0) void useAttach.getState().addFiles(files);
  }

  return (
    <div className="ch-compose-wrap">
      {notice && <Notice text={notice} />}
      <form
        className={`ch-compose ${dragging ? 'is-dragging' : ''}`}
        onSubmit={(e) => void submit(e)}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        <FileChips items={items} notice={attachNotice} onRemove={(id) => useAttach.getState().remove(id)} />
        <textarea
          aria-label="에이전트에게 요청"
          placeholder="무엇을 도와드릴까요? 예: 골조가 3주 밀렸어. 만회 계획 세워 줘"
          value={text}
          rows={2}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
          onPaste={onPaste}
        />
        <div className="ch-compose-row">
          <AttachButton disabled={streaming} onPick={(files) => void useAttach.getState().addFiles(files)} />
          {seeing && <span className="ch-seeing ch-ellipsis" title={`보는 중: ${seeing}`}>{`보는 중: ${seeing}`}</span>}
          <span className="ch-gap" />
          <SendOrStop streaming={streaming} stopping={thread?.stopping ?? false} empty={!canSend} />
        </div>
      </form>
    </div>
  );
}
