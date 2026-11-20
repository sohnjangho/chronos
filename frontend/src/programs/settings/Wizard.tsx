import { useState } from 'react';
import Button from '../../shared/ui/Button';
import Field from '../../shared/ui/Field';
import { llmApi } from './llmApi';
import { PROVIDERS, type ConnectionSaved, type LlmError, type Probe, type Provider } from './model';
import { ErrorLine, SecretField, toProblem } from './parts';
import ProbeResult from './ProbeResult';

const STEPS = ['공급자', '주소와 키', '연결 테스트'];
const PROVIDER_HINTS: Record<Provider, string> = {
  liner: '주소가 미리 채워집니다 · 대회 기본',
  openai_compatible: '주소를 직접 넣습니다',
};
const AUTO_NAMES: Record<Provider, string> = { liner: 'Liner', openai_compatible: '' };
const KEY_LABEL = 'API 키 — 저장하면 암호화되고, 화면에는 끝 4자리만 보입니다';

interface Fields {
  name: string;
  baseUrl: string;
  secret: string;
}

/** 시험 결과. 요청이 거절되면(예 쓸 수 없는 키) error 만 있다. */
interface Tested {
  probe?: Probe;
  error?: LlmError;
}

function StepBar({ step }: { step: number }) {
  return (
    <ol className="st-steps" aria-label="단계">
      {STEPS.map((label, i) => {
        const n = i + 1;
        const state = n < step ? ' ok' : n === step ? ' on' : '';
        return (
          <li key={label} className={`st-step${state}`} aria-current={n === step ? 'step' : undefined}>
            <i>{n}</i>
            {label}
          </li>
        );
      })}
    </ol>
  );
}

function ProviderPicker({ value, onPick, disabled }: { value: Provider | null; onPick(p: Provider): void; disabled: boolean }) {
  return (
    <div className="st-providers">
      {PROVIDERS.map((p) => (
        <button
          key={p.value}
          type="button"
          className="st-provider"
          aria-pressed={value === p.value}
          disabled={disabled}
          onClick={() => onPick(p.value)}
        >
          <b>{p.label}</b> <span className="st-muted">{PROVIDER_HINTS[p.value]}</span>
        </button>
      ))}
    </div>
  );
}

/** 공급자를 고르면 주소는 그 공급자의 기본값, 이름은 손대지 않았을 때만 그 공급자 이름. */
function withProvider(f: Fields, p: Provider): Fields {
  const untouchedName = Object.values(AUTO_NAMES).includes(f.name);
  return {
    ...f,
    name: untouchedName ? AUTO_NAMES[p] : f.name,
    baseUrl: PROVIDERS.find((x) => x.value === p)?.defaultBaseUrl ?? '',
  };
}

/** 마법사 상태. 주소·키·공급자를 바꾸면 시험 결과를 지운다(시험한 키로만 저장되게). */
function useWizard(onSaved: (c: ConnectionSaved) => void, onCancel: () => void) {
  const [provider, setProvider] = useState<Provider | null>(null);
  const [fields, setFields] = useState<Fields>({ name: '', baseUrl: '', secret: '' });
  const [tested, setTested] = useState<Tested | null>(null);
  const [saveError, setSaveError] = useState<LlmError | null>(null);
  const [busy, setBusy] = useState(false);

  const choose = (p: Provider) => {
    setProvider(p);
    setFields((f) => withProvider(f, p));
    setTested(null);
  };
  const edit = (key: keyof Fields, value: string) => {
    setFields((f) => ({ ...f, [key]: value }));
    if (key !== 'name') setTested(null);
  };
  const clearSecret = () => setFields((f) => ({ ...f, secret: '' }));
  const target = () => ({ provider: provider as Provider, base_url: fields.baseUrl.trim(), secret: fields.secret });
  async function busyWhile(task: () => Promise<void>, onError: (p: LlmError) => void) {
    setBusy(true);
    setSaveError(null);
    await task().catch((e) => onError(toProblem(e)));
    setBusy(false);
  }
  const runTest = () =>
    busyWhile(async () => setTested({ probe: await llmApi.testNew(target()) }), (error) => setTested({ error }));
  const save = () =>
    busyWhile(async () => {
      const saved = await llmApi.create({ name: fields.name.trim(), ...target() });
      clearSecret();
      onSaved(saved);
    }, setSaveError);
  const cancel = () => {
    clearSecret();
    onCancel();
  };

  const canTest = !busy && fields.baseUrl.trim() !== '' && fields.secret !== '';
  const canSave = !busy && tested?.probe?.ok === true && fields.name.trim() !== '';
  const step = !provider ? 1 : tested ? 3 : 2;
  return { provider, fields, tested, saveError, busy, step, canTest, canSave, choose, edit, runTest, save, cancel, back: () => setTested(null) };
}

/** 연결 추가 3단계: 공급자 → 이름·주소·키 → 연결 테스트(결과와 모델 목록) → 저장. 저장은 시험에 성공해야 켜진다. */
export default function Wizard({ onSaved, onCancel }: { onSaved(c: ConnectionSaved): void; onCancel(): void }) {
  const w = useWizard(onSaved, onCancel);
  return (
    <section className="st-card st-wizard" aria-label="연결 추가">
      <div className="st-wizard-head">
        <b className="st-card-name">연결 추가</b>
        <StepBar step={w.step} />
      </div>
      <ProviderPicker value={w.provider} onPick={w.choose} disabled={w.busy} />
      {w.provider && (
        <>
          <div className="st-grid2">
            <Field label="이름">
              <input value={w.fields.name} disabled={w.busy} onChange={(e) => w.edit('name', e.target.value)} />
            </Field>
            <Field label="URL">
              <input
                value={w.fields.baseUrl}
                spellCheck={false}
                disabled={w.busy}
                onChange={(e) => w.edit('baseUrl', e.target.value)}
              />
            </Field>
          </div>
          <SecretField label={KEY_LABEL} value={w.fields.secret} disabled={w.busy} onChange={(v) => w.edit('secret', v)} />
        </>
      )}
      {w.tested?.probe && <ProbeResult probe={w.tested.probe} />}
      <ErrorLine error={w.tested?.error ?? w.saveError} />
      <div className="st-actions">
        {w.step === 3 && <Button onClick={w.back}>이전</Button>}
        {w.provider && (
          <Button onClick={w.runTest} disabled={!w.canTest}>
            {w.tested ? '다시 테스트' : '연결 테스트'}
          </Button>
        )}
        <span className="st-gap" />
        <Button onClick={w.cancel}>취소</Button>
        {w.provider && (
          <Button variant="primary" onClick={w.save} disabled={!w.canSave}>
            저장
          </Button>
        )}
      </div>
    </section>
  );
}
