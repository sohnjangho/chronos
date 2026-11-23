// 연락처 창 오른쪽의 대화 칸(Task 78). 위에서부터 머리 줄(ThreadHeader) · 탭 내용 · 입력창 자리.
// 「문자 · 카카오톡」 탭: 대화(MessageThread)와 그 아래 입력창 자리(ComposerSlot — Task 79 가 채운다).
// 「통화」 탭: CallsSlot(Task 92 가 채운다). 탭 줄은 위 PersonHead 에 있다. 대화는 문자 탭이 열려 있을 때만 읽는다.
import { useRef, type ComponentType } from 'react';
import type { ThreadSlotProps } from './Contacts';
import Composer from './Composer';
import type { PersonBrief } from './contactsApi';
import MessageThread from './MessageThread';
import ThreadHeader from './ThreadHeader';
import { useThread } from './useThread';
import './thread.css';

export const DNC_REASON = '수신 거부한 사람에게는 보낼 수 없습니다.';

/** 입력창 자리가 받는 값(Task 79 의 Composer 가 이 꼴로 들어온다). */
export interface ComposerSlotProps {
  scheduleId: number;
  person: PersonBrief;
  /** 다른 프로그램이 넘긴 미리 채울 글·연결할 작업 id */
  compose?: string;
  activity?: string;
  /** 보낼 수 없는 까닭(수신 거부). 있으면 입력창도 보내기를 잠근다. */
  blocked: string | null;
  /** 초안을 만들었거나 보냈다 — 대화를 다시 읽는다(끝나면 풀리는 약속). */
  onSent: () => Promise<void>;
}

/** 통화 탭 자리가 받는 값(Task 92). */
export interface CallsSlotProps {
  scheduleId: number;
  person: PersonBrief;
  /** 열 통화 id(다른 프로그램이 넘김) */
  call?: string;
  onChanged: () => void;
}

function CallsPlaceholder({ person }: CallsSlotProps) {
  return <p className="ct-muted ct-pad">{`${person.name} 님과의 통화 기록이 여기에 보입니다.`}</p>;
}

/** 입력창 자리(Task 79 Composer). */
const ComposerSlot: ComponentType<ComposerSlotProps> = Composer;
/** 통화 탭 자리. Task 92 가 이 한 줄을 통화 목록으로 바꾼다. */
const CallsSlot: ComponentType<CallsSlotProps> = CallsPlaceholder;

function MessagesTab({ scheduleId, person, compose, activity, onChanged }: Omit<ThreadSlotProps, 'tab' | 'call'>) {
  const root = useRef<HTMLDivElement>(null);
  const thread = useThread(scheduleId, person.id, root, onChanged);
  // 수신 거부는 번호 기준이라 대화 응답의 값이 가장 새것이다.
  const blocked = (thread.contact ?? person).do_not_contact ? DNC_REASON : null;
  return (
    <div className="th-tab" ref={root}>
      <MessageThread scheduleId={scheduleId} thread={thread} blocked={blocked} />
      {blocked && <p className="th-strip is-bad">수신 거부 — 이 사람에게는 보낼 수 없습니다. 주고받은 기록은 볼 수 있습니다.</p>}
      <div className="th-composer" data-slot="composer">
        <ComposerSlot scheduleId={scheduleId} person={person} compose={compose} activity={activity} blocked={blocked} onSent={thread.reload} />
      </div>
    </div>
  );
}

export default function ThreadPane({ scheduleId, person, tab, compose, activity, call, onChanged }: ThreadSlotProps) {
  return (
    <div className="th-pane">
      <ThreadHeader key={`head-${person.id}`} scheduleId={scheduleId} person={person} />
      {tab === 'calls' ? (
        <div className="th-tab" data-slot="calls">
          <CallsSlot scheduleId={scheduleId} person={person} call={call} onChanged={onChanged} />
        </div>
      ) : (
        <MessagesTab key={`messages-${person.id}`} scheduleId={scheduleId} person={person} compose={compose} activity={activity} onChanged={onChanged} />
      )}
    </div>
  );
}
