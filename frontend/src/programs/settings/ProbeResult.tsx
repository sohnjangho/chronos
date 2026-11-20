import { useState } from 'react';
import type { Probe } from './model';
import { ErrorLine } from './parts';

/** 이보다 많으면 찾기 칸을 보인다. */
const LONG_LIST = 12;

function ModelList({ models }: { models: string[] }) {
  const [query, setQuery] = useState('');
  const q = query.trim().toLowerCase();
  const shown = q ? models.filter((m) => m.toLowerCase().includes(q)) : models;
  return (
    <div className="st-models">
      {models.length > LONG_LIST && (
        <input
          className="st-search"
          aria-label="모델 찾기"
          placeholder="모델 찾기"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      )}
      <ul className="st-model-list" aria-label="모델 목록">
        {shown.map((m) => (
          <li key={m}>{m}</li>
        ))}
      </ul>
      {shown.length === 0 && <p className="st-muted">찾는 모델이 없습니다.</p>}
    </div>
  );
}

/** 연결 시험 결과: 성공이면 응답 시간·모델 수·모델 목록, 실패면 서버의 글과 코드. */
export default function ProbeResult({ probe }: { probe: Probe }) {
  if (!probe.ok) {
    return (
      <div className="st-probe st-probe-fail">
        <div>
          <b>연결하지 못했습니다</b>
          {` · 응답 ${probe.latency_ms}ms`}
        </div>
        <ErrorLine error={probe.error ?? { code: 'unknown', message: '원인을 알 수 없습니다.' }} />
      </div>
    );
  }
  return (
    <>
      <div className="st-probe st-probe-ok" role="status">
        <b>연결되었습니다</b>
        {` · 응답 ${probe.latency_ms}ms · 모델 ${probe.models.length}개를 불러왔습니다`}
      </div>
      <ModelList models={probe.models} />
    </>
  );
}
