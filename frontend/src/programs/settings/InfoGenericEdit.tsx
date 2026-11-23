import { useState } from 'react';
import Button from '../../shared/ui/Button';
import GenericFieldset, { missing, type DraftErrors, type GenericDraft } from './InfoGenericFields';
import { infoApi, type InfoConnection, type InfoPatch } from './infoApi';
import type { LlmError } from './model';
import { ErrorLine, toProblem } from './parts';

const TEXT_FIELDS = ['name', 'base_url', 'description', 'usage', 'key_name', 'test_path'] as const;

const draftOf = (c: InfoConnection): GenericDraft => ({
  name: c.name,
  base_url: c.base_url,
  secret: '',
  description: c.description,
  usage: c.usage,
  key_in: c.key_in,
  key_name: c.key_name,
  test_path: c.test_path,
});

/** 바뀐 것만 보낸다(쓰는 법은 앞뒤 공백도 그대로). 키는 넣었을 때만. */
function changes(conn: InfoConnection, d: GenericDraft): InfoPatch {
  const body: InfoPatch = {};
  for (const k of TEXT_FIELDS) {
    const v = k === 'usage' ? d[k] : d[k].trim();
    if (v !== conn[k]) body[k] = v;
  }
  if (d.key_in !== conn.key_in) body.key_in = d.key_in;
  if (d.secret !== '') body.secret = d.secret;
  return body;
}

/**
 * 범용 연결 고치기: 이름·주소·설명·쓰는 법·키 넣는 곳·키 이름·시험 경로, 키는 바꿀 때만.
 * 다른 주소면 서버가 422 secret_required 를 주고 그 글을 그대로 보인다. pathError 는 연결 시험의 test_path_required 글.
 */
export default function GenericEditForm({ conn, pathError, onSaved, onCancel }: { conn: InfoConnection; pathError?: string; onSaved(): void; onCancel(): void }) {
  const [draft, setDraft] = useState<GenericDraft>(() => draftOf(conn));
  const [errors, setErrors] = useState<DraftErrors>(pathError ? { test_path: pathError } : {});
  const [error, setError] = useState<LlmError | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (patch: Partial<GenericDraft>) => setDraft((d) => ({ ...d, ...patch }));
  const body = changes(conn, draft);
  const save = async () => {
    const missed = missing(draft, false);
    setErrors(missed);
    if (Object.keys(missed).length > 0) return;
    setBusy(true);
    setError(null);
    try {
      await infoApi.update(conn.id, body);
      set({ secret: '' });
      onSaved();
    } catch (e) {
      setError(toProblem(e));
    } finally {
      setBusy(false);
    }
  };
  const cancel = () => {
    set({ secret: '' });
    onCancel();
  };
  return (
    <div className="st-edit" role="group" aria-label="연결 고치기">
      <GenericFieldset draft={draft} set={set} errors={errors} busy={busy} keyLabel="키 — 바꿀 때만 넣습니다" keyHint="주소를 바꾸면 키를 다시 넣어야 합니다" />
      <ErrorLine error={error} />
      <div className="st-actions">
        <span className="st-gap" />
        <Button onClick={cancel}>취소</Button>
        <Button variant="primary" onClick={save} disabled={busy || Object.keys(body).length === 0}>
          저장
        </Button>
      </div>
    </div>
  );
}
