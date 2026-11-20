import { useCallback, useEffect, useState } from 'react';
import Button from '../../shared/ui/Button';
import Field from '../../shared/ui/Field';
import InfoCard, { KEY_HINT } from './InfoCard';
import { INFO_PRESETS, infoApi, type InfoConnection, type InfoPreset } from './infoApi';
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

/** 연결 추가: 종류(기상청만) · 이름 · 서비스 키. 주소는 서버가 종류의 기본 주소로 채운다. 저장·취소 때 키 칸을 비운다. */
function AddForm({ onSaved, onCancel }: { onSaved(): void; onCancel(): void }) {
  const [preset, setPreset] = useState<InfoPreset>('kma');
  const [name, setName] = useState('기상청 날씨');
  const [secret, setSecret] = useState('');
  const [error, setError] = useState<LlmError | null>(null);
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await infoApi.create({ name: name.trim(), preset, secret });
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
    <section className="st-card" role="group" aria-label="정보 API 연결 추가">
      <b className="st-card-name">연결 추가</b>
      <div className="st-grid2">
        <Field label="종류">
          <select value={preset} disabled={busy} onChange={(e) => setPreset(e.target.value as InfoPreset)}>
            {INFO_PRESETS.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>
        </Field>
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
    </section>
  );
}

/** 「정보 API 연결」(관리자): 에이전트 도구가 쓰는 바깥 정보. LLM 연결과 같은 모양의 카드. */
export default function InfoSection() {
  const { connections, error, reload } = useInfoConnections();
  const [adding, setAdding] = useState(false);
  const saved = () => {
    setAdding(false);
    reload();
  };
  return (
    <div className="st-pane">
      <div className="st-head">
        <h2>정보 API 연결</h2>
        <Button variant="primary" disabled={adding} onClick={() => setAdding(true)}>
          + 연결 추가
        </Button>
      </div>
      <p className="st-muted">에이전트 도구가 쓰는 바깥 정보 · 키는 암호화하고 끝 4자리만 보입니다.</p>
      <ErrorLine error={error} />
      {connections?.length === 0 && !adding && (
        <p className="st-muted">아직 연결이 없습니다. 「+ 연결 추가」로 기상청 서비스 키를 넣어 주세요.</p>
      )}
      {connections?.map((c) => <InfoCard key={c.id} conn={c} onChanged={reload} />)}
      {adding && <AddForm onSaved={saved} onCancel={() => setAdding(false)} />}
      <p className="st-muted">
        쓰는 도구 info.weather — 지난 해들 그 달 통계(코드가 계산) · 3일 예보. 숫자는 근거로만 붙이고 날짜 계산에는 넣지 않습니다.
      </p>
    </div>
  );
}
