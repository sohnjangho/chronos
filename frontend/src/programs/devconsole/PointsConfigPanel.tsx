// 관리 포인트 설정 카드(계획 5 Task 7, 관리자만 — 개발 콘솔 자체가 관리자만): 기준 다섯과 분야별 외부 자료 표.
// 범위는 서버가 준 bounds 로 먼저 막고, 저장할 때 서버가 다시 검사한다(틀리면 422 — 그 글을 그대로 보인다).
// 「관리 포인트」 창의 [설정에서 바꾸기]는 이 카드로 연다(params focus=points).
import { useEffect, useRef, useState } from 'react';
import { ApiError } from '../../shared/api';
import { devApi, type PointSourceKind, type PointsConfig } from './devApi';

type NumKey = 'points_tf_days' | 'points_window_weeks' | 'points_max_new' | 'points_forecast_reuse_hours' | 'accel_warn_ratio';

const FIELDS: { key: NumKey; label: string; unit: string; help: string; step?: number }[] = [
  { key: 'points_tf_days', label: '크리티컬 직전으로 볼 여유', unit: '일', help: '여유가 이 일수 이하인 작업도 관리 포인트로 봅니다. 0이면 크리티컬만.' },
  { key: 'points_window_weeks', label: '앞으로 볼 기간', unit: '주', help: 'Data Date부터 이 주 안에 시작하는 작업만 봅니다.' },
  { key: 'points_max_new', label: '외부 영향을 찾을 새 포인트 수', unit: '곳', help: '한 번 바뀔 때 새로 들어온 포인트 가운데 앞에서 이만큼만 외부 자료를 찾습니다.' },
  { key: 'points_forecast_reuse_hours', label: '찾은 외부 자료를 다시 쓰는 시간', unit: '시간', help: '같은 질문을 이 시간 안에 했으면 다시 부르지 않고 그 값을 씁니다.' },
  { key: 'accel_warn_ratio', label: '당김 효과 경고 비율', unit: '', step: 0.05, help: '당긴 일수 가운데 준공에 반영된 비율이 이보다 낮으면 「당겨도 소용이 적다」고 알립니다.' },
];

const KINDS: { id: PointSourceKind; label: string }[] = [
  { id: 'weather', label: '날씨' },
  { id: 'materials', label: '금속·원자재' },
  { id: 'fx', label: '환율' },
  { id: 'business', label: '업체 소식' },
];

type Draft = Record<NumKey, string> & { points_sources: Record<string, PointSourceKind[]> };

const toDraft = (c: PointsConfig): Draft => ({
  points_tf_days: String(c.points_tf_days),
  points_window_weeks: String(c.points_window_weeks),
  points_max_new: String(c.points_max_new),
  points_forecast_reuse_hours: String(c.points_forecast_reuse_hours),
  accel_warn_ratio: String(c.accel_warn_ratio),
  points_sources: c.points_sources,
});

/** 범위 밖·숫자 아님이면 그 까닭, 맞으면 null. 비율 말고는 정수만. */
function invalid(key: NumKey, text: string, bounds: Record<string, [number, number]>): string | null {
  const [lo, hi] = bounds[key] ?? [-Infinity, Infinity];
  const n = Number(text);
  if (text.trim() === '' || !Number.isFinite(n) || (key !== 'accel_warn_ratio' && !Number.isInteger(n)) || n < lo || n > hi)
    return `${lo}~${hi} 사이${key === 'accel_warn_ratio' ? '' : ' 정수'}로 넣어 주세요.`;
  return null;
}

/** 숫자 칸 하나: 이름(단위) · 칸 · 한 줄 도움말(범위) · 틀렸으면 까닭. */
function NumberField({ f, value, bounds, why, busy, onChange }: {
  f: (typeof FIELDS)[number];
  value: string;
  bounds: [number, number] | undefined;
  why: string | null;
  busy: boolean;
  onChange(v: string): void;
}) {
  const [lo, hi] = bounds ?? [undefined, undefined];
  return (
    <label className="dc-cfg-field">
      <span>{f.unit ? `${f.label} (${f.unit})` : f.label}</span>
      <input type="number" aria-label={f.label} aria-invalid={why ? true : undefined} min={lo} max={hi} step={f.step ?? 1} value={value}
        disabled={busy} onChange={(e) => onChange(e.target.value)} />
      <span className="dc-pt-help">{f.help}{lo !== undefined ? ` (${lo}~${hi})` : ''}</span>
      {why && <span className="dc-error" role="alert">{why}</span>}
    </label>
  );
}

/** 분야(줄) × 외부 자료 갈래(칸) 켜고 끄기. */
function SourcesTable({ domains, sources, busy, onToggle }: {
  domains: PointsConfig['domains'];
  sources: Draft['points_sources'];
  busy: boolean;
  onToggle(domain: string, kind: PointSourceKind, on: boolean): void;
}) {
  return (
    <div className="dc-pt-src">
      <p className="dc-muted">분야마다 관리 포인트에 쓸 외부 자료를 고릅니다. 표에 없는 분야는 「그 밖의 분야」를 따릅니다. 날씨는 기상청, 나머지는 Liner(비용 있음)입니다.</p>
      <div className="dc-u-wrap">
        <table className="dc-u dc-pt-table" aria-label="분야별 외부 자료">
          <thead>
            <tr>
              <th scope="col">분야</th>
              {KINDS.map((k) => (
                <th key={k.id} scope="col">{k.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {domains.map((d) => (
              <tr key={d.id}>
                <th scope="row">{d.label}</th>
                {KINDS.map((k) => (
                  <td key={k.id}>
                    <input
                      type="checkbox"
                      aria-label={`${d.label} ${k.label}`}
                      checked={(sources[d.id] ?? []).includes(k.id)}
                      disabled={busy}
                      onChange={(e) => onToggle(d.id, k.id, e.target.checked)}
                    />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function PointsConfigPanel({ focus = false }: { focus?: boolean }) {
  const [saved, setSaved] = useState<PointsConfig | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const ref = useRef<HTMLElement | null>(null);

  useEffect(() => {
    let live = true;
    devApi.getPointsConfig().then(
      (c) => {
        if (!live) return;
        setSaved(c);
        setDraft(toDraft(c));
      },
      () => live && setError('관리 포인트 설정을 읽지 못했습니다.'),
    );
    return () => {
      live = false;
    };
  }, []);
  useEffect(() => {
    if (focus && saved) ref.current?.scrollIntoView?.({ block: 'start' });
  }, [focus, saved]);

  const bounds = saved?.bounds ?? {};
  const wrong = draft ? FIELDS.map((f) => [f.key, invalid(f.key, draft[f.key], bounds)] as const).filter(([, w]) => w) : [];
  const dirty = saved !== null && draft !== null && JSON.stringify(draft) !== JSON.stringify(toDraft(saved));

  const edit = (patch: Partial<Draft>) => {
    setDraft((d) => (d ? { ...d, ...patch } : d));
    setNotice(null);
    setError(null);
  };
  const toggle = (domain: string, kind: PointSourceKind, on: boolean) => {
    if (!draft) return;
    const now = draft.points_sources[domain] ?? [];
    const next = on ? KINDS.map((k) => k.id).filter((k) => k === kind || now.includes(k)) : now.filter((k) => k !== kind);
    edit({ points_sources: { ...draft.points_sources, [domain]: next } });
  };

  async function save() {
    if (!draft) return;
    setBusy(true);
    setNotice(null);
    setError(null);
    try {
      const next = await devApi.savePointsConfig({
        points_tf_days: Number(draft.points_tf_days),
        points_window_weeks: Number(draft.points_window_weeks),
        points_max_new: Number(draft.points_max_new),
        points_forecast_reuse_hours: Number(draft.points_forecast_reuse_hours),
        accel_warn_ratio: Number(draft.accel_warn_ratio),
        points_sources: draft.points_sources,
      });
      setSaved(next);
      setDraft(toDraft(next));
      setNotice('관리 포인트 설정을 저장했습니다. 다음 버전 계산부터 씁니다.');
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '설정을 저장하지 못했습니다.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <section ref={ref} id="dc-points-config" className="dc-cfg-card" aria-label="관리 포인트 설정">
      <div className="dc-cfg-head">
        <div>
          <h3>관리 포인트 설정</h3>
          <p className="dc-muted">관리 포인트 = 크리티컬 + 여유가 적은 작업 가운데 가까운 몇 주 안에 시작하는 것. 버전이 바뀔 때 이 기준으로 다시 셉니다.</p>
        </div>
        <div className="dc-cfg-actions">
          <button type="button" className="dc-btn dc-btn-primary" disabled={busy || !dirty || wrong.length > 0} onClick={() => void save()}>
            {busy ? '저장 중…' : '관리 포인트 설정 저장'}
          </button>
        </div>
      </div>
      {!draft && !error && <p className="dc-muted">불러오는 중…</p>}
      {draft && (
        <>
          <div className="dc-cfg-grid">
            {FIELDS.map((f) => (
              <NumberField key={f.key} f={f} value={draft[f.key]} bounds={bounds[f.key]} why={wrong.find(([k]) => k === f.key)?.[1] ?? null}
                busy={busy} onChange={(v) => edit({ [f.key]: v } as Partial<Draft>)} />
            ))}
          </div>
          <SourcesTable domains={saved?.domains ?? []} sources={draft.points_sources} busy={busy} onToggle={toggle} />
        </>
      )}
      {(notice || error) && (
        <div className="dc-cfg-toggles">
          {notice && <span className="dc-ok" role="status">{notice}</span>}
          {error && <span className="dc-error" role="alert">{error}</span>}
        </div>
      )}
    </section>
  );
}
