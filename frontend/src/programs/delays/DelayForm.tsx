// 지연 사건 등록·고치기 양식(오른쪽 칸). 반영된 사건은 대상·시작일·일수를 고칠 수 없다(원인·책임·하루 금액·근거만).
// 보내기 전에 검사하고, 서버가 거절하면 그 글을 그대로 보인다. 날짜는 계산하지 않는다(시작일 기본값은 일정의 Data Date).
import { useEffect, useState, type FormEvent } from 'react';
import type { ScheduleView } from '../../shared/schedule/scheduleApi';
import Button from '../../shared/ui/Button';
import Field from '../../shared/ui/Field';
import ActivityPicker from './ActivityPicker';
import type { DelayEvent, Responsibility } from './delaysApi';
import { validate, type FormErrors, type FormValues } from './form';
import { RESPONSIBILITIES } from './format';

interface Props {
  /** 고칠 사건(없으면 새 사건). */
  event: DelayEvent | null;
  initial: FormValues;
  /** 실적 입력 전 버전(실적 입력의 지연 알림이 연 양식). */
  before: number | null;
  view: ScheduleView | null;
  viewError: string | null;
  /** 보낸다. 실패하면 보일 글, 성공(또는 보낼 것 없음)이면 null. */
  onSubmit: (values: FormValues) => Promise<string | null>;
  onCancel: () => void;
}

type Setter = <K extends keyof FormValues>(key: K, value: FormValues[K]) => void;

interface FieldsProps {
  values: FormValues;
  set: Setter;
  errors: FormErrors;
  locked: boolean;
  view: ScheduleView | null;
  viewError: string | null;
}

/** 칸들: 대상 · 시작일·일수 · 원인 · 책임·하루 금액 · 근거 문서. locked(반영된 사건)면 대상·시작일·일수를 끈다. */
function Fields({ values, set, errors, locked, view, viewError }: FieldsProps) {
  return (
    <>
      <ActivityPicker
        view={view}
        viewError={viewError}
        value={values.activity_id}
        onChange={(aid) => set('activity_id', aid)}
        disabled={locked}
        error={errors.activity_id}
      />
      <div className="dl-form-row">
        <Field label="시작일" error={errors.start_date}>
          <input className="dl-input" value={values.start_date} placeholder="2027-06-01" disabled={locked} onChange={(e) => set('start_date', e.target.value)} />
        </Field>
        <Field label="일수" hint="근무일" error={errors.days}>
          <input className="dl-input" inputMode="numeric" value={values.days} disabled={locked} onChange={(e) => set('days', e.target.value)} />
        </Field>
      </div>
      <Field label="원인" error={errors.cause}>
        <input className="dl-input" value={values.cause} maxLength={200} onChange={(e) => set('cause', e.target.value)} />
      </Field>
      <div className="dl-form-row">
        <Field label="책임">
          <select className="dl-input" value={values.responsibility} onChange={(e) => set('responsibility', e.target.value as Responsibility)}>
            {RESPONSIBILITIES.map((r) => (
              <option key={r.key} value={r.key}>
                {r.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="하루 금액(원)" hint="비워도 됩니다" error={errors.daily_cost}>
          <input className="dl-input" inputMode="numeric" value={values.daily_cost} onChange={(e) => set('daily_cost', e.target.value)} />
        </Field>
      </div>
      <Field label="근거 문서">
        <input className="dl-input" value={values.evidence} maxLength={200} placeholder="회의록·공문 이름" onChange={(e) => set('evidence', e.target.value)} />
      </Field>
    </>
  );
}

function Notes({ before, locked }: { before: number | null; locked: boolean }) {
  return (
    <>
      {before !== null && (
        <p className="dl-note" role="note">
          실적 입력에서 감지한 지연입니다. 이미 일정에 들어 있어 반영된 사건으로 기록합니다(두 번 세지 않습니다).
        </p>
      )}
      {locked && (
        <p className="dl-note" role="note">
          반영된 사건은 원인·책임·하루 금액·근거만 고칠 수 있습니다.
        </p>
      )}
    </>
  );
}

export default function DelayForm({ event, initial, before, view, viewError, onSubmit, onCancel }: Props) {
  const [values, setValues] = useState(initial);
  const [errors, setErrors] = useState<FormErrors>({});
  const [failure, setFailure] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const locked = event?.status === 'reflected';
  const set: Setter = (key, value) => setValues((v) => ({ ...v, [key]: value }));

  const dataDate = view?.data_date ?? null;
  useEffect(() => {
    if (dataDate) setValues((v) => (v.start_date ? v : { ...v, start_date: dataDate })); // 일정을 늦게 읽었을 때
  }, [dataDate]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const found = validate(values);
    setErrors(found);
    setFailure(null);
    if (Object.keys(found).length > 0) return;
    setBusy(true);
    const message = await onSubmit(values);
    setBusy(false);
    setFailure(message);
  };

  return (
    <form className="dl-form" aria-label={event ? '지연 사건 고치기' : '새 지연 사건'} onSubmit={submit} noValidate>
      <h3 className="dl-title">{event ? '지연 사건 고치기' : '새 지연 사건'}</h3>
      <Notes before={before} locked={locked} />
      <Fields values={values} set={set} errors={errors} locked={locked} view={view} viewError={viewError} />
      {failure && (
        <p className="dl-error" role="alert">
          {failure}
        </p>
      )}
      <div className="dl-actions">
        <Button variant="primary" type="submit" disabled={busy}>
          {event ? '저장' : '등록'}
        </Button>
        <Button onClick={onCancel} disabled={busy}>
          취소
        </Button>
      </div>
    </form>
  );
}
