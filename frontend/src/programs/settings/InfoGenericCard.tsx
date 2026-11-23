import { useState } from 'react';
import Badge from '../../shared/ui/Badge';
import Button from '../../shared/ui/Button';
import { DeletePanel, STATUS, type Mode, type Outcome } from './InfoCard';
import GenericEditForm from './InfoGenericEdit';
import { infoApi, type InfoConnection, type InfoTest } from './infoApi';
import { checkedText } from './model';
import { ErrorLine, toProblem } from './parts';

/** 주소의 호스트+경로만(https:// 와 끝 / 를 뺀다). 못 읽으면 그대로. */
export function hostPath(url: string): string {
  try {
    const u = new URL(url);
    return `${u.host}${u.pathname}`.replace(/\/+$/, '');
  } catch {
    return url;
  }
}

/** 범용 시험 결과: 요약 한 줄, HTTP 상태·걸린 시간, 실패면 서버 글, 응답 앞부분(고정폭·줄바꿈·높이 제한). */
function GenericTestResult({ test }: { test: InfoTest }) {
  const s = test.services[0];
  const status = test.http_status ?? null;
  return (
    <div className="st-info-result" role="status" aria-label="연결 테스트 결과">
      <div className={`st-probe ${test.ok ? 'st-probe-ok' : 'st-probe-fail'}`}>{test.summary}</div>
      <div className="st-info-line">
        {status !== null && <Badge tone={status >= 200 && status < 300 ? 'success' : 'danger'}>{`HTTP ${status}`}</Badge>}
        {s && <span className="st-muted">{`${s.latency_ms}ms`}</span>}
      </div>
      <ErrorLine error={s?.error} />
      {test.sample && <pre className="st-info-sample">{test.sample}</pre>}
    </div>
  );
}

/** 범용 연결 카드(접힌 높이 고정): 이름·「범용」·상태·[연결 테스트][고치기][지우기] / 호스트+경로·키 끝 4자리·확인 시각 / 설명 2줄. */
export default function InfoGenericCard({ conn, onChanged }: { conn: InfoConnection; onChanged(): void }) {
  const [mode, setMode] = useState<Mode>('idle');
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [pathError, setPathError] = useState<string | undefined>();
  const [busy, setBusy] = useState(false);
  const status = STATUS[conn.status];
  async function test() {
    setMode('idle');
    setBusy(true);
    setOutcome(null);
    setPathError(undefined);
    try {
      setOutcome({ test: await infoApi.test(conn.id) });
    } catch (e) {
      const p = toProblem(e);
      if (p.code === 'test_path_required') {
        setPathError(p.message);
        setMode('edit');
      } else setOutcome({ error: p });
    } finally {
      setBusy(false);
    }
    onChanged();
  }
  async function remove() {
    setMode('idle');
    try {
      await infoApi.remove(conn.id);
    } catch (e) {
      setOutcome({ error: toProblem(e) });
    }
    onChanged();
  }
  const open = (m: Mode) => {
    setOutcome(null);
    setPathError(undefined);
    setMode(m);
  };
  const saved = () => {
    setMode('idle');
    setOutcome({ note: '저장했습니다.' });
    onChanged();
  };
  const locked = busy || mode !== 'idle';
  return (
    <article className="st-card st-info-gcard" aria-label={conn.name}>
      <div className="st-card-head st-info-ghead">
        <b className="st-card-name st-info-gname" title={conn.name}>
          {conn.name}
        </b>
        <Badge tone="info">범용</Badge>
        <Badge tone={status.tone}>{status.text}</Badge>
        <span className="st-gap" />
        <div className="st-info-gactions">
          <Button disabled={locked} onClick={test}>
            연결 테스트
          </Button>
          <Button disabled={locked} onClick={() => open('edit')}>
            고치기
          </Button>
          <Button className="st-danger-text" disabled={locked} onClick={() => open('delete')}>
            지우기
          </Button>
        </div>
      </div>
      <div className="st-info-meta">
        <span className="st-info-host" title={conn.base_url}>
          {hostPath(conn.base_url)}
        </span>
        <span>{`키 …${conn.secret_last4}`}</span>
        <span>{checkedText(conn.checked_at, null)}</span>
      </div>
      <p className="st-info-desc" title={conn.description}>
        {conn.description}
      </p>
      {mode === 'edit' && <GenericEditForm conn={conn} pathError={pathError} onSaved={saved} onCancel={() => setMode('idle')} />}
      {mode === 'delete' && <DeletePanel name={conn.name} note="에이전트가 이 연결을 더 쓰지 못합니다." onCancel={() => setMode('idle')} onConfirm={remove} />}
      {outcome?.note && <p className="st-note">{outcome.note}</p>}
      {outcome?.test && <GenericTestResult test={outcome.test} />}
      <ErrorLine error={outcome?.error} />
    </article>
  );
}
