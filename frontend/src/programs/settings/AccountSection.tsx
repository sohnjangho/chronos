import { useEffect, useState } from 'react';
import { useSession, type Role } from '../../os/session';
import Badge, { type Tone } from '../../shared/ui/Badge';
import Button from '../../shared/ui/Button';
import Field from '../../shared/ui/Field';
import Table, { type Column } from '../../shared/ui/Table';
import type { Account, AccountStatus, LlmError } from './model';
import { ErrorLine, toProblem } from './parts';
import { settingsApi } from './settingsApi';

const ROLE_LABELS: Record<Role, string> = { admin: '관리자', user: '사용자', field: '현장 관리자' };
const STATUS_META: Record<AccountStatus, { label: string; tone: Tone }> = {
  pending: { label: '승인 대기', tone: 'warning' },
  active: { label: '활성', tone: 'success' },
  rejected: { label: '거절됨', tone: 'danger' },
  disabled: { label: '비활성', tone: 'neutral' },
};

const COLUMNS: Column<Account>[] = [
  { key: 'name', header: '이름', render: (a) => <span title={a.name}>{a.name}</span> },
  { key: 'login_id', header: '아이디', render: (a) => <span title={a.login_id}>{a.login_id}</span> },
  { key: 'role', header: '등급', render: (a) => ROLE_LABELS[a.role] },
  {
    key: 'org',
    header: '소속 · 부서',
    render: (a) => {
      const txt = [a.organization, a.department].filter(Boolean).join(' / ') || '—';
      return <span title={txt}>{txt}</span>;
    },
  },
  {
    key: 'status',
    header: '상태',
    render: (a) => {
      const st = STATUS_META[a.status ?? 'active'] ?? STATUS_META.active;
      return <Badge tone={st.tone}>{st.label}</Badge>;
    },
  },
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
        <option value="field">현장 관리자</option>
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
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [organization, setOrganization] = useState('');
  const [department, setDepartment] = useState('');
  const s = useSubmit(onDone);
  const create = () =>
    s.submit(() =>
      settingsApi.createAccount({
        login_id: loginId.trim(),
        name: name.trim(),
        role,
        password: s.password,
        ...(email.trim() ? { email: email.trim() } : {}),
        ...(phone.trim() ? { phone: phone.trim() } : {}),
        ...(organization.trim() ? { organization: organization.trim() } : {}),
        ...(department.trim() ? { department: department.trim() } : {}),
      }),
    );
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
        <Field label="이메일 (선택)">
          <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@company.com" />
        </Field>
        <Field label="연락처 (선택)">
          <input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="010-1234-5678" />
        </Field>
        <Field label="소속 회사 · 현장 (선택)">
          <input value={organization} onChange={(e) => setOrganization(e.target.value)} />
        </Field>
        <Field label="부서 · 직책 (선택)">
          <input value={department} onChange={(e) => setDepartment(e.target.value)} />
        </Field>
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
function EditAccountForm({ account, isSelf, onDone, onCancel }: FormProps & { account: Account; isSelf: boolean }) {
  const [name, setName] = useState(account.name);
  const [role, setRole] = useState<Role>(account.role);
  const [status, setStatus] = useState<AccountStatus>(account.status ?? 'active');
  const [email, setEmail] = useState(account.email ?? '');
  const [phone, setPhone] = useState(account.phone ?? '');
  const [organization, setOrganization] = useState(account.organization ?? '');
  const [department, setDepartment] = useState(account.department ?? '');
  const s = useSubmit(onDone);
  const patch = {
    ...(name.trim() !== account.name ? { name: name.trim() } : {}),
    ...(role !== account.role ? { role } : {}),
    ...(status !== (account.status ?? 'active') ? { status } : {}),
    ...(email.trim() !== (account.email ?? '') ? { email: email.trim() } : {}),
    ...(phone.trim() !== (account.phone ?? '') ? { phone: phone.trim() } : {}),
    ...(organization.trim() !== (account.organization ?? '') ? { organization: organization.trim() } : {}),
    ...(department.trim() !== (account.department ?? '') ? { department: department.trim() } : {}),
    ...(s.password ? { password: s.password } : {}),
  };
  return (
    <section className="st-card st-edit" aria-label="계정 고치기">
      <div className="st-card-head">
        <b className="st-wrap">{account.login_id}</b>
        {account.note && <span className="st-muted">{`· 신청 메모: ${account.note}`}</span>}
      </div>
      <div className="st-grid2">
        <Field label="이름">
          <input value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <RoleSelect value={role} onChange={setRole} />
        <Field label="상태">
          <select value={status} onChange={(e) => setStatus(e.target.value as AccountStatus)}>
            <option value="active">활성</option>
            <option value="disabled">비활성 (로그인 차단)</option>
            <option value="pending">승인 대기</option>
            <option value="rejected">거절됨</option>
          </select>
        </Field>
        <PasswordField label="새 비밀번호" hint="비워 두면 그대로입니다." value={s.password} onChange={s.setPassword} />
        <Field label="이메일">
          <input value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <Field label="연락처">
          <input value={phone} onChange={(e) => setPhone(e.target.value)} />
        </Field>
        <Field label="소속 회사 · 현장">
          <input value={organization} onChange={(e) => setOrganization(e.target.value)} />
        </Field>
        <Field label="부서 · 직책">
          <input value={department} onChange={(e) => setDepartment(e.target.value)} />
        </Field>
      </div>
      <ErrorLine error={s.error} />
      <div className="st-actions">
        {!isSelf && (
          <Button
            variant="danger"
            disabled={s.busy}
            onClick={() => void s.submit(() => settingsApi.deleteAccount(account.id))}
          >
            계정 삭제
          </Button>
        )}
        <span className="st-gap" />
        <Button onClick={onCancel}>취소</Button>
        <Button
          variant="primary"
          onClick={() => void s.submit(() => settingsApi.updateAccount(account.id, patch))}
          disabled={s.busy || name.trim() === '' || Object.keys(patch).length === 0}
        >
          저장
        </Button>
      </div>
    </section>
  );
}

function PendingSignupQueue({ list, onDone }: { list: Account[]; onDone(): void }) {
  const [roles, setRoles] = useState<Record<number, Role>>({});
  const [busyId, setBusyId] = useState<number | null>(null);
  const [err, setErr] = useState<LlmError | null>(null);

  if (list.length === 0) return null;

  async function decide(acc: Account, status: 'active' | 'rejected') {
    setBusyId(acc.id);
    setErr(null);
    try {
      const picked = roles[acc.id] ?? acc.role;
      await settingsApi.updateAccount(acc.id, status === 'active' ? { status, role: picked } : { status });
      onDone();
    } catch (e) {
      setErr(toProblem(e));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <section className="st-card st-pending-box" aria-label="가입 승인 대기">
      <div className="st-card-head">
        <b>{`가입 승인 대기 (${list.length}명)`}</b>
        <span className="st-muted">승인하기 전까지 로그인할 수 없습니다. 등급을 확인한 뒤 승인 또는 거절하세요.</span>
      </div>
      <ErrorLine error={err} />
      <ul className="st-pending-list">
        {list.map((acc) => {
          const picked = roles[acc.id] ?? acc.role;
          const busy = busyId === acc.id;
          return (
            <li key={acc.id} className="st-pending-item">
              <div className="st-pending-meta">
                <b>{`${acc.name} (${acc.login_id})`}</b>
                <span className="st-muted">
                  {[acc.email, acc.phone, [acc.organization, acc.department].filter(Boolean).join(' / ')].filter(Boolean).join(' · ') || '추가 연락처 없음'}
                </span>
                {acc.note && <span className="st-pending-note">{`신청 사유: ${acc.note}`}</span>}
              </div>
              <div className="st-pending-actions">
                <select
                  aria-label={`${acc.name} 승인 등급`}
                  value={picked}
                  disabled={busy}
                  onChange={(e) => setRoles((prev) => ({ ...prev, [acc.id]: e.target.value as Role }))}
                >
                  <option value="user">사용자</option>
                  <option value="field">현장 관리자</option>
                  <option value="admin">관리자</option>
                </select>
                <Button variant="primary" disabled={busy} onClick={() => void decide(acc, 'active')}>
                  승인
                </Button>
                <Button disabled={busy} onClick={() => void decide(acc, 'rejected')}>
                  거절
                </Button>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** 「계정」(관리자): 가입 승인 대기열, 계정 목록·추가, 줄을 누르면 이름·등급·상태·비밀번호 고치기/삭제. */
export default function AccountSection() {
  const meId = useSession((s) => s.session?.user.id ?? null);
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
  const pendingUsers = (users ?? []).filter((u) => u.status === 'pending');

  return (
    <div className="st-pane">
      <div className="st-head">
        <h2>계정 (관리자·사용자)</h2>
        <Button variant="primary" onClick={() => setEditing('new')}>
          + 계정 추가
        </Button>
      </div>
      <ErrorLine error={error} />
      <PendingSignupQueue list={pendingUsers} onDone={done} />
      <Table
        label="계정"
        columns={COLUMNS}
        rows={users ?? []}
        rowKey={(a) => String(a.id)}
        onRowClick={setEditing}
        selectedKey={editing && editing !== 'new' ? String(editing.id) : undefined}
      />
      {editing === 'new' && <NewAccountForm onDone={done} onCancel={cancel} />}
      {editing && editing !== 'new' && (
        <EditAccountForm key={editing.id} account={editing} isSelf={editing.id === meId} onDone={done} onCancel={cancel} />
      )}
    </div>
  );
}
