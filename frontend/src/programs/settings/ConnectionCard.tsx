import { useState } from 'react';
import Badge from '../../shared/ui/Badge';
import Button from '../../shared/ui/Button';
import { DeletePanel, KeyForm, UrlForm } from './EditForms';
import { llmApi } from './llmApi';
import { checkedText, providerLabel, statusView, type Connection, type ConnectionSaved, type LlmError, type Probe } from './model';
import { ErrorLine, savedButFailed, toProblem } from './parts';
import ProbeResult from './ProbeResult';

type Mode = 'idle' | 'url' | 'key' | 'delete';

/** 카드 아래에 보일 마지막 결과. */
interface Outcome {
  note?: string;
  probe?: Probe;
  error?: LlmError | null;
}

/** 끝 4자리만. 키가 짧아 서버가 끝자리를 주지 않으면 점만. */
const maskedKey = (last4: string) => '•'.repeat(last4 ? 12 : 8) + last4;

function CardHead({ conn }: { conn: Connection }) {
  const status = statusView(conn);
  return (
    <div className="st-card-head">
      <b className="st-card-name">{conn.name}</b>
      <Badge tone="info">{providerLabel(conn.provider)}</Badge>
      {conn.is_default && <Badge className="st-badge-default">기본 연결</Badge>}
      <span className="st-gap" />
      <Badge tone={status.tone}>{status.text}</Badge>
    </div>
  );
}

function Facts({ conn }: { conn: Connection }) {
  return (
    <dl className="st-facts">
      <dt>URL</dt>
      <dd>{conn.base_url}</dd>
      <dt>API 키</dt>
      <dd>{maskedKey(conn.secret_last4)}</dd>
      <dt>확인</dt>
      <dd>{checkedText(conn.checked_at, conn.latency_ms)}</dd>
    </dl>
  );
}

/** 폼이나 확인 패널이 열려 있거나 요청 중이면 다른 단추는 잠근다(열린 폼이 다른 단추로 사라지지 않게). */
function CardActions({ conn, locked, onTest, onDefault, onEdit }: {
  conn: Connection;
  locked: boolean;
  onTest(): void;
  onDefault(): void;
  onEdit(m: Mode): void;
}) {
  return (
    <div className="st-actions">
      <Button disabled={locked} onClick={onTest}>
        연결 테스트
      </Button>
      <Button disabled={locked} onClick={() => onEdit('url')}>
        URL 수정
      </Button>
      <Button disabled={locked} onClick={() => onEdit('key')}>
        키 교체
      </Button>
      {!conn.is_default && (
        <Button disabled={locked} onClick={onDefault}>
          기본으로 지정
        </Button>
      )}
      <span className="st-gap" />
      <Button className="st-danger-text" disabled={locked} onClick={() => onEdit('delete')}>
        삭제
      </Button>
    </div>
  );
}

/** 연결 카드: 이름·공급자·상태·URL·키 끝 4자리·확인 시각과 [연결 테스트][URL 수정][키 교체][기본으로 지정][삭제]. */
export default function ConnectionCard({ conn, onChanged }: { conn: Connection; onChanged(): void }) {
  const [mode, setMode] = useState<Mode>('idle');
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(task: () => Promise<Outcome>) {
    setMode('idle');
    setBusy(true);
    setOutcome(null);
    try {
      setOutcome(await task());
    } catch (e) {
      setOutcome({ error: toProblem(e) });
    } finally {
      setBusy(false);
    }
    onChanged();
  }
  const saved = (s: ConnectionSaved) => {
    setMode('idle');
    setOutcome(s.error ? { error: savedButFailed(s.error) } : { note: '저장했습니다.' });
    onChanged();
  };
  const edit = (m: Mode) => {
    setOutcome(null);
    setMode(m);
  };
  const close = () => setMode('idle');

  return (
    <article className="st-card" aria-label={conn.name}>
      <CardHead conn={conn} />
      <Facts conn={conn} />
      <CardActions
        conn={conn}
        locked={busy || mode !== 'idle'}
        onTest={() => run(async () => ({ probe: await llmApi.retest(conn.id) }))}
        onDefault={() => run(async () => (await llmApi.update(conn.id, { is_default: true }), { note: '기본 연결로 정했습니다.' }))}
        onEdit={edit}
      />
      {mode === 'url' && <UrlForm conn={conn} onSaved={saved} onCancel={close} />}
      {mode === 'key' && <KeyForm conn={conn} onSaved={saved} onCancel={close} />}
      {mode === 'delete' && (
        <DeletePanel name={conn.name} onCancel={close} onConfirm={() => run(async () => (await llmApi.remove(conn.id), {}))} />
      )}
      {outcome?.note && <p className="st-note">{outcome.note}</p>}
      {outcome?.probe && <ProbeResult probe={outcome.probe} />}
      <ErrorLine error={outcome?.error} />
    </article>
  );
}
