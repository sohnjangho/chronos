// 결정 상자(대기 건만): 의견 칸과 [거부][거부하고 다시 짜게 하기][승인하고 반영]. 다시 짜기는 의견이 있어야 한다(R3).
import { useId, useRef, useState } from 'react';
import Button from '../../shared/ui/Button';
import type { ApprovalDetail, Decision } from './apvApi';
import { ro } from './format';

interface Props {
  item: ApprovalDetail;
  /** 대상 일정의 지금 버전(모르면 null·없음 — 그때는 승인 건의 기준 버전으로 센다). */
  currentVersion?: number | null;
  /** 서버에 결정을 보내고 끝나면 풀린다(결과 글은 부르는 쪽이 보인다). */
  onDecide(decision: Decision, note: string): Promise<void>;
}

const NOTE_REQUIRED = '다시 짜게 하려면 이유를 적어 주세요.';

const hintOf = (item: ApprovalDetail, current: number | null) => {
  if (item.blocked) return ''; // 반영할 수 없는 건 — 「승인하면 …」을 말하지 않는다
  if (item.kind === 'change' && current !== null && current !== item.base_version) {
    return `버전 ${item.base_version} 기준으로 만든 건이라 지금 일정(버전 ${current})에는 그대로 반영되지 않습니다 — 승인하면 충돌로 남습니다.`;
  }
  if (item.kind === 'rule') {
    return '승인하면 내 규칙으로 저장됩니다. 일정은 바뀌지 않고, 조건·규칙 창에서 끄거나 지울 수 있습니다.';
  }
  if (item.kind === 'first_save') {
    return '승인하면 새 일정(버전 1, Plan)으로 저장되고, 탐색기에서 볼 수 있습니다.';
  }
  if (item.summary?.rule && item.summary?.plan_change === false) {
    return `승인하면 내 규칙이 반영되어 버전 ${ro(item.base_version + 1)} 저장됩니다. 기존 기준선(Plan)은 유지됩니다.`;
  }
  if (item.summary?.plan_change === true) {
    return `승인하면 버전 ${ro(item.base_version + 1)} 저장되고, 기준선(Plan)도 이 안으로 새로 잡힙니다. 탐색기에서 되돌릴 수 있습니다.`;
  }
  return `승인하면 버전 ${ro(item.base_version + 1)} 저장되고, 탐색기에서 되돌릴 수 있습니다.`;
};

function Actions({ hint, busy, blocked, decide }: { hint: string; busy: boolean; blocked: boolean; decide(d: Decision): void }) {
  return (
    <div className="apv-decide-row">
      {hint && <span className="apv-muted apv-wrap">{hint}</span>}
      <Button className="apv-reject" disabled={busy} onClick={() => decide('reject')}>
        거부
      </Button>
      <Button disabled={busy} onClick={() => decide('reject_retry')}>
        거부하고 다시 짜게 하기
      </Button>
      <Button variant="primary" disabled={busy || blocked} onClick={() => decide('approve')}>
        승인하고 반영
      </Button>
    </div>
  );
}

export default function DecisionBox({ item, currentVersion = null, onDecide }: Props) {
  const id = useId();
  const box = useRef<HTMLTextAreaElement>(null);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function decide(decision: Decision) {
    const text = note.trim();
    if (decision === 'reject_retry' && !text) {
      setError(NOTE_REQUIRED);
      box.current?.focus();
      return;
    }
    setError(null);
    setBusy(true);
    try {
      await onDecide(decision, text);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="apv-decide" aria-label="결정">
      <b className="apv-decide-h">결정</b>
      <label className="apv-note-label" htmlFor={id}>
        의견 (선택) — 거부할 때 이유를 적으면 에이전트가 반영해 다시 짭니다
      </label>
      <textarea
        id={id}
        ref={box}
        className="apv-note-box"
        value={note}
        maxLength={1000}
        aria-invalid={error !== null}
        onChange={(e) => {
          setNote(e.target.value);
          if (error) setError(null);
        }}
      />
      {error && (
        <p className="apv-error" role="alert">
          {error}
        </p>
      )}
      {item.blocked && <p className="apv-error apv-wrap">{item.blocked}</p>}
      <Actions hint={hintOf(item, currentVersion)} busy={busy} blocked={Boolean(item.blocked)} decide={(d) => void decide(d)} />
    </section>
  );
}
