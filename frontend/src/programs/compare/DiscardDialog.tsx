// [복사본 버리기] 확인. 버리면 비교 목록에서 빠진다(일정은 그대로). 거절은 서버 글 그대로.
import { useState } from 'react';
import Button from '../../shared/ui/Button';
import { discardScenario, messageOf } from './compareApi';
import Dialog from './Dialog';

interface Props {
  scheduleId: number;
  scenarioId: number;
  name: string;
  onClose(): void;
  onDone(): void;
}

export default function DiscardDialog({ scheduleId, scenarioId, name, onClose, onDone }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function discard() {
    setBusy(true);
    setError(null);
    try {
      await discardScenario(scheduleId, scenarioId);
      onDone();
    } catch (e) {
      setError(messageOf(e));
      setBusy(false);
    }
  }
  return (
    <Dialog
      title="복사본 버리기"
      alert
      onClose={onClose}
      actions={
        <>
          <Button variant="danger" disabled={busy} onClick={() => void discard()}>
            버리기
          </Button>
          <Button autoFocus disabled={busy} onClick={onClose}>
            취소
          </Button>
        </>
      }
    >
      <p className="cmp-dialog-p">「{name}」 복사본을 버릴까요? 일정은 그대로이고, 버린 복사본은 비교 목록에서 빠집니다.</p>
      {error && (
        <p className="cmp-error" role="alert">
          {error}
        </p>
      )}
    </Dialog>
  );
}
