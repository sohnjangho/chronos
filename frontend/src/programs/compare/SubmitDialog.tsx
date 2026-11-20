// [이 안을 반영 (승인함으로)]: 제목만 보낸다(PM 11-20: Plan 다시 잡기 없음). 보내면 승인 배지를 다시 읽고 승인 건 id 를 넘긴다 —
// 승인함은 비교판이 포커스를 되찾은 뒤에 연다(먼저 열면 돌아온 포커스가 비교판을 다시 앞으로 올린다).
// 거절(409 잠김·낡음, 422)은 서버 글 그대로. 낡음이면 보내기를 끄고 비교판을 다시 읽는다(낡음 배지·반영 단추 꺼짐).
import { useState } from 'react';
import { refreshApprovals } from '../../os/approvals';
import { ApiError } from '../../shared/api';
import Button from '../../shared/ui/Button';
import { messageOf, submitScenario } from './compareApi';
import Dialog from './Dialog';

interface Props {
  scheduleId: number;
  scenarioId: number;
  /** 제목 기본값 = 복사본 이름. */
  name: string;
  onClose(): void;
  /** 보냈다. 승인 건 id — 여는 것은 부르는 쪽(포커스를 정리한 뒤). */
  onSent(approvalId: number): void;
  /** 서버가 낡았다고 했다. */
  onStale(): void;
}

export default function SubmitDialog({ scheduleId, scenarioId, name, onClose, onSent, onStale }: Props) {
  const [title, setTitle] = useState(name);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [blocked, setBlocked] = useState(false);
  const text = title.trim();

  async function send() {
    setBusy(true);
    setError(null);
    try {
      const out = await submitScenario(scheduleId, scenarioId, text);
      await refreshApprovals();
      onSent(out.approval_id);
    } catch (e) {
      setError(messageOf(e));
      if (e instanceof ApiError && e.code === 'scenario_stale') {
        setBlocked(true);
        onStale();
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      title="이 안을 반영"
      onClose={onClose}
      actions={
        <>
          <Button variant="primary" disabled={busy || blocked || !text} onClick={() => void send()}>
            보내기
          </Button>
          <Button onClick={onClose}>취소</Button>
        </>
      }
    >
      <p className="cmp-dialog-p">승인함으로 보냅니다. 승인되면 이 복사본이 일정의 새 버전이 됩니다.</p>
      <label className="cmp-field">
        <span>제목</span>
        <input value={title} maxLength={100} autoFocus onChange={(e) => setTitle(e.target.value)} />
      </label>
      {error && (
        <p className="cmp-error" role="alert">
          {error}
        </p>
      )}
    </Dialog>
  );
}
