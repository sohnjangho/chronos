import { useEffect, useState } from 'react';
import type { ProgramProps } from '../../os/registry';
import { useWindows, workArea } from '../../os/windowStore';
import { useZoom, zoomOf } from '../../os/zoom';
import Composer from './Composer';
import ContextPanel from './ContextPanel';
import Conversation from './Conversation';
import ModelPicker from './ModelPicker';
import { useChat } from './chatStore';
import ThreadList, { sessionTitle } from './ThreadList';
import './chat.css';

/** 창 본문 너비가 이 이상이면 큰 화면(왼쪽 대화 목록 · 가운데 대화 · 오른쪽 컨텍스트). */
export const WIDE_MIN = 1100;

/** 창 너비(확대면 작업 영역)를 배율로 나눈 본문 CSS 너비로 큰 화면인지 본다. */
function useWide(windowId: string): boolean {
  const win = useWindows((s) => s.wins.find((w) => w.id === windowId));
  useWindows((s) => s.insetRight);
  const zoom = useZoom((s) => zoomOf(s.levels, 'chat'));
  if (!win) return false;
  const outer = win.maximized ? workArea().w : win.w;
  return (outer * 100) / zoom >= WIDE_MIN;
}

export const ASK_REJECTED = '앞의 요청이 끝난 뒤 다시 보내 주세요.';

/** 이미 보낸 ask 의 params 객체(StrictMode 가 효과를 두 번 불러도, 같은 params 로 다시 그려져도 한 번만 보낸다). */
const asked = new WeakSet<object>();

/** 보내기가 거절됐다는 안내를 지금 대화의 안내 줄에 둔다(이미 다른 안내가 있으면 그대로). */
function noteRejected() {
  useChat.setState((s) => {
    const id = s.currentId;
    if (id === null) return s.notice ? s : { notice: ASK_REJECTED };
    const t = s.threads[id];
    return !t || t.notice ? s : { threads: { ...s.threads, [id]: { ...t, notice: ASK_REJECTED } } };
  });
}

/**
 * params: session(그 대화 열기) · resume_questionnaire(제출한 질문지로 이어 가기) · resume_approval(다시 짜기로
 * 거부한 승인 건으로 이어 가기) · compose(입력창에 미리 넣을 글, 보내지는 않는다 — Composer 가 읽는다) ·
 * ask(보낼 글: session 이 있으면 그 대화를 열고, 없으면 새 대화에서 한 번 보낸다).
 * 열린 창에 새 params 가 오면(같은 값이어도) 다시 따른다.
 */
function useFollowParams(params: ProgramProps['params']) {
  useEffect(() => {
    const session = Number(params?.session);
    const chat = useChat.getState();
    if (params?.ask) {
      if (asked.has(params)) return; // StrictMode 의 두 번째 효과·같은 params 재그림: 대화도 다시 열지 않는다
      asked.add(params);
      const ask = params.ask;
      void (async () => {
        if (Number.isInteger(session) && session > 0) await chat.openSession(session);
        else chat.newChat();
        if (!(await useChat.getState().send(ask))) noteRejected();
      })();
      return;
    }
    if (!Number.isInteger(session) || session <= 0) return;
    const questionnaire = Number(params?.resume_questionnaire);
    const approval = Number(params?.resume_approval);
    if (questionnaire > 0) void chat.resume(session, { questionnaire_id: questionnaire });
    else if (approval > 0) void chat.resume(session, { approval_id: approval });
    else void chat.openSession(session);
  }, [params]);
}

/** 작은 화면 위쪽: 대화 고르기(펼치면 대화 목록) · 새 대화. */
function SessionBar() {
  const [open, setOpen] = useState(false);
  const title = useChat((s) => sessionTitle(s.sessions, s.currentId));
  return (
    <div className="ch-bar" onKeyDown={(e) => e.key === 'Escape' && setOpen(false)}>
      <button
        type="button"
        className="ch-pill ch-picker"
        aria-expanded={open}
        aria-label={title ? `대화 고르기: ${title}` : '대화 고르기'}
        onClick={() => setOpen(!open)}
      >
        <span className="ch-ellipsis">{title || '대화 고르기'}</span>
        <span aria-hidden="true">▾</span>
      </button>
      <span className="ch-gap" />
      <ModelPicker />
      <button type="button" className="ch-pill" onClick={() => useChat.getState().newChat()}>
        <span aria-hidden="true">+</span> 새 대화
      </button>
      {open && (
        <div className="ch-pop">
          <ThreadList popover onPicked={() => setOpen(false)} />
        </div>
      )}
    </div>
  );
}

function ConvHeader() {
  const title = useChat((s) => sessionTitle(s.sessions, s.currentId));
  return (
    <div className="ch-head">
      <h2 className="ch-title ch-ellipsis">{title || '무엇을 도와드릴까요?'}</h2>
      <span className="ch-gap" />
      <ModelPicker />
    </div>
  );
}

/** 에이전트 대화 프로그램. 창 너비 1100 이상이면 큰 화면, 미만이면 작은 화면. */
export default function Chat({ windowId, params }: ProgramProps) {
  const wide = useWide(windowId);
  useFollowParams(params);
  useEffect(() => {
    void useChat.getState().loadSessions();
  }, []);
  return (
    <div className={`ch-root ${wide ? 'is-wide' : 'is-narrow'}`}>
      {wide && <ThreadList />}
      <div className="ch-main">
        {wide ? <ConvHeader /> : <SessionBar />}
        <Conversation />
        <Composer params={params} />
      </div>
      {wide && <ContextPanel />}
    </div>
  );
}
