import { useEffect, useState } from 'react';
import Button from '../../shared/ui/Button';
import Field from '../../shared/ui/Field';
import GenericFieldset, { EMPTY_DRAFT, missing, type DraftErrors, type GenericDraft } from './InfoGenericFields';
import { infoApi, type InfoTemplate } from './infoApi';
import type { LlmError } from './model';
import { ErrorLine, toProblem } from './parts';

/** 빠른 채움 목록. 못 읽었거나 비었으면 'none'(폼은 그대로 쓴다). */
function useTemplates() {
  const [templates, setTemplates] = useState<InfoTemplate[] | 'none' | null>(null);
  useEffect(() => {
    let live = true;
    infoApi
      .templates()
      .then((list) => live && setTemplates(list.length > 0 ? list : 'none'))
      .catch(() => live && setTemplates('none'));
    return () => {
      live = false;
    };
  }, []);
  return templates;
}

/** 빠른 채움 고르기 + 고른 것의 공식 문서 링크. 목록이 없으면 흐린 한 줄. */
function QuickFill({ templates, picked, busy, onPick }: { templates: InfoTemplate[] | 'none' | null; picked: string; busy: boolean; onPick(t: InfoTemplate): void }) {
  if (templates === null) return null;
  if (templates === 'none') return <p className="st-muted">빠른 채움 목록을 불러오지 못했습니다</p>;
  const chosen = templates.find((t) => t.id === picked);
  return (
    <div className="st-info-quick">
      <Field label="빠른 채움" hint="주소·키 이름·설명·쓰는 법·시험 경로를 채웁니다(키는 직접 넣습니다)">
        <select
          value={picked}
          disabled={busy}
          onChange={(e) => {
            const t = templates.find((x) => x.id === e.target.value);
            if (t) onPick(t);
          }}
        >
          <option value="">고르지 않음</option>
          {templates.map((t) => (
            <option key={t.id} value={t.id}>
              {t.label}
            </option>
          ))}
        </select>
      </Field>
      {chosen?.docs_url && (
        <a className="st-info-docs" href={chosen.docs_url} target="_blank" rel="noopener noreferrer">
          공식 문서
        </a>
      )}
    </div>
  );
}

/** 범용 연결 추가. 필수: 이름·주소·키·설명. 저장·취소 때 키 칸을 비운다. */
export default function GenericAddForm({ onSaved, onCancel }: { onSaved(): void; onCancel(): void }) {
  const templates = useTemplates();
  const [picked, setPicked] = useState('');
  const [draft, setDraft] = useState<GenericDraft>(EMPTY_DRAFT);
  const [errors, setErrors] = useState<DraftErrors>({});
  const [error, setError] = useState<LlmError | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (patch: Partial<GenericDraft>) => setDraft((d) => ({ ...d, ...patch }));
  const pick = ({ id, label, base_url, key_in, key_name, description, usage, test_path }: InfoTemplate) => {
    setPicked(id);
    setDraft((d) => ({ ...d, base_url, key_in, key_name, description, usage, test_path, name: d.name.trim() === '' ? label : d.name }));
  };
  const save = async () => {
    const missed = missing(draft, true);
    setErrors(missed);
    if (Object.keys(missed).length > 0) return;
    setBusy(true);
    setError(null);
    try {
      const { name, secret, ...rest } = draft;
      const trimmed = { ...rest, base_url: rest.base_url.trim(), description: rest.description.trim(), key_name: rest.key_name.trim(), test_path: rest.test_path.trim() };
      await infoApi.create({ name: name.trim(), preset: 'generic', secret, ...trimmed });
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
    <>
      <QuickFill templates={templates} picked={picked} busy={busy} onPick={pick} />
      <GenericFieldset draft={draft} set={set} errors={errors} busy={busy} keyLabel="키 — 저장하면 암호화되고, 화면에는 끝 4자리만 보입니다" />
      <ErrorLine error={error} />
      <div className="st-actions">
        <span className="st-gap" />
        <Button onClick={cancel}>취소</Button>
        <Button variant="primary" onClick={save} disabled={busy}>
          저장
        </Button>
      </div>
    </>
  );
}
