import { useEffect, useState } from 'react';
import type { Role } from '../../os/session';
import Button from '../../shared/ui/Button';
import Field from '../../shared/ui/Field';
import Table, { type Column } from '../../shared/ui/Table';
import type { Account, LlmError } from './model';
import { ErrorLine, toProblem } from './parts';
import { settingsApi } from './settingsApi';

const ROLE_LABELS: Record<Role, string> = { admin: '관리자', user: '사용자' };
const COLUMNS: Column<Account>[] = [
  { key: 'name', header: '이름' },
  { key: 'login_id', header: '아이디' },
  { key: 'role', header: '등급', render: (a) => ROLE_LABELS[a.role] },
];

interface FormProps {
  onDone(): void;
  onCancel(): void;
}

/** 보내고, 성공하면 비밀번호 칸을 비우고 알린다. 실패하면 서버 글. */
function useSubmit(onDone: () => void) {
  const [password, setPassword] = useState('');
  const [error, setError] = useState<LlmError | null>(null);
  const [busy, setBusy] = useState(false);
  async function submit(task: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await task();
      setPassword('');
      onDone();
    } catch (e) {
      setError(toProblem(e));
    } finally {
      setBusy(false);
    }
  }
  return { password, setPassword, error, busy, submit };
}

function RoleSelect({ value, onChange }: { value: Role; onChange(r: Role): void }) {
  return (
    <Field label="등급">
      <select value={value} onChange={(e) => onChange(e.target.value as Role)}>
        <option value="user">사용자</option>
        <option value="admin">관리자</option>
      </select>
    </Field>
  );
}

function PasswordField({ label, hint, value, onChange }: { label: string; hint?: string; value: string; onChange(v: string): void }) {
  return (
    <Field label={label} hint={hint}>
      <input type="password" autoComplete="new-password" value={value} onChange={(e) => onChange(e.target.value)} />
    </Field>
  );
}

function FormActions({ label, onCancel, onSave, canSave }: { label: string; onCancel(): void; onSave(): void; canSave: boolean }) {
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

function NewAccountForm({ onDone, onCancel }: FormProps) {
  const [loginId, setLoginId] = useState('');
  const [name, setName] = useState('');
  const [role, setRole] = useState<Role>('user');
  const s = useSubmit(onDone);
  const create = () =>
    s.submit(() => settingsApi.createAccount({ login_id: loginId.trim(), name: name.trim(), role, password: s.password }));
  return (
    <section className="st-card st-edit" aria-label="계정 추가">
      <div className="st-grid2">
        <Field label="아이디">
          <input value={loginId} onChange={(e) => setLoginId(e.target.value)} />
        </Field>
        <Field label="이름">
          <input value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <RoleSelect value={role} onChange={setRole} />
        <PasswordField label="비밀번호" value={s.password} onChange={s.setPassword} />
      </div>
      <ErrorLine error={s.error} />
      <FormActions
        label="만들기"
        onCancel={onCancel}
        onSave={create}
        canSave={!s.busy && loginId.trim() !== '' && name.trim() !== '' && s.password !== ''}
      />
    </section>
  );
}

/** 바꾼 칸만 보낸다. 비밀번호는 넣었을 때만. */
function EditAccountForm({ account, onDone, onCancel }: FormProps & { account: Account }) {
  const [name, setName] = useState(account.name);
  const [role, setRole] = useState<Role>(account.role);
  const s = useSubmit(onDone);
  const patch = {
    ...(name.trim() !== account.name ? { name: name.trim() } : {}),
    ...(role !== account.role ? { role } : {}),
    ...(s.password ? { password: s.password } : {}),
  };
  return (
    <section className="st-card st-edit" aria-label="계정 고치기">
      <b>{account.login_id}</b>
      <div className="st-grid2">
        <Field label="이름">
          <input value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <RoleSelect value={role} onChange={setRole} />
        <PasswordField label="새 비밀번호" hint="비워 두면 그대로입니다." value={s.password} onChange={s.setPassword} />
      </div>
      <ErrorLine error={s.error} />
      <FormActions
        label="저장"
        onCancel={onCancel}
        onSave={() => s.submit(() => settingsApi.updateAccount(account.id, patch))}
        canSave={!s.busy && name.trim() !== '' && Object.keys(patch).length > 0}
      />
    </section>
  );
}

/** 「계정」(관리자): 목록, 계정 추가, 줄을 누르면 이름·등급·비밀번호 고치기. */
export default function AccountSection() {
  const [users, setUsers] = useState<Account[] | null>(null);
  const [error, setError] = useState<LlmError | null>(null);
  const [tick, setTick] = useState(0);
  const [editing, setEditing] = useState<Account | 'new' | null>(null);
  useEffect(() => {
    let live = true;
    settingsApi
      .accounts()
      .then((list) => live && setUsers(list))
      .catch((e) => live && setError(toProblem(e)));
    return () => {
      live = false;
    };
  }, [tick]);
  const done = () => {
    setEditing(null);
    setTick((t) => t + 1);
  };
  const cancel = () => setEditing(null);
  return (
    <div className="st-pane">
      <div className="st-head">
        <h2>계정 (관리자·사용자)</h2>
        <Button variant="primary" onClick={() => setEditing('new')}>
          + 계정 추가
        </Button>
      </div>
      <ErrorLine error={error} />
      <Table
        label="계정"
        columns={COLUMNS}
        rows={users ?? []}
        rowKey={(a) => String(a.id)}
        onRowClick={setEditing}
        selectedKey={editing && editing !== 'new' ? String(editing.id) : undefined}
      />
      {editing === 'new' && <NewAccountForm onDone={done} onCancel={cancel} />}
      {editing && editing !== 'new' && <EditAccountForm key={editing.id} account={editing} onDone={done} onCancel={cancel} />}
    </div>
  );
}
