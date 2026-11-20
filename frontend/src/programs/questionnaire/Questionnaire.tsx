import { useEffect, useState } from 'react';
import type { ProgramProps } from '../../os/registry';
import { useWindows } from '../../os/windowStore';
import Button from '../../shared/ui/Button';
import FilledList from './FilledList';
import GroupNav from './GroupNav';
import QuestionCard from './QuestionCard';
import Submitted from './Submitted';
import type { QView } from './qApi';
import { firstOpen, flatten, positiveId } from './model';
import { useQuestionnaire } from './useQuestionnaire';
import './questionnaire.css';

const NO_CHAT = '제출했습니다. 대화창에서 이어서 요청해 주세요.';

/**
 * 질문지 프로그램. params: id(질문지) · session(이어 갈 대화, 없으면 질문지를 만든 대화).
 * 제출하면 그 대화를 resume_questionnaire 로 이어 가게 열고 이 창을 닫는다(Task 14 의 params 방식).
 */
export default function Questionnaire({ windowId, params }: ProgramProps) {
  const id = positiveId(params?.id);
  const { load, notice, answer, submit, markSubmitted } = useQuestionnaire(id);
  const [doneNote, setDoneNote] = useState<string | null>(null);
  useEffect(() => setDoneNote(null), [id]);
  const title = load.kind === 'ready' ? load.view.title : null;
  useEffect(() => {
    useWindows.getState().setTitle(windowId, title ? `질문지 — ${title}` : '질문지');
  }, [windowId, title]);

  if (load.kind !== 'ready') {
    const text = load.kind === 'loading' ? '질문지를 읽는 중…' : load.kind === 'missing' ? '질문지를 찾을 수 없습니다.' : load.message;
    return (
      <div className="qn-root">
        <p className="qn-empty" role={load.kind === 'failed' ? 'alert' : undefined}>
          {text}
        </p>
      </div>
    );
  }
  const view = load.view;
  const fromParams = positiveId(params?.session);
  const session = fromParams ?? view.chat_session_id;
  return (
    <div className="qn-root">
      {view.status === 'submitted' ? (
        <Submitted view={view} notice={doneNote} />
      ) : (
        <Answering
          key={view.id}
          view={view}
          notice={notice}
          onAnswer={answer}
          onChat={() => useWindows.getState().open('chat', session ? { session: String(session) } : undefined)}
          onSubmit={async () => {
            if (!(await submit())) return false;
            const wins = useWindows.getState();
            if (session) {
              wins.open('chat', { session: String(session), resume_questionnaire: String(view.id) });
              wins.close(windowId);
            } else {
              setDoneNote(NO_CHAT);
              markSubmitted();
            }
            return true;
          }}
        />
      )}
    </div>
  );
}

interface AnsweringProps {
  view: QView;
  notice: string | null;
  onAnswer(questionId: string, value: string | null): Promise<boolean>;
  onChat(): void;
  onSubmit(): Promise<boolean>;
}

/** 답하는 중: 왼쪽 목차 · 오른쪽 한 질문과 이미 채운 것 · 아래 이동·대화·제출. */
function Answering({ view, notice, onAnswer, onChat, onSubmit }: AnsweringProps) {
  const all = flatten(view);
  const [currentId, setCurrentId] = useState(() => firstOpen(all)?.id ?? null);
  const [focus, setFocus] = useState<{ id: string; n: number } | null>(null);
  const at = Math.max(0, all.findIndex((q) => q.id === currentId));
  const cur = all[at];
  if (!cur) return <p className="qn-empty">질문이 없습니다.</p>;
  const go = (qid: string) => {
    setCurrentId(qid);
    setFocus(null);
  };
  const edit = (qid: string) => {
    setCurrentId(qid);
    setFocus((f) => ({ id: qid, n: (f?.n ?? 0) + 1 }));
  };
  const last = at === all.length - 1;
  const { answered, total } = view.progress;
  const group = view.groups.find((g) => g.name === cur.group);
  return (
    <div className="qn-body">
      <GroupNav view={view} currentId={cur.id} onPick={go} />
      <div className="qn-main">
        <div className="qn-scroll">
          <p className="qn-pos">{`${cur.group} · ${cur.pos}번째 질문 (${cur.size}개 중)`}</p>
          <QuestionCard
            key={cur.id}
            question={cur}
            focusRequest={focus?.id === cur.id ? focus.n : undefined}
            onAnswer={(value) => onAnswer(cur.id, value)}
          />
          <FilledList prefilled={view.prefilled} answered={group?.questions.filter((q) => q.answer) ?? []} onEdit={edit} />
        </div>
        {notice && (
          <p className="qn-notice" role="alert">
            {notice}
          </p>
        )}
        <Actions
          prev={at > 0 ? () => go(all[at - 1].id) : null}
          next={last ? null : () => go(all[at + 1].id)}
          answered={answered}
          assumed={total - answered}
          onChat={onChat}
          onSubmit={onSubmit}
        />
      </div>
    </div>
  );
}

interface ActionsProps {
  /** 없으면 그 단추를 끈다(처음·마지막 질문). */
  prev: (() => void) | null;
  next: (() => void) | null;
  answered: number;
  assumed: number;
  onChat(): void;
  onSubmit(): Promise<boolean>;
}

/** 아래 줄: [이전] [다음 질문] · [대화로 답하기] · [제출하고 생성 (답 m개 · 가정 k개)] — 제출은 늘 켜져 있다. */
function Actions({ prev, next, answered, assumed, onChat, onSubmit }: ActionsProps) {
  const [sending, setSending] = useState(false);
  return (
    <div className="qn-actions">
      <Button disabled={!prev} onClick={() => prev?.()}>
        이전
      </Button>
      <Button variant={next ? 'primary' : 'default'} disabled={!next} onClick={() => next?.()}>
        다음 질문
      </Button>
      <span className="qn-gap" />
      <Button onClick={onChat}>대화로 답하기</Button>
      <Button
        variant={next ? 'default' : 'primary'}
        disabled={sending}
        onClick={async () => {
          setSending(true);
          if (!(await onSubmit())) setSending(false);
        }}
      >
        {`제출하고 생성 (답 ${answered}개 · 가정 ${assumed}개)`}
      </Button>
    </div>
  );
}
