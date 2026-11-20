// 스케줄표 칸(설계 8-1 차례). 보이는 글은 CSV 에도 그대로 쓴다. 고칠 수 있는 칸은 edit 가 있다.
import type { ReactNode } from 'react';
import Badge from '../ui/Badge';
import { dot, KIND_LABEL, percent, statusBadge } from './format';
import type { Activity } from './scheduleApi';

export type ColKey =
  | 'id' | 'name' | 'kind' | 'wbs' | 'weight' | 'od' | 'rd' | 'plan_start' | 'plan_finish'
  | 'actual_start' | 'actual_finish' | 'progress' | 'status' | 'tf' | 'ff' | 'preds'
  | 'constraint' | 'es' | 'ef' | 'resources';

/** 한 액티비티 줄을 그리는 데 드는 글(부모가 미리 만들어 넘긴다 — 글이 같으면 줄을 다시 그리지 않는다). */
export interface CellCtx {
  a: Activity;
  preds: string;
  wbsLabel: string;
  resources: string;
}

export interface ColumnDef {
  key: ColKey;
  header: string;
  width: number;
  align?: 'right';
  /** 남는 폭을 나눠 갖는 칸(width 는 최소 폭). */
  flex?: boolean;
  /** 열 고르기에서 처음에는 꺼진 칸(설계 8-1 「켜는 칸」). */
  optional?: boolean;
  /** 고치는 방법. 없으면 읽기 전용. */
  edit?: 'text' | 'kind' | 'wbs';
  text(c: CellCtx): string;
  render?(c: CellCtx): ReactNode;
  className?(c: CellCtx): string | undefined;
}

const num = (n: number | null) => (n === null ? '' : String(n));

export const COLUMNS: ColumnDef[] = [
  { key: 'id', header: 'ID', width: 96, text: (c) => c.a.id },
  { key: 'name', header: '이름', width: 220, flex: true, edit: 'text', text: (c) => c.a.name },
  { key: 'kind', header: '유형', width: 108, edit: 'kind', text: (c) => KIND_LABEL[c.a.kind] },
  { key: 'wbs', header: 'WBS', width: 108, edit: 'wbs', text: (c) => c.wbsLabel },
  { key: 'weight', header: '가중치(%)', width: 76, align: 'right', text: (c) => percent(c.a.weight) },
  { key: 'od', header: 'OD', width: 52, align: 'right', edit: 'text', text: (c) => num(c.a.od) },
  { key: 'rd', header: 'RD', width: 52, align: 'right', edit: 'text', text: (c) => num(c.a.rd) },
  { key: 'plan_start', header: 'Plan 시작', width: 96, text: (c) => dot(c.a.plan_start) },
  { key: 'plan_finish', header: 'Plan 종료', width: 96, text: (c) => dot(c.a.plan_finish) },
  { key: 'actual_start', header: 'Actual 시작', width: 96, edit: 'text', text: (c) => dot(c.a.actual_start) },
  { key: 'actual_finish', header: 'Actual 종료', width: 96, edit: 'text', text: (c) => dot(c.a.actual_finish) },
  { key: 'progress', header: '진도(%)', width: 64, align: 'right', edit: 'text', text: (c) => percent(c.a.progress) },
  {
    key: 'status',
    header: '상태',
    width: 100,
    text: (c) => statusBadge(c.a.status).label,
    render: (c) => {
      const b = statusBadge(c.a.status);
      return <Badge tone={b.tone}>{b.label}</Badge>;
    },
  },
  { key: 'tf', header: 'TF', width: 48, align: 'right', text: (c) => String(c.a.tf), className: (c) => (c.a.tf <= 0 ? 'danger' : undefined) },
  { key: 'ff', header: 'FF', width: 48, align: 'right', text: (c) => String(c.a.ff) },
  { key: 'preds', header: '선행', width: 160, flex: true, edit: 'text', text: (c) => c.preds },
  {
    key: 'constraint',
    header: '제약',
    width: 140,
    optional: true,
    edit: 'text',
    text: (c) => (c.a.constraint ? `${c.a.constraint.type} ${dot(c.a.constraint.date)}` : ''),
  },
  { key: 'es', header: 'ES', width: 96, optional: true, text: (c) => dot(c.a.es) },
  { key: 'ef', header: 'EF', width: 96, optional: true, text: (c) => dot(c.a.ef) },
  { key: 'resources', header: '주요 자원', width: 140, optional: true, text: (c) => c.resources },
];

/** 늘 보이는 칸(열 고르기에 없다). */
export const FIXED: ColKey[] = ['id', 'name'];

/** 가로로 밀어도 왼쪽에 붙어 있는 칸(ID 96px 다음에 이름). */
export const pinClass = (key: ColKey) => (key === 'id' ? 'pin1' : key === 'name' ? 'pin2' : undefined);

export const DEFAULT_VISIBLE: ColKey[] = COLUMNS.filter((c) => !c.optional).map((c) => c.key);
