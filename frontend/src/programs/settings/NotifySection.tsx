import { useCallback, useEffect, useState } from 'react';
import Button from '../../shared/ui/Button';
import type { LlmError } from './model';
import NotifyAdd from './NotifyAdd';
import NotifyCard from './NotifyCard';
import { notifyApi, type NotifyConnection, type NotifySaved } from './notifyApi';
import { ErrorLine, savedButFailed, toProblem } from './parts';
import './notify.css';

/** 연결 목록. reload 를 부르면 다시 읽는다. 읽기 전에는 null. */
function useNotifyConnections() {
  const [connections, setConnections] = useState<NotifyConnection[] | null>(null);
  const [error, setError] = useState<LlmError | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let live = true;
    notifyApi
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

/** 「알림 연결」(관리자): 협력사에게 문자·카카오톡·전화를 보내는 연결. 카드마다 진단 결과와 발송 설정. */
export default function NotifySection() {
  const { connections, error, reload } = useNotifyConnections();
  const [adding, setAdding] = useState(false);
  // 저장은 됐지만 저장 직후 연결 테스트가 실패했으면 그 까닭을 남긴다.
  const [notice, setNotice] = useState<LlmError | null>(null);
  const saved = (s: NotifySaved) => {
    setAdding(false);
    setNotice(s.error ? savedButFailed(s.error) : null);
    reload();
  };
  const add = () => {
    setNotice(null);
    setAdding(true);
  };
  return (
    <div className="st-pane st-nt">
      <div className="st-head">
        <div>
          <h2>알림 연결</h2>
          <p className="st-muted">협력사에게 문자·카카오톡·전화를 보내는 연결 · 키는 암호화하고 끝 4자리만 보입니다.</p>
        </div>
        <Button variant="primary" disabled={adding} onClick={add}>
          + 연결 추가
        </Button>
      </div>
      <ErrorLine error={error} />
      <ErrorLine error={notice} />
      {connections?.length === 0 && !adding && (
        <p className="st-muted">아직 연결이 없습니다. 「+ 연결 추가」로 한국AI통신 API Key 와 Account ID 를 넣어 주세요.</p>
      )}
      {connections?.map((c) => <NotifyCard key={c.id} conn={c} onChanged={reload} />)}
      {adding && <NotifyAdd onSaved={saved} onCancel={() => setAdding(false)} />}
    </div>
  );
}
