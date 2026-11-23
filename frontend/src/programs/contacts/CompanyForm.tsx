// 협력사 추가·고치기(시안 ⑤): 이름 · 공종 · 메모. 고칠 때는 [숨기기]/[다시 보이기]. 서버 글은 칸 아래에.
import { useState, type FormEvent } from 'react';
import { ApiError } from '../../shared/api';
import Button from '../../shared/ui/Button';
import { patchCompany, postCompany, type Company, type CompanyBody } from './contactsApi';

interface Props {
  scheduleId: number;
  /** 고칠 협력사(없으면 새 협력사). */
  company: Company | null;
  onSaved: (c: Company) => void;
  onCancel: () => void;
}

export default function CompanyForm({ scheduleId, company, onSaved, onCancel }: Props) {
  const [name, setName] = useState(company?.name ?? '');
  const [trade, setTrade] = useState(company?.trade ?? '');
  const [note, setNote] = useState(company?.note ?? '');
  const [errors, setErrors] = useState<{ name?: string; trade?: string; note?: string; form?: string }>({});
  const [busy, setBusy] = useState(false);

  const save = async (body: CompanyBody) => {
    setErrors({});
    setBusy(true);
    try {
      const saved = company ? await patchCompany(scheduleId, company.id, body) : await postCompany(scheduleId, body);
      setBusy(false);
      onSaved(saved);
    } catch (e) {
      setBusy(false);
      if (!(e instanceof ApiError)) return setErrors({ form: '저장할 수 없습니다.' });
      const f = (e.detail as { field?: string } | null)?.field;
      setErrors(e.code === 'invalid_text' && (f === 'name' || f === 'trade' || f === 'note') ? { [f]: e.message } : { form: e.message });
    }
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return setErrors({ name: '협력사 이름을 넣어 주세요.' });
    const body: CompanyBody = { name: name.trim(), trade: trade.trim(), note };
    if (company) for (const k of ['name', 'trade', 'note'] as const) if (body[k] === company[k]) delete body[k];
    if (company && Object.keys(body).length === 0) return onCancel();
    void save(body);
  };

  const err = (m?: string) =>
    m && (
      <p className="ct-error" role="alert">
        {m}
      </p>
    );
  const title = company ? '협력사 고치기' : '협력사 추가';
  return (
    <form className="ct-form" aria-label={title} onSubmit={submit} noValidate>
      <div className="ct-form-head">
        <h3 className="ct-title">{title}</h3>
      </div>
      <div className="ct-grid">
        <div className="ct-field">
          <label className="ct-fld-label">
            <span className="ct-label">협력사 이름</span>
            <input className="ct-input" value={name} maxLength={100} onChange={(e) => setName(e.target.value)} />
          </label>
          {err(errors.name)}
        </div>
        <div className="ct-field">
          <label className="ct-fld-label">
            <span className="ct-label">공종</span>
            <input className="ct-input" value={trade} maxLength={100} placeholder="예: 전기" onChange={(e) => setTrade(e.target.value)} />
          </label>
          {err(errors.trade)}
        </div>
        <div className="ct-field is-wide">
          <label className="ct-fld-label">
            <span className="ct-label">메모</span>
            <textarea className="ct-input ct-textarea" value={note} maxLength={2000} rows={3} onChange={(e) => setNote(e.target.value)} />
          </label>
          {err(errors.note)}
        </div>
      </div>
      <p className="ct-hint">이 프로젝트의 주소록에만 저장됩니다. 다른 프로젝트의 같은 협력사는 따로 고칩니다.</p>
      {err(errors.form)}
      <div className="ct-actions">
        {company && (
          <Button onClick={() => void save({ hidden: !company.hidden })} disabled={busy}>
            {company.hidden ? '다시 보이기' : '숨기기'}
          </Button>
        )}
        <span className="ct-gap" />
        <Button onClick={onCancel} disabled={busy}>
          취소
        </Button>
        <Button variant="primary" type="submit" disabled={busy}>
          저장
        </Button>
      </div>
    </form>
  );
}
