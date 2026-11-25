import { useCallback, useEffect, useId, useState } from 'react';
import Badge from '../../shared/ui/Badge';
import Button from '../../shared/ui/Button';
import Field from '../../shared/ui/Field';
import InfoCard, { KEY_HINT } from './InfoCard';
import GenericAddForm from './InfoGenericAdd';
import InfoGenericCard from './InfoGenericCard';
import { infoApi, type InfoConnection, type InfoPreset } from './infoApi';
import type { LlmError } from './model';
import { ErrorLine, SecretField, toProblem } from './parts';
import './info.css';

/** 연결 목록. reload 를 부르면 다시 읽는다. 읽기 전에는 null. */
function useInfoConnections() {
  const [connections, setConnections] = useState<InfoConnection[] | null>(null);
  const [error, setError] = useState<LlmError | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let live = true;
    infoApi
      .list()
      .then((list) => {
        if (!live) return;
        setConnections(list);
        setError(null);
      })
      .catch((e) => live && setError(toProblem(e)));
    return () => {
      live = false;
    };
  }, [tick]);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { connections, error, reload };
}

/** 기상청 연결 추가: 이름 · 서비스 키. 주소는 서버가 기본 주소로 채운다. 저장·취소 때 키 칸을 비운다. */
function KmaAddForm({ onSaved, onCancel }: { onSaved(): void; onCancel(): void }) {
  const [name, setName] = useState('기상청 날씨');
  const [secret, setSecret] = useState('');
  const [error, setError] = useState<LlmError | null>(null);
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await infoApi.create({ name: name.trim(), preset: 'kma', secret });
      setSecret('');
      onSaved();
    } catch (e) {
      setError(toProblem(e));
    } finally {
      setBusy(false);
    }
  };
  const cancel = () => {
    setSecret('');
    onCancel();
  };
  return (
    <>
      <div className="st-grid2">
        <Field label="이름">
          <input value={name} disabled={busy} onChange={(e) => setName(e.target.value)} />
        </Field>
      </div>
      <SecretField
        label="서비스 키 — 저장하면 암호화되고, 화면에는 끝 4자리만 보입니다"
        value={secret}
        disabled={busy}
        onChange={setSecret}
        hint={KEY_HINT}
      />
      <ErrorLine error={error} />
      <div className="st-actions">
        <span className="st-gap" />
        <Button onClick={cancel}>취소</Button>
        <Button variant="primary" onClick={save} disabled={busy || name.trim() === '' || secret === ''}>
          저장
        </Button>
      </div>
    </>
  );
}

const KINDS: { value: InfoPreset; label: string }[] = [
  { value: 'kma', label: '기상청(전용)' },
  { value: 'generic', label: '범용' },
];

/** 연결 추가: 종류(기상청(전용) | 범용)를 고르면 그 종류의 칸들. */
function AddForm({ onSaved, onCancel }: { onSaved(): void; onCancel(): void }) {
  const [kind, setKind] = useState<InfoPreset>('kma');
  const labelId = useId();
  return (
    <section className="st-card" role="group" aria-label="정보 API 연결 추가">
      <b className="st-card-name">연결 추가</b>
      <div className="st-info-kindrow">
        <span id={labelId} className="ui-field-label">
          종류
        </span>
        <div className="st-info-kinds" role="radiogroup" aria-labelledby={labelId}>
          {KINDS.map((k) => (
            <label key={k.value} className="st-info-kind">
              <input type="radio" name={`${labelId}-kind`} value={k.value} checked={kind === k.value} onChange={() => setKind(k.value)} />
              {k.label}
            </label>
          ))}
        </div>
      </div>
      {kind === 'kma' ? <KmaAddForm onSaved={onSaved} onCancel={onCancel} /> : <GenericAddForm onSaved={onSaved} onCancel={onCancel} />}
    </section>
  );
}

/** 이름·설명에 찾는 말이 들어간 연결만. */
const matches = (c: InfoConnection, q: string) => `${c.name}\n${c.description ?? ''}`.toLowerCase().includes(q.trim().toLowerCase());

/** 연결 카드 목록. 6개를 넘으면 찾기 칸(이름·설명)을 위에 둔다. */
function ConnectionList({ connections, onChanged }: { connections: InfoConnection[]; onChanged(): void }) {
  const [query, setQuery] = useState('');
  const filterable = connections.length > 6;
  const shown = filterable && query.trim() !== '' ? connections.filter((c) => matches(c, query)) : connections;
  return (
    <>
      {filterable && (
        <div className="st-filter-row">
          <input type="search" className="st-search st-info-filter" aria-label="이름·설명 찾기" placeholder="이름·설명 찾기" value={query} onChange={(e) => setQuery(e.target.value)} />
          <span className="st-muted">{`${shown.length} / ${connections.length}개`}</span>
        </div>
      )}
      {filterable && shown.length === 0 && <p className="st-muted">찾는 연결이 없습니다.</p>}
      {shown.map((c) =>
        c.preset === 'generic' ? <InfoGenericCard key={c.id} conn={c} onChanged={onChanged} /> : <InfoCard key={c.id} conn={c} onChanged={onChanged} />,
      )}
    </>
  );
}

/** 「정보 API 연결」(관리자): 에이전트 도구가 쓰는 외부 정보. 지원 프리셋 카드와 연결 카드 목록. */
export default function InfoSection() {
  const { connections, error, reload } = useInfoConnections();
  const [adding, setAdding] = useState(false);
  const saved = () => {
    setAdding(false);
    reload();
  };
  const kmaConnected = connections?.some((c) => c.preset === 'kma') ?? false;
  return (
    <div className="st-pane">
      <div className="st-head">
        <div>
          <h2>정보 API 연결</h2>
          <p className="st-muted">에이전트 도구가 쓰는 외부 정보 · 키는 암호화하고 끝 4자리만 보입니다.</p>
        </div>
        <Button variant="primary" disabled={adding} onClick={() => setAdding(true)}>
          + 연결 추가
        </Button>
      </div>
      <ErrorLine error={error} />
      <section className="st-card st-card-subtle" aria-label="지원 정보 API 프리셋">
        <div className="st-card-head">
          <b className="st-card-name">지원 정보 API: 기상청 (공공데이터포털 · info.weather)</b>
          <span className="st-gap" />
          <Badge tone={kmaConnected ? 'success' : 'neutral'}>{kmaConnected ? '등록됨' : '미등록'}</Badge>
        </div>
        <p className="st-muted">
          쓰는 도구 info.weather — 지난 해들 그 달 통계(코드가 계산) · 3일 예보. 숫자는 근거로만 붙이고 날짜 계산에는 넣지 않습니다.
        </p>
      </section>
      {connections?.length === 0 && !adding && (
        <p className="st-muted">아직 연결이 없습니다. 「+ 연결 추가」로 기상청 서비스 키를 넣어 주세요.</p>
      )}
      {connections && <ConnectionList connections={connections} onChanged={reload} />}
      {adding && <AddForm onSaved={saved} onCancel={() => setAdding(false)} />}
    </div>
  );
}
