import { useEffect, useId, useState, type CSSProperties, type FormEvent } from 'react';
import { ApiError } from '../api';
import Button from '../ui/Button';
import { limitsApi, type LimitsOut } from './limitsApi';

/** 칸 이름 → 화면 글·단위. 서버가 모르는 칸을 더 주면 이름 그대로 「그 밖」 묶음에 그린다. */
const LABELS: Record<string, [string, string]> = {
  daily_sms_total: ['하루 문자', '건'],
  per_contact_sms_daily: ['한 사람 하루 문자', '건'],
  daily_calls_total: ['하루 전화', '통'],
  per_contact_calls_daily: ['한 사람 하루 전화', '통'],
  max_call_seconds: ['최대 통화 시간', '초'],
  max_call_seconds_unknown: ['모르는 번호 통화 시간', '초'],
  unknown_calls_hourly: ['모르는 번호 전화 한 시간', '통'],
  auto_reply_hourly: ['자동 답 한 시간', '번'],
  auto_reply_daily: ['자동 답 하루', '번'],
  reply_grace_minutes: ['답 유예', '분'],
  unknown_notice_daily: ['모르는 번호 안내 하루', '번'],
  unknown_notice_total_daily: ['모르는 번호 안내 하루 전체', '건'],
  inbound_burst_count: ['잦은 전화 횟수', '번'],
  inbound_burst_minutes: ['잦은 전화 시간 창', '분'],
};

const GROUPS: [string, string[]][] = [
  ['문자', ['daily_sms_total', 'per_contact_sms_daily']],
  ['전화', ['daily_calls_total', 'per_contact_calls_daily', 'max_call_seconds', 'max_call_seconds_unknown', 'unknown_calls_hourly']],
  ['자동 답', ['auto_reply_hourly', 'auto_reply_daily', 'reply_grace_minutes', 'unknown_notice_daily', 'unknown_notice_total_daily']],
  ['들어오는 전화', ['inbound_burst_count', 'inbound_burst_minutes']],
];

// 모양은 공용 부품 클래스(ui-field·ui-btn)와 아래 몇 줄만 — 설정과 개발 콘솔 어디에 놓여도 같게.
const S: Record<string, CSSProperties> = {
  root: { display: 'flex', flexDirection: 'column', gap: 10, minWidth: 0 },
  head: { display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '6px 10px' },
  muted: { margin: 0, fontSize: 'var(--fs-12)', color: 'var(--fg-muted)', flex: '1 1 200px', minWidth: 0 },
  group: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(210px, 1fr))',
    gap: 10,
    margin: 0,
    padding: '8px 10px 10px',
    minWidth: 0,
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius-3)',
  },
  legend: { padding: '0 4px', fontSize: 'var(--fs-12)', fontWeight: 700, color: 'var(--fg)' },
  row: { display: 'flex', gap: 6, alignItems: 'center', minWidth: 0 },
  input: { flex: '1 1 auto', minWidth: 0, width: '100%', boxSizing: 'border-box' },
  save: { flex: 'none', whiteSpace: 'nowrap' },
  changed: { marginLeft: 6, fontSize: 'var(--fs-11)', color: 'var(--tone-info-fg)' },
  ok: { fontSize: 'var(--fs-12)', color: 'var(--success-text)' },
  error: { margin: 0, fontSize: 'var(--fs-12)', color: 'var(--danger-text)', overflowWrap: 'anywhere' },
};

type Problems = Record<string, string>;

/** 서버 오류를 칸마다의 까닭으로. 422 invalid_limits 는 detail {칸: 까닭}, 그 밖에는 고친 칸 아래에 서버 글. */
function problemsOf(e: unknown, key: string): Problems {
  if (!(e instanceof ApiError)) return { [key]: '요청을 처리할 수 없습니다.' };
  const detail = e.detail;
  if (e.code === 'invalid_limits' && detail && typeof detail === 'object') {
    const named = Object.fromEntries(Object.entries(detail as Record<string, unknown>).filter(([, v]) => typeof v === 'string')) as Problems;
    if (Object.keys(named).length > 0) return named;
  }
  return { [key]: e.message };
}

const isCount = (text: string) => /^\d{1,9}$/.test(text.trim());

interface FieldProps {
  name: string;
  data: LimitsOut;
  draft: string | undefined;
  problem: string | undefined;
  saved: boolean;
  busy: boolean;
  onDraft(text: string): void;
  onSave(): void;
}

/** 한 칸: 이름(단위) · 값 · [저장] · 기본값과 받는 범위 · 서버 까닭. */
function LimitField({ name, data, draft, problem, saved, busy, onDraft, onSave }: FieldProps) {
  const id = useId();
  const [label, unit] = LABELS[name] ?? [name, ''];
  const value = data.values[name];
  const text = draft ?? String(value);
  const range = data.ranges[name];
  const fallback = data.defaults[name];
  const hint = [fallback !== undefined && `기본 ${fallback}`, range && `받는 값 ${range[0]}~${range[1]}`].filter(Boolean).join(' · ');
  const canSave = !busy && draft !== undefined && isCount(draft) && Number(draft) !== value;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (canSave) onSave();
  };
  return (
    <form className="ui-field" data-limit={name} noValidate onSubmit={submit} style={{ minWidth: 0 }}>
      <div style={S.row}>
        <label className="ui-field-label" htmlFor={id}>
          {unit ? `${label} (${unit})` : label}
        </label>
        {fallback !== undefined && value !== fallback && <span style={S.changed}>바꿈</span>}
      </div>
      <div style={S.row}>
        <input
          id={id}
          type="number"
          inputMode="numeric"
          min={range?.[0]}
          max={range?.[1]}
          step={1}
          value={text}
          disabled={busy}
          aria-invalid={problem ? true : undefined}
          aria-describedby={`${id}-hint`}
          style={S.input}
          onChange={(e) => onDraft(e.target.value)}
        />
        <Button type="submit" disabled={!canSave} style={S.save}>
          저장
        </Button>
      </div>
      <span className="ui-field-hint" id={`${id}-hint`}>
        {hint}
      </span>
      {saved && <span style={S.ok}>저장했습니다.</span>}
      {problem && (
        <p role="alert" style={S.error}>
          {problem}
        </p>
      )}
    </form>
  );
}

/**
 * 알림 연결의 상한 열두 칸(GET …/limits 가 주는 그대로). 칸마다 따로 저장하고(PUT 은 그 칸만),
 * 서버의 까닭은 그 칸 아래에. [기본값으로] 는 바꾼 칸을 모두 지운다. 부르는 화면의 상태는 받지 않는다.
 */
export default function LimitsForm({ connectionId, disabled = false, onSaved }: {
  connectionId: number;
  /** 부르는 화면이 다른 일을 하는 동안 참(예: 연결 진단 중) — 칸·단추를 모두 잠근다. */
  disabled?: boolean;
  onSaved?(values: Record<string, number>): void;
}) {
  const [data, setData] = useState<LimitsOut | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [problems, setProblems] = useState<Problems>({});
  const [savedKey, setSavedKey] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    limitsApi
      .get(connectionId)
      .then((d) => live && setData(d))
      .catch((e) => live && setLoadError(e instanceof ApiError ? e.message : '요청을 처리할 수 없습니다.'));
    return () => {
      live = false;
    };
  }, [connectionId]);

  async function apply(task: () => Promise<LimitsOut>, key: string | null) {
    setBusy(true);
    setProblems({});
    setSavedKey(null);
    setNote(null);
    try {
      const next = await task();
      setData(next);
      setDrafts((d) => (key === null ? {} : Object.fromEntries(Object.entries(d).filter(([k]) => k !== key))));
      if (key === null) setNote('기본값으로 되돌렸습니다.');
      else setSavedKey(key);
      onSaved?.(next.values);
    } catch (e) {
      setProblems(problemsOf(e, key ?? ''));
    } finally {
      setBusy(false);
    }
  }

  if (loadError) return <p style={S.error}>{loadError}</p>;
  if (!data) return <p style={S.muted}>상한을 읽는 중…</p>;
  const known = new Set(GROUPS.flatMap(([, keys]) => keys));
  const others = Object.keys(data.values).filter((k) => !known.has(k));
  const groups = [...GROUPS, ['그 밖', others] as [string, string[]]]
    .map(([title, keys]) => [title, keys.filter((k) => k in data.values)] as [string, string[]])
    .filter(([, keys]) => keys.length > 0);
  const changedCount = Object.keys(data.values).filter((k) => data.defaults[k] !== undefined && data.values[k] !== data.defaults[k]).length;
  const field = (name: string) => (
    <LimitField
      key={name}
      name={name}
      data={data}
      draft={drafts[name]}
      problem={problems[name]}
      saved={savedKey === name}
      busy={busy || disabled}
      onDraft={(text) => setDrafts((d) => ({ ...d, [name]: text }))}
      onSave={() => apply(() => limitsApi.put(connectionId, { [name]: Number(drafts[name]) }), name)}
    />
  );
  return (
    <div style={S.root}>
      <div style={S.head}>
        <p style={S.muted}>{changedCount === 0 ? '모두 기본값입니다.' : `기본값과 다른 칸 ${changedCount}개`} · 칸마다 따로 저장합니다.</p>
        <Button disabled={busy || disabled || changedCount === 0} onClick={() => apply(() => limitsApi.reset(connectionId), null)}>
          기본값으로
        </Button>
      </div>
      {note && <p style={S.muted}>{note}</p>}
      {problems[''] && (
        <p role="alert" style={S.error}>
          {problems['']}
        </p>
      )}
      {groups.map(([title, keys]) => (
        <fieldset key={title} style={S.group}>
          <legend style={S.legend}>{title}</legend>
          {keys.map(field)}
        </fieldset>
      ))}
    </div>
  );
}
