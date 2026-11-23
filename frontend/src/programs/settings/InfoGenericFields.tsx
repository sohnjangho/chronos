import Field from '../../shared/ui/Field';
import type { GenericFields, KeyIn } from './infoApi';

/** 범용 연결 칸 전부(추가·고치기 공통). 키는 화면 상태에만 있고 저장·취소 때 비운다. */
export type GenericDraft = GenericFields & { name: string; secret: string };

export type DraftErrors = Partial<Record<keyof GenericDraft, string>>;

export const EMPTY_DRAFT: GenericDraft = {
  name: '',
  base_url: '',
  secret: '',
  description: '',
  usage: '',
  key_in: 'query',
  key_name: 'serviceKey',
  test_path: '',
};

const REQUIRED: [keyof GenericDraft, string][] = [
  ['name', '이름을 넣어 주세요.'],
  ['base_url', '주소를 넣어 주세요.'],
  ['secret', '키를 넣어 주세요.'],
  ['description', '설명을 넣어 주세요.'],
];

/** 비어 있는 필수 칸마다 한국어 글. 고치기는 키를 비워 둬도 된다(needKey=false). */
export function missing(d: GenericDraft, needKey: boolean): DraftErrors {
  const out: DraftErrors = {};
  for (const [k, msg] of REQUIRED) {
    if (k === 'secret' && !needKey) continue;
    if (d[k].trim() === '') out[k] = msg;
  }
  return out;
}

interface Props {
  draft: GenericDraft;
  set(patch: Partial<GenericDraft>): void;
  errors: DraftErrors;
  busy: boolean;
  keyLabel: string;
  keyHint?: string;
}

/** 이름·주소 / 키 / 키 넣는 곳·키 이름 / 설명 / 쓰는 법 / 시험 경로. */
export default function GenericFieldset({ draft, set, errors, busy, keyLabel, keyHint }: Props) {
  return (
    <>
      <div className="st-grid2">
        <Field label="이름" error={errors.name}>
          <input value={draft.name} maxLength={80} disabled={busy} onChange={(e) => set({ name: e.target.value })} />
        </Field>
        <Field label="주소" error={errors.base_url}>
          <input value={draft.base_url} spellCheck={false} disabled={busy} placeholder="https://apis.data.go.kr/…" onChange={(e) => set({ base_url: e.target.value })} />
        </Field>
      </div>
      <Field label={keyLabel} hint={keyHint} error={errors.secret}>
        <input type="password" autoComplete="new-password" spellCheck={false} value={draft.secret} disabled={busy} onChange={(e) => set({ secret: e.target.value })} />
      </Field>
      <div className="st-grid2">
        <Field label="키 넣는 곳">
          <select value={draft.key_in} disabled={busy} onChange={(e) => set({ key_in: e.target.value as KeyIn })}>
            <option value="query">질의</option>
            <option value="header">헤더</option>
          </select>
        </Field>
        <Field label="키 이름" error={errors.key_name}>
          <input value={draft.key_name} maxLength={60} spellCheck={false} disabled={busy} onChange={(e) => set({ key_name: e.target.value })} />
        </Field>
      </div>
      <Field label="설명" hint="이 API 가 무엇을 주는지 — 에이전트가 읽고 고릅니다" error={errors.description}>
        <textarea rows={2} maxLength={500} value={draft.description} disabled={busy} onChange={(e) => set({ description: e.target.value })} />
      </Field>
      <Field label="쓰는 법" hint="경로·필수 파라미터·예시 — 에이전트가 읽고 호출을 짭니다">
        <textarea rows={4} maxLength={3000} value={draft.usage} disabled={busy} onChange={(e) => set({ usage: e.target.value })} />
      </Field>
      <Field label="시험 경로" hint="연결 테스트에 쓸 경로+질의, 예: /getRestDeInfo?solYear=2026&solMonth=12" error={errors.test_path}>
        <input value={draft.test_path} maxLength={500} spellCheck={false} disabled={busy} onChange={(e) => set({ test_path: e.target.value })} />
      </Field>
    </>
  );
}
