import { useState } from 'react';
import { ApiError } from '../../shared/api';
import Button from '../../shared/ui/Button';
import Field from '../../shared/ui/Field';
import type { LlmError } from './model';
import { KAT_BASE_URL, notifyApi, type NotifyConnection, type NotifyPatch, type NotifySaved } from './notifyApi';
import { ErrorLine, SecretField, toProblem } from './parts';

// 키·Account ID 는 비밀번호 칸에만 있고, 요청이 끝나면(성공·실패 모두) 칸을 비운다. 화면에는 서버가 준 가린 꼴만.

function FormActions({ onCancel, onSave, canSave, label = '저장' }: { onCancel(): void; onSave(): void; canSave: boolean; label?: string }) {
  return (
    <div className="st-actions">
      <span className="st-gap" />
      <Button onClick={onCancel}>취소</Button>
      <Button variant="primary" onClick={onSave} disabled={!canSave}>
        {label}
      </Button>
    </div>
  );
}

/** 422 의 detail.field(칸 오류 — too_long · required …). 없으면 null. */
function fieldOf(e: unknown): string | null {
  const detail = e instanceof ApiError ? (e.detail as { field?: unknown } | null) : null;
  return detail && typeof detail === 'object' && typeof detail.field === 'string' ? detail.field : null;
}

/** 칸 아래 서버 글(칸 오류일 때). */
function FieldError({ text }: { text: string | undefined }) {
  return text ? <span className="ui-field-error">{text}</span> : null;
}

/** 요청 하나를 보내고 끝나면 비밀 칸을 비운다. 실패하면 서버 글을 남긴다 — 칸 오류면 그 칸 아래에, 아니면 아래 줄에. */
function useSecretRequest() {
  const [secret, setSecret] = useState('');
  const [account, setAccount] = useState('');
  const [error, setError] = useState<LlmError | null>(null);
  const [field, setField] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function run(task: () => Promise<void>) {
    setBusy(true);
    setError(null);
    setField(null);
    try {
      await task();
    } catch (e) {
      setError(toProblem(e));
      setField(fieldOf(e));
    } finally {
      setSecret('');
      setAccount('');
      setBusy(false);
    }
  }
  const clear = () => {
    setSecret('');
    setAccount('');
  };
  /** 그 칸의 오류 글(칸 오류일 때만). */
  const at = (name: string) => (error && field === name ? error.message : undefined);
  /** 칸에 붙지 않은 오류(아래 줄). */
  const general = field ? null : error;
  return { secret, setSecret, account, setAccount, error, general, at, busy, run, clear };
}

/** 연결 추가: 이름 · 공급자 · 주소 · API Key · Account ID → [저장하고 연결 테스트](저장 직후 서버가 한 번 시험한다). */
export default function NotifyAdd({ onSaved, onCancel }: { onSaved(saved: NotifySaved): void; onCancel(): void }) {
  const [name, setName] = useState('한국AI통신');
  const [url, setUrl] = useState(KAT_BASE_URL);
  const r = useSecretRequest();
  const save = () =>
    r.run(async () => {
      onSaved(await notifyApi.create({ name: name.trim(), base_url: url.trim(), secret: r.secret, account_id: r.account.trim() }));
    });
  const cancel = () => {
    r.clear();
    onCancel();
  };
  const canSave = !r.busy && name.trim() !== '' && url.trim() !== '' && r.secret !== '' && r.account.trim() !== '';
  return (
    <section className="st-card st-wizard" role="group" aria-label="알림 연결 추가">
      <b className="st-card-name">연결 추가</b>
      <div className="st-grid2">
        <Field label="이름" error={r.at('name')}>
          <input value={name} disabled={r.busy} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="공급자">
          <select value="koreaaitel" disabled={r.busy} onChange={() => undefined}>
            <option value="koreaaitel">한국AI통신</option>
          </select>
        </Field>
      </div>
      <Field label="주소" error={r.at('base_url')}>
        <input value={url} spellCheck={false} disabled={r.busy} onChange={(e) => setUrl(e.target.value)} />
      </Field>
      <div className="st-grid2">
        <div className="st-nt-secret">
          <SecretField label="API Key — 암호화 저장, 화면에는 끝 4자리만" value={r.secret} disabled={r.busy} onChange={r.setSecret} />
          <FieldError text={r.at('secret')} />
        </div>
        <div className="st-nt-secret">
          <SecretField label="Account ID — 화면에는 끝 4자리만" value={r.account} disabled={r.busy} onChange={r.setAccount} />
          <FieldError text={r.at('account_id')} />
        </div>
      </div>
      <ErrorLine error={r.general} />
      <FormActions onCancel={cancel} onSave={save} canSave={canSave} label="저장하고 연결 테스트" />
      <p className="st-muted">테스트가 통과하면 이 계정의 승인된 발신번호를 읽어 와 아래에서 고르게 합니다.</p>
    </section>
  );
}

interface EditProps {
  conn: NotifyConnection;
  onSaved(saved: NotifySaved): void;
  onCancel(): void;
}

/** URL 수정: 주소를 바꾸면 서버는 키를 함께 받아야 한다(같은 서버로 보여도). 그래서 키 칸을 처음부터 둔다. */
export function NotifyUrlForm({ conn, onSaved, onCancel }: EditProps) {
  const [url, setUrl] = useState(conn.base_url);
  const r = useSecretRequest();
  const save = () => r.run(async () => onSaved(await notifyApi.update(conn.id, { base_url: url.trim(), secret: r.secret })));
  const cancel = () => {
    r.clear();
    onCancel();
  };
  const canSave = !r.busy && url.trim() !== '' && url.trim() !== conn.base_url && r.secret !== '';
  return (
    <div className="st-edit" role="group" aria-label="URL 수정">
      <Field label="주소" error={r.at('base_url')}>
        <input value={url} spellCheck={false} disabled={r.busy} onChange={(e) => setUrl(e.target.value)} />
      </Field>
      <SecretField label="API Key — 주소를 바꾸면 키를 다시 넣습니다" value={r.secret} disabled={r.busy} onChange={r.setSecret} />
      <ErrorLine error={r.general} />
      <FormActions onCancel={cancel} onSave={save} canSave={canSave} />
    </div>
  );
}

/** 키 교체: 새 API Key 와(바꿀 때만) Account ID. 넣은 칸만 보낸다. */
export function NotifyKeyForm({ conn, onSaved, onCancel }: EditProps) {
  const r = useSecretRequest();
  const body = (): NotifyPatch => ({
    ...(r.secret !== '' ? { secret: r.secret } : {}),
    ...(r.account.trim() !== '' ? { account_id: r.account.trim() } : {}),
  });
  const save = () => r.run(async () => onSaved(await notifyApi.update(conn.id, body())));
  const cancel = () => {
    r.clear();
    onCancel();
  };
  return (
    <div className="st-edit" role="group" aria-label="키 교체">
      <div className="st-grid2">
        <SecretField label="API Key — 새 키" value={r.secret} disabled={r.busy} onChange={r.setSecret} autoFocus />
        <div className="st-nt-secret">
          <SecretField label="Account ID — 바꿀 때만" value={r.account} disabled={r.busy} onChange={r.setAccount} />
          <FieldError text={r.at('account_id')} />
        </div>
      </div>
      <ErrorLine error={r.general} />
      <FormActions onCancel={cancel} onSave={save} canSave={!r.busy && (r.secret !== '' || r.account.trim() !== '')} />
    </div>
  );
}
