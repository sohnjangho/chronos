import { useState } from 'react';
import Button from '../../shared/ui/Button';
import Field from '../../shared/ui/Field';
import { llmApi, type ConnectionPatch } from './llmApi';
import type { Connection, ConnectionSaved, LlmError } from './model';
import { ErrorLine, SecretField, toProblem } from './parts';

interface FormProps {
  conn: Connection;
  onSaved(saved: ConnectionSaved): void;
  onCancel(): void;
}

/** PATCH 를 보내고, 성공하면 키 칸을 비운 뒤 알린다. 실패하면 서버 글을 돌려준다. */
function usePatch(conn: Connection, onSaved: FormProps['onSaved']) {
  const [secret, setSecret] = useState('');
  const [error, setError] = useState<LlmError | null>(null);
  const [busy, setBusy] = useState(false);
  async function send(body: ConnectionPatch): Promise<LlmError | null> {
    setBusy(true);
    setError(null);
    try {
      const saved = await llmApi.update(conn.id, body);
      setSecret('');
      onSaved(saved);
      return null;
    } catch (e) {
      const problem = toProblem(e);
      setError(problem);
      return problem;
    } finally {
      setBusy(false);
    }
  }
  return { secret, setSecret, error, busy, send };
}

function FormActions({ onCancel, onSave, canSave }: { onCancel(): void; onSave(): void; canSave: boolean }) {
  return (
    <div className="st-actions">
      <span className="st-gap" />
      <Button onClick={onCancel}>취소</Button>
      <Button variant="primary" onClick={onSave} disabled={!canSave}>
        저장
      </Button>
    </div>
  );
}

/**
 * URL 수정. 다른 서버 주소로 바꾸면 서버가 422 secret_required 를 주고,
 * 그때 그 글을 그대로 보이며 키 칸을 연다. 다음 저장은 주소와 키를 함께 보낸다.
 */
export function UrlForm({ conn, onSaved, onCancel }: FormProps) {
  const [url, setUrl] = useState(conn.base_url);
  const [needKey, setNeedKey] = useState(false);
  const p = usePatch(conn, onSaved);
  const save = async () => {
    const body = needKey ? { base_url: url.trim(), secret: p.secret } : { base_url: url.trim() };
    const problem = await p.send(body);
    if (problem?.code === 'secret_required') setNeedKey(true);
  };
  const cancel = () => {
    p.setSecret('');
    onCancel();
  };
  const changed = url.trim() !== '' && (url.trim() !== conn.base_url || needKey);
  return (
    <div className="st-edit" role="group" aria-label="URL 수정">
      <Field label="URL">
        <input value={url} spellCheck={false} disabled={p.busy} onChange={(e) => setUrl(e.target.value)} />
      </Field>
      {needKey && (
        <SecretField label="API 키 — 새 주소로 보낼 키" value={p.secret} disabled={p.busy} onChange={p.setSecret} autoFocus />
      )}
      <ErrorLine error={p.error} />
      <FormActions onCancel={cancel} onSave={save} canSave={!p.busy && changed && (!needKey || p.secret !== '')} />
    </div>
  );
}

/** 키 교체. 새 키로 다시 연결 테스트를 하고, 화면에는 서버가 준 끝 4자리만 보인다. */
export function KeyForm({ conn, onSaved, onCancel }: FormProps) {
  const p = usePatch(conn, onSaved);
  const cancel = () => {
    p.setSecret('');
    onCancel();
  };
  return (
    <div className="st-edit" role="group" aria-label="키 교체">
      <SecretField label="API 키 — 새 키" value={p.secret} disabled={p.busy} onChange={p.setSecret} />
      <ErrorLine error={p.error} />
      <FormActions onCancel={cancel} onSave={() => p.send({ secret: p.secret })} canSave={!p.busy && p.secret !== ''} />
    </div>
  );
}

/** 지우기 전 화면 안에서 묻는다(브라우저 확인 창은 쓰지 않는다). */
export function DeletePanel({ name, onConfirm, onCancel }: { name: string; onConfirm(): void; onCancel(): void }) {
  return (
    <div className="st-confirm" role="group" aria-label="연결 삭제 확인">
      <p className="st-wrap">
        「{name}」 연결을 지울까요? 이 연결을 쓰던 작업별 모델 배정은 기본값으로 돌아갑니다.
      </p>
      <div className="st-actions">
        <span className="st-gap" />
        <Button onClick={onCancel}>취소</Button>
        <Button variant="danger" onClick={onConfirm}>
          삭제
        </Button>
      </div>
    </div>
  );
}
