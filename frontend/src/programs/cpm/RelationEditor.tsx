// 관계 고치기: 종류(FS·SS·FF·SF)·간격 → 후행의 선행 목록을 바꿔 일정 저장소의 선행 쓰기로 보낸다(오류·409 는 저장소가 알린다).
// 목록은 보낼 차례가 왔을 때의 일정으로 만든다 — 그 사이 그 관계가 바뀌었으면 보내지 않고 알린다.
import { useId, useState, type FormEvent } from 'react';
import type { PredItem, Relation, RelType, ScheduleView } from '../../shared/schedule/scheduleApi';
import { useNotify, useScheduleStore, useWindowId } from '../../shared/schedule/scope';
import Button from '../../shared/ui/Button';

const TYPES: RelType[] = ['FS', 'SS', 'FF', 'SF'];
const LAG = /^[+-]?\d+$/;
export const LAG_ERROR = '간격은 정수(일)로 넣어 주세요.';
const LINK_GONE = '그 사이 관계가 바뀌어 고치지 못했습니다';

const predsOf = (view: ScheduleView, succ: string): PredItem[] =>
  view.relations.filter((r) => r.succ === succ).map(({ pred, type, lag }) => ({ pred, type, lag }));

export default function RelationEditor({ rel, onClose }: { rel: Relation; onClose(): void }) {
  const store = useScheduleStore();
  const windowId = useWindowId();
  const notify = useNotify();
  const [type, setType] = useState<RelType>(rel.type);
  const [lag, setLag] = useState(String(rel.lag));
  const id = useId();

  /** patch 로 고치거나(null 이면 지운다) 보낸다. 성공하면 닫는다. */
  async function send(patch: Partial<PredItem> | null) {
    const ok = await store.getState().setPredecessors(rel.succ, (view) => {
      const items = predsOf(view, rel.succ);
      const i = items.findIndex((it) => it.pred === rel.pred && it.type === rel.type && it.lag === rel.lag);
      if (i < 0) {
        store.getState().setNotice({ tone: 'error', text: LINK_GONE, windowId });
        return null;
      }
      return patch === null ? items.filter((_, k) => k !== i) : items.map((it, k) => (k === i ? { ...it, ...patch } : it));
    });
    if (ok) onClose();
  }

  function save(e: FormEvent) {
    e.preventDefault();
    const text = lag.trim();
    if (!LAG.test(text)) return notify('error', LAG_ERROR);
    const n = Number(text);
    if (type === rel.type && n === rel.lag) return onClose();
    void send({ type, lag: n });
  }

  return (
    <form aria-label="관계 고치기" className="cpm-rel" onSubmit={save}>
      <div className="cpm-rel-head">
        <b>{`${rel.pred} → ${rel.succ}`}</b>
        <button type="button" className="sch-x" aria-label="관계 고치기 닫기" onClick={onClose}>
          ×
        </button>
      </div>
      <div className="cpm-rel-fields">
        <label htmlFor={`${id}-type`}>종류</label>
        <select id={`${id}-type`} value={type} onChange={(e) => setType(e.target.value as RelType)}>
          {TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <label htmlFor={`${id}-lag`}>간격</label>
        <span className="cpm-rel-lag">
          <input id={`${id}-lag`} inputMode="numeric" value={lag} onChange={(e) => setLag(e.target.value)} />
          <span className="sch-muted">일</span>
        </span>
      </div>
      <div className="cpm-rel-actions">
        <Button variant="danger" onClick={() => void send(null)}>
          삭제
        </Button>
        <span className="sch-gap" />
        <Button onClick={onClose}>취소</Button>
        <Button type="submit" variant="primary">
          저장
        </Button>
      </div>
    </form>
  );
}
