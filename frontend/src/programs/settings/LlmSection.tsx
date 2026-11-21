import { useCallback, useEffect, useState } from 'react';
import Button from '../../shared/ui/Button';
import AssignmentTable from './AssignmentTable';
import ConnectionCard from './ConnectionCard';
import { llmApi } from './llmApi';
import type { Connection, ConnectionSaved, LlmError } from './model';
import { ErrorLine, savedButFailed, toProblem } from './parts';
import Wizard from './Wizard';

/** 연결 목록. reload 를 부르면 다시 읽는다. 읽기 전에는 null. */
function useConnections() {
  const [connections, setConnections] = useState<Connection[] | null>(null);
  const [error, setError] = useState<LlmError | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let live = true;
    llmApi
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

/** 「LLM 연결」: 위쪽에 연결 카드와 연결 추가, 아래쪽에 작업별 모델 배정(전체 폭 정렬). */
export default function LlmSection() {
  const { connections, error, reload } = useConnections();
  const [adding, setAdding] = useState(false);
  // 저장은 됐지만 저장 때 한 서버의 연결 시험이 실패했으면 그 까닭을 남긴다.
  const [notice, setNotice] = useState<LlmError | null>(null);
  const saved = (s: ConnectionSaved) => {
    setAdding(false);
    setNotice(s.error ? savedButFailed(s.error) : null);
    reload();
  };
  const add = () => {
    setNotice(null);
    setAdding(true);
  };
  return (
    <div className="st-llm">
      <div className="st-col">
        <div className="st-head">
          <div>
            <h2>LLM 연결</h2>
            <p className="st-muted">AI 제공자 연결 키는 암호화 저장되며 실패 시 원인(키 · 주소 · 시간 초과 · 한도)을 안내합니다.</p>
          </div>
          <Button variant="primary" disabled={adding} onClick={add}>
            + 연결 추가
          </Button>
        </div>
        <ErrorLine error={error} />
        <ErrorLine error={notice} />
        {connections?.length === 0 && !adding && (
          <p className="st-muted">아직 연결이 없습니다. 「+ 연결 추가」로 Liner 연결을 넣어 주세요.</p>
        )}
        {connections?.map((c) => <ConnectionCard key={c.id} conn={c} onChanged={reload} />)}
        {adding && <Wizard onSaved={saved} onCancel={() => setAdding(false)} />}
      </div>
      <div className="st-side">
        <div className="st-section-head">
          <h3>작업별 모델 배정</h3>
          <p className="st-muted">에이전트의 6가지 쓰임새마다 사용할 업체·모델과 라우팅 기준을 한 줄씩 지정합니다.</p>
        </div>
        <AssignmentTable connections={connections} />
      </div>
    </div>
  );
}

/** 「작업별 모델 배정」만 따로 연 구역. */
export function AssignSection() {
  const { connections, error } = useConnections();
  return (
    <div className="st-pane st-pane-wide">
      <div className="st-section-head">
        <h2>작업별 모델 배정</h2>
        <p className="st-muted">에이전트의 6가지 쓰임새마다 사용할 업체·모델과 라우팅 기준을 지정합니다.</p>
      </div>
      <ErrorLine error={error} />
      <AssignmentTable connections={connections} />
    </div>
  );
}
