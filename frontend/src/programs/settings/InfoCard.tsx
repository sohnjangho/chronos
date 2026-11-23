import { useState } from 'react';
import Badge, { type Tone } from '../../shared/ui/Badge';
import Button from '../../shared/ui/Button';
import Field from '../../shared/ui/Field';
import { infoApi, presetLabel, type InfoConnection, type InfoPatch, type InfoTest } from './infoApi';
import { checkedText, type LlmError } from './model';
import { ErrorLine, SecretField, toProblem } from './parts';

/** 서비스 키 칸 아래 안내(추가·고치기 공통). */
export const KEY_HINT = '공공데이터포털 마이페이지의 일반 인증키(인코딩·디코딩 아무거나)';

export type Mode = 'idle' | 'edit' | 'delete';

export interface Outcome {
  note?: string;
  test?: InfoTest;
  error?: LlmError | null;
}

export const STATUS: Record<InfoConnection['status'], { tone: Tone; text: string }> = {
  ok: { tone: 'success', text: '연결됨' },
  failed: { tone: 'danger', text: '연결 실패' },
  unknown: { tone: 'neutral', text: '미확인' },
};

/** 끝 4자리만. 키가 짧아 서버가 끝자리를 주지 않으면 점만. */
const maskedKey = (last4: string) => '•'.repeat(last4 ? 12 : 8) + last4;

/** 시험 결과: 요약 한 줄 + 서비스마다 한 줄(OK·실패, 응답 시간, 실패면 서버 글과 코드). */
function TestResult({ test }: { test: InfoTest }) {
  return (
    <div className="st-info-result" role="status" aria-label="연결 테스트 결과">
      <div className={`st-probe ${test.ok ? 'st-probe-ok' : 'st-probe-fail'}`}>{test.summary}</div>
      <ul className="st-info-services">
        {test.services.map((s) => (
          <li key={s.service}>
            <div className="st-info-line">
              <Badge tone={s.ok ? 'success' : 'danger'}>{s.ok ? 'OK' : '실패'}</Badge>
              <b>{s.label}</b>
              <span className="st-muted">{`${s.latency_ms}ms`}</span>
            </div>
            <ErrorLine error={s.error} />
          </li>
        ))}
      </ul>
    </div>
  );
}

/** 바뀐 것만 보낸다. 키는 넣었을 때만. */
function changes(conn: InfoConnection, name: string, url: string, secret: string): InfoPatch {
  const body: InfoPatch = {};
  if (name.trim() !== conn.name) body.name = name.trim();
  if (url.trim() !== conn.base_url) body.base_url = url.trim();
  if (secret !== '') body.secret = secret;
  return body;
}

/** 고치기: 이름·주소·키. 다른 주소면 서버가 422 secret_required 를 주고, 그 글을 그대로 보인다. 저장·취소 때 키 칸을 비운다. */
function EditForm({ conn, onSaved, onCancel }: { conn: InfoConnection; onSaved(): void; onCancel(): void }) {
  const [name, setName] = useState(conn.name);
  const [url, setUrl] = useState(conn.base_url);
  const [secret, setSecret] = useState('');
  const [error, setError] = useState<LlmError | null>(null);
  const [busy, setBusy] = useState(false);
  const body = changes(conn, name, url, secret);
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await infoApi.update(conn.id, body);
      setSecret('');
      onSaved();
    } catch (e) {
      setError(toProblem(e));
    } finally {
      setBusy(false);
    }
  };
  const cancel = () => {
    setSecret('');
    onCancel();
  };
  const canSave = !busy && name.trim() !== '' && url.trim() !== '' && Object.keys(body).length > 0;
  return (
    <div className="st-edit" role="group" aria-label="연결 고치기">
      <div className="st-grid2">
        <Field label="이름">
          <input value={name} disabled={busy} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="주소">
          <input value={url} spellCheck={false} disabled={busy} onChange={(e) => setUrl(e.target.value)} />
        </Field>
      </div>
      <SecretField label="서비스 키 — 바꿀 때만 넣습니다" value={secret} disabled={busy} onChange={setSecret} hint={KEY_HINT} />
      <ErrorLine error={error} />
      <div className="st-actions">
        <span className="st-gap" />
        <Button onClick={cancel}>취소</Button>
        <Button variant="primary" onClick={save} disabled={!canSave}>
          저장
        </Button>
      </div>
    </div>
  );
}

export function DeletePanel({
  name,
  note = '날씨 근거 도구가 이 키를 더 쓰지 못합니다.',
  onConfirm,
  onCancel,
}: {
  name: string;
  note?: string;
  onConfirm(): void;
  onCancel(): void;
}) {
  return (
    <div className="st-confirm" role="group" aria-label="연결 지우기 확인">
      <p className="st-wrap">{`「${name}」 연결을 지울까요? ${note}`}</p>
      <div className="st-actions">
        <span className="st-gap" />
        <Button onClick={onCancel}>취소</Button>
        <Button variant="danger" onClick={onConfirm}>
          지우기
        </Button>
      </div>
    </div>
  );
}

function Facts({ conn }: { conn: InfoConnection }) {
  return (
    <dl className="st-facts">
      <dt>주소</dt>
      <dd>{conn.base_url}</dd>
      <dt>서비스 키</dt>
      <dd>{maskedKey(conn.secret_last4)}</dd>
      <dt>확인</dt>
      <dd>{checkedText(conn.checked_at, null)}</dd>
    </dl>
  );
}

/** 정보 API 연결 카드: 이름·종류·상태·주소·키 끝 4자리·확인 시각과 [연결 테스트][고치기][지우기]. */
export default function InfoCard({ conn, onChanged }: { conn: InfoConnection; onChanged(): void }) {
  const [mode, setMode] = useState<Mode>('idle');
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [busy, setBusy] = useState(false);
  const status = STATUS[conn.status];
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
  const edit = (m: Mode) => {
    setOutcome(null);
    setMode(m);
  };
  const saved = () => {
    setMode('idle');
    setOutcome({ note: '저장했습니다.' });
    onChanged();
  };
  const locked = busy || mode !== 'idle';
  return (
    <article className="st-card" aria-label={conn.name}>
      <div className="st-card-head">
        <b className="st-card-name">{conn.name}</b>
        <Badge tone="info">{presetLabel(conn.preset)}</Badge>
        <span className="st-gap" />
        <Badge tone={status.tone}>{status.text}</Badge>
      </div>
      <Facts conn={conn} />
      <div className="st-actions">
        <Button disabled={locked} onClick={() => run(async () => ({ test: await infoApi.test(conn.id) }))}>
          연결 테스트
        </Button>
        <Button disabled={locked} onClick={() => edit('edit')}>
          고치기
        </Button>
        <span className="st-gap" />
        <Button className="st-danger-text" disabled={locked} onClick={() => edit('delete')}>
          지우기
        </Button>
      </div>
      {mode === 'edit' && <EditForm conn={conn} onSaved={saved} onCancel={() => setMode('idle')} />}
      {mode === 'delete' && (
        <DeletePanel name={conn.name} onCancel={() => setMode('idle')} onConfirm={() => run(async () => (await infoApi.remove(conn.id), {}))} />
      )}
      {outcome?.note && <p className="st-note">{outcome.note}</p>}
      {outcome?.test && <TestResult test={outcome.test} />}
      <ErrorLine error={outcome?.error} />
    </article>
  );
}
