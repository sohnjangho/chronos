import { useState } from 'react';
import PickList from '../../../os/PickList';
import Badge from '../../../shared/ui/Badge';
import type { Activity, PredItem, RelType, ScheduleView } from '../scheduleApi';
import { useSchedule } from '../scheduleStore';
import Popover from './Popover';
import { wbsLabel, wbsTree } from './rows';

const TYPES: RelType[] = ['FS', 'SS', 'FF', 'SF'];
const LAG_ERROR = '간격은 정수(일)로 넣어 주세요.';

/** succ 의 선행 목록(저장된 차례). */
const predsOf = (view: ScheduleView, succ: string): PredItem[] =>
  view.relations.filter((r) => r.succ === succ).map(({ pred, type, lag }) => ({ pred, type, lag }));

/** succ 의 선행 i 번째를 고치거나(patch) 지운다(null). */
function editRelation(view: ScheduleView, succ: string, i: number, patch: Partial<PredItem> | null) {
  const items = predsOf(view, succ);
  const next = patch === null ? items.filter((_, k) => k !== i) : items.map((it, k) => (k === i ? { ...it, ...patch } : it));
  return useSchedule.getState().setPredecessors(succ, next);
}

interface Link {
  /** 표에 보이는 상대 액티비티. */
  other: string;
  pred: string;
  succ: string;
  type: RelType;
  lag: number;
  /** succ 의 선행 목록에서의 차례. */
  index: number;
}

function linksOf(view: ScheduleView, aid: string, side: 'pred' | 'succ'): Link[] {
  const seen = new Map<string, number>();
  const out: Link[] = [];
  for (const r of view.relations) {
    const index = seen.get(r.succ) ?? 0;
    seen.set(r.succ, index + 1);
    if ((side === 'pred' ? r.succ : r.pred) === aid) out.push({ ...r, other: side === 'pred' ? r.pred : r.succ, index });
  }
  return out;
}

function LagInput({ link, view }: { link: Link; view: ScheduleView }) {
  const name = `${link.pred} → ${link.succ}`;
  const save = (input: HTMLInputElement) => {
    const text = input.value.trim();
    if (!/^-?\d+$/.test(text)) {
      useSchedule.getState().setNotice({ tone: 'error', text: LAG_ERROR });
      input.value = String(link.lag);
    } else if (Number(text) !== link.lag) {
      // 서버가 거절하면 원래 간격으로 돌린다.
      void editRelation(view, link.succ, link.index, { lag: Number(text) }).then((ok) => ok || (input.value = String(link.lag)));
    }
  };
  return (
    <input
      key={link.lag}
      type="number"
      step={1}
      className="sch-lag"
      aria-label={`${name} 간격(일)`}
      defaultValue={link.lag}
      onBlur={(e) => save(e.currentTarget)}
      onKeyDown={(e) => e.key === 'Enter' && save(e.currentTarget)}
    />
  );
}

function RelTable({ title, links, view }: { title: '선행' | '후행'; links: Link[]; view: ScheduleView }) {
  const names = new Map(view.activities.map((a) => [a.id, a.name]));
  return (
    <table className="sch-rel-table" aria-label={title}>
      <thead>
        <tr>
          {['구분', 'ID', '이름', '관계', '간격(일)', ''].map((h, i) => (
            <th key={i} scope="col">
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {links.length === 0 && (
          <tr>
            <td colSpan={6} className="sch-muted">
              {`${title}이 없습니다.`}
            </td>
          </tr>
        )}
        {links.map((l) => {
          const name = `${l.pred} → ${l.succ}`;
          return (
            <tr key={`${l.succ}:${l.index}`}>
              <td>{title}</td>
              <td>{l.other}</td>
              <td title={names.get(l.other)}>{names.get(l.other)}</td>
              <td>
                <select aria-label={`${name} 관계`} value={l.type} onChange={(e) => void editRelation(view, l.succ, l.index, { type: e.target.value as RelType })}>
                  {TYPES.map((t) => (
                    <option key={t}>{t}</option>
                  ))}
                </select>
              </td>
              <td>
                <LagInput link={l} view={view} />
              </td>
              <td>
                <button type="button" className="sch-x" aria-label={`${name} 관계 지우기`} onClick={() => void editRelation(view, l.succ, l.index, null)}>
                  ×
                </button>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/** + 선행 추가 / + 후행 추가: WBS 로 묶은 찾기 목록에서 고른다. */
function AddLink({ side, a, view }: { side: 'pred' | 'succ'; a: Activity; view: ScheduleView }) {
  const [query, setQuery] = useState('');
  const label = side === 'pred' ? '선행으로 넣을 액티비티' : '후행으로 넣을 액티비티';
  const taken = new Set(linksOf(view, a.id, side).map((l) => l.other).concat(a.id));
  const q = query.trim().toLowerCase();
  const tree = wbsTree(view);
  const groups = [...tree.acts.keys()].map((code) => ({
    title: wbsLabel(view.wbs.find((w) => w.code === code) ?? { code, name: '', parent: null }),
    acts: (tree.acts.get(code) ?? []).filter((x) => !taken.has(x.id) && (!q || `${x.id} ${x.name}`.toLowerCase().includes(q))),
  }));
  const add = (other: string) => {
    const succ = side === 'pred' ? a.id : other;
    const item: PredItem = { pred: side === 'pred' ? other : a.id, type: 'FS', lag: 0 };
    void useSchedule.getState().setPredecessors(succ, [...predsOf(view, succ), item]);
  };
  return (
    <Popover button={side === 'pred' ? '+ 선행 추가' : '+ 후행 추가'} label={label} up align="right" role="none">
      {(close) => (
        <PickList
          className="sch-pick"
          label={label}
          placeholder="ID·이름 찾기"
          query={query}
          onQuery={setQuery}
          onClose={close}
          groups={groups.map((g) => ({
            title: g.title,
            items: g.acts.map((x) => ({ key: x.id, label: x.name, detail: x.id, run: () => (close(), add(x.id)) })),
          }))}
        />
      )}
    </Popover>
  );
}

/** 아래 관계 패널: 고른 액티비티의 선행·후행을 종류(FS·SS·FF·SF)와 간격으로 고친다. */
export default function RelationsPanel() {
  const view = useSchedule((s) => s.view)!;
  const selected = useSchedule((s) => s.selected);
  const a = selected ? view.activities.find((x) => x.id === selected) : undefined;
  return (
    <section aria-label="관계" className="sch-rel">
      <div className="sch-rel-head">
        <b>관계</b>
        {a ? <Badge tone="info">{`${a.id} ${a.name}`}</Badge> : <Badge>선택 없음</Badge>}
        <span className="sch-gap" />
        {a && <AddLink side="pred" a={a} view={view} />}
        {a && <AddLink side="succ" a={a} view={view} />}
      </div>
      {a ? (
        <div className="sch-rel-tables">
          <RelTable title="선행" links={linksOf(view, a.id, 'pred')} view={view} />
          <RelTable title="후행" links={linksOf(view, a.id, 'succ')} view={view} />
        </div>
      ) : (
        <div className="sch-rel-empty">
          <b>액티비티를 선택하세요</b>
          <span>위 표에서 액티비티 행을 누르면 선행·후행 관계를 고칠 수 있습니다.</span>
        </div>
      )}
    </section>
  );
}
