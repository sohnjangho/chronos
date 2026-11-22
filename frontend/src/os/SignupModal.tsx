import { useEffect, useRef, useState, type FormEvent } from 'react';
import { ApiError } from '../shared/api';
import Button from '../shared/ui/Button';
import Field from '../shared/ui/Field';
import { signUp, type SignupResponse, type SignupRole } from './auth';
import { useModalFocus } from './modalFocus';

interface Props {
  open: boolean;
  onClose(): void;
}

const ROLE_OPTIONS: { value: SignupRole; title: string; desc: string }[] = [
  { value: 'user', title: '사용자 (공정 · 일정 담당자)', desc: 'PC · 태블릿에서 일정 수립, 간트 차트, 에이전트 대화를 사용합니다.' },
  { value: 'field', title: '현장 관리자', desc: '스마트폰 · 태블릿 전용 화면에서 일일 점검과 사진 AI 보고를 수행합니다.' },
];

export default function SignupModal({ open, onClose }: Props) {
  const [loginId, setLoginId] = useState('');
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [organization, setOrganization] = useState('');
  const [department, setDepartment] = useState('');
  const [role, setRole] = useState<SignupRole>('user');
  const [password, setPassword] = useState('');
  const [passwordConfirm, setPasswordConfirm] = useState('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState<SignupResponse | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const trap = useModalFocus(dialogRef);

  useEffect(() => {
    if (!open) return;
    setError('');
    setBusy(false);
    setDone(null);
  }, [open]);

  if (!open) return null;

  function resetAndClose() {
    setLoginId('');
    setName('');
    setEmail('');
    setPhone('');
    setOrganization('');
    setDepartment('');
    setRole('user');
    setPassword('');
    setPasswordConfirm('');
    setNote('');
    setError('');
    setDone(null);
    onClose();
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const idTrim = loginId.trim();
    const nameTrim = name.trim();
    const emailTrim = email.trim();
    if (!idTrim || !nameTrim || !emailTrim || !password) {
      setError('아이디, 이름, 이메일, 비밀번호는 필수 항목입니다.');
      return;
    }
    if (password.length < 4) {
      setError('비밀번호는 4자 이상 입력해 주세요.');
      return;
    }
    if (password !== passwordConfirm) {
      setError('비밀번호와 비밀번호 확인이 일치하지 않습니다.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const res = await signUp({
        login_id: idTrim,
        password,
        name: nameTrim,
        role,
        email: emailTrim,
        ...(phone.trim() ? { phone: phone.trim() } : {}),
        ...(organization.trim() ? { organization: organization.trim() } : {}),
        ...(department.trim() ? { department: department.trim() } : {}),
        ...(note.trim() ? { note: note.trim() } : {}),
      });
      setDone(res);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '회원가입 신청을 처리하지 못했습니다.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="os-signup-backdrop"
      role="presentation"
      onClick={(e) => {
        if (e.target === e.currentTarget && !busy) resetAndClose();
      }}
      onKeyDown={(e) => {
        if (e.key === 'Escape' && !busy) resetAndClose();
      }}
    >
      <div
        ref={dialogRef}
        className="os-signup-modal"
        role="dialog"
        aria-modal="true"
        aria-label="회원가입"
        tabIndex={-1}
        onKeyDown={trap}
      >
        <div className="os-signup-head">
          <div>
            <h2>회원가입 신청</h2>
            <p className="os-signup-desc">가입 신청 후 관리자가 승인하면 로그인하여 사용할 수 있습니다.</p>
          </div>
          <button type="button" className="os-signup-close" aria-label="회원가입 닫기" disabled={busy} onClick={resetAndClose}>
            ×
          </button>
        </div>

        {done ? (
          <div className="os-signup-done" role="status">
            <p className="os-signup-done-title">{done.message}</p>
            <dl className="os-signup-summary">
              <dt>아이디</dt>
              <dd>{done.login_id}</dd>
              <dt>이름</dt>
              <dd>{done.name}</dd>
              <dt>신청 등급</dt>
              <dd>{done.role === 'field' ? '현장 관리자' : '사용자 (공정 · 일정 담당자)'}</dd>
              <dt>상태</dt>
              <dd>관리자 승인 대기</dd>
            </dl>
            <div className="os-card-actions">
              <Button type="button" variant="primary" className="os-card-submit" onClick={resetAndClose}>
                로그인 화면으로 돌아가기
              </Button>
            </div>
          </div>
        ) : (
          <form className="os-signup-form" onSubmit={onSubmit}>
            <div className="os-signup-grid">
              <Field label="아이디 *" hint="영문·숫자·._- (3~50자)">
                <input
                  value={loginId}
                  onChange={(e) => setLoginId(e.target.value)}
                  placeholder="예: hong.gildong"
                  autoComplete="username"
                  required
                  autoFocus
                />
              </Field>
              <Field label="이름 *">
                <input value={name} onChange={(e) => setName(e.target.value)} placeholder="예: 홍길동" required />
              </Field>
              <Field label="이메일 *">
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="name@company.com"
                  autoComplete="email"
                  required
                />
              </Field>
              <Field label="연락처 (선택)">
                <input
                  type="tel"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  placeholder="010-1234-5678"
                  autoComplete="tel"
                />
              </Field>
              <Field label="소속 회사 · 현장 (선택)">
                <input value={organization} onChange={(e) => setOrganization(e.target.value)} placeholder="예: OO건설 / 판교 R&D 센터" />
              </Field>
              <Field label="부서 · 직책 (선택)">
                <input value={department} onChange={(e) => setDepartment(e.target.value)} placeholder="예: 공정관리팀 · 과장" />
              </Field>
              <Field label="비밀번호 *" hint="4자 이상">
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="new-password"
                  required
                />
              </Field>
              <Field label="비밀번호 확인 *">
                <input
                  type="password"
                  value={passwordConfirm}
                  onChange={(e) => setPasswordConfirm(e.target.value)}
                  autoComplete="new-password"
                  required
                />
              </Field>
            </div>

            <div className="os-signup-roles" role="group" aria-label="신청 등급 선택">
              <span className="os-signup-role-label">신청 등급</span>
              <div className="os-signup-role-grid">
                {ROLE_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    className="os-signup-role-btn"
                    aria-pressed={role === opt.value}
                    onClick={() => setRole(opt.value)}
                  >
                    <b>{opt.title}</b>
                    <span>{opt.desc}</span>
                  </button>
                ))}
              </div>
            </div>

            <Field label="가입 사유 · 담당 업무 메모 (선택)">
              <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="예: OO 프로젝트 공정 관리 담당자입니다." />
            </Field>

            {error && (
              <p className="os-card-error" role="alert">
                {error}
              </p>
            )}

            <div className="os-card-actions">
              <Button type="button" disabled={busy} onClick={resetAndClose}>
                취소
              </Button>
              <Button type="submit" variant="primary" className="os-card-submit" disabled={busy}>
                {busy ? '신청 중…' : '가입 신청하기'}
              </Button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
