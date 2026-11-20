// 오른쪽 「상세」: 고른 카드의 유형·Plan·Actual·OD/RD·TF/FF·진도·주요 자원·선행·후행. 관계를 누르면 관계 고치기.
// 날짜는 서버 값을 글로 바꾸기만 한다.
import type { ReactNode } from 'react';
import { dot, KIND_LABEL, percent } from '../../shared/schedule/format';
import type { Activity, Relation, ScheduleView } from '../../shared/schedule/scheduleApi';
import { md } from './cards';
import { edgeKey, relLabel } from './layout';

/** 2027.05.06 ~ 07.14(같은 해면 끝의 해를 뺀다 — 글자만 견준다). */
function span(start: string, finish: string): string {
  return `${dot(start)} ~ ${start.slice(0, 4) === finish.slice(0, 4) ? md(finish) : dot(finish)}`;
}

function actualText(a: Activity): string {
  if (!a.actual_start) return a.actual_finish ? `~ ${dot(a.actual_finish)}` : '미착수';
  return a.actual_finish ? span(a.actual_start, a.actual_finish) : `${dot(a.actual_start)} ~ (진행 중)`;
}

function Kv({ k, children, danger }: { k: string; children: ReactNode; danger?: boolean }) {
  return (
    <div className="cpm-kv">
      <span>{k}</span>
      <span className={danger ? 'cpm-danger' : undefined}>{children}</span>
    </div>
  );
}

function Links({ title, rels, other, names, onEdit }: { title: string; rels: Relation[]; other: 'pred' | 'succ'; names: Map<string, string>; onEdit(key: string): void }) {
  return (
    <>
      <h3 className="cpm-panel-sub">{title}</h3>
      {rels.length === 0 && <p className="cpm-panel-none">없음</p>}
      {rels.map((r) => {
        const label = relLabel(r.type, r.lag);
        return (
          <button
            key={edgeKey(r)} type="button" className="cpm-link" aria-label={`${r.pred} → ${r.succ} ${label} 관계 고치기`}
            onClick={() => onEdit(edgeKey(r))}
          >
            <span className="cpm-link-id">{r[other]}</span>
            <span className="cpm-link-name">{names.get(r[other]) ?? ''}</span>
            <span className="cpm-link-rel">{label}</span>
          </button>
        );
      })}
    </>
  );
}

function Detail({ view, a, onEdit }: { view: ScheduleView; a: Activity; onEdit(key: string): void }) {
  const names = new Map(view.activities.map((x) => [x.id, x.name]));
  const resources = a.resources.map((id) => view.resources.find((r) => r.id === id)?.name ?? id);
  return (
    <>
      <div className="cpm-panel-title">{`${a.id} ${a.name}`}</div>
      <div className="cpm-kvs">
        <Kv k="유형">{a.critical ? `${KIND_LABEL[a.kind]} · 크리티컬` : KIND_LABEL[a.kind]}</Kv>
        <Kv k="Plan">{a.plan_start && a.plan_finish ? span(a.plan_start, a.plan_finish) : 'Plan 없음'}</Kv>
        <Kv k="Actual">{actualText(a)}</Kv>
        <Kv k="OD / RD">{`${a.od}일 / ${a.rd === null ? '—' : `${a.rd}일`}`}</Kv>
        <Kv k="TF / FF" danger={a.critical}>{`${a.tf}일 / ${a.ff}일`}</Kv>
        <Kv k="진도">{`${percent(a.progress)}%`}</Kv>
        <Kv k="주요 자원">{resources.length ? resources.join(', ') : '없음'}</Kv>
      </div>
      <Links title="선행" rels={view.relations.filter((r) => r.succ === a.id)} other="pred" names={names} onEdit={onEdit} />
      <Links title="후행" rels={view.relations.filter((r) => r.pred === a.id)} other="succ" names={names} onEdit={onEdit} />
    </>
  );
}

interface PanelProps {
  view: ScheduleView;
  selected: string | null;
  /** 관계 고치기(열려 있으면 맨 위에). */
  editor: ReactNode;
  onEdit(key: string): void;
}

export default function DetailPanel({ view, selected, editor, onEdit }: PanelProps) {
  const a = view.activities.find((x) => x.id === selected) ?? null;
  return (
    <section aria-label="상세" className="cpm-panel">
      <h2 className="cpm-panel-head">상세</h2>
      <div className="cpm-panel-body">
        {editor}
        {a ? <Detail view={view} a={a} onEdit={onEdit} /> : <p className="cpm-panel-none">카드를 누르면 상세가 보입니다.</p>}
        <p className="sch-muted cpm-panel-hint">화살표나 선행·후행 관계를 누르면 관계를 고칠 수 있습니다.</p>
      </div>
    </section>
  );
}
