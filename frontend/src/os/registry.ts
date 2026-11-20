import type { ComponentType, LazyExoticComponent, ReactNode } from 'react';
import type { Role } from './session';

/** 프로그램 화면이 받는 값. params 는 windowStore.open 으로 넘긴 것. */
export interface ProgramProps {
  windowId: string;
  params?: Record<string, string>;
}

/**
 * 펼침 메뉴의 한 줄. action 은 맨 앞 창의 id 를 받는다. shortcut 은 보이기만 한다(예 "Ctrl+Alt+R").
 * checked 를 주면 체크 항목(✓). separatorBefore 면 앞에 구분선. group 이 바뀌는 곳에는 구분선과
 * 묶음 제목(group 글, 누를 수 없음)이 들어간다.
 */
export interface ProgramMenuItem {
  label: string;
  action: (windowId: string) => void;
  shortcut?: string;
  disabled?: boolean;
  checked?: boolean;
  separatorBefore?: boolean;
  group?: string;
}

/** 메뉴바의 펼침 메뉴 하나(예 「보기」). 「보기」가 있으면 셸이 배율 항목을 그 끝에 붙인다. */
export interface ProgramMenu {
  label: string;
  items: ProgramMenuItem[];
}

/** 아이콘 타일 색(tokens.css 의 --tile-<tone>-from/to). */
export type IconTone = 'blue' | 'violet' | 'teal' | 'indigo' | 'amber' | 'sky' | 'green' | 'rose' | 'slate';

export interface ProgramManifest {
  id: string;
  name: string;
  /** 흰 선 그림(24px, glyph). 셸이 tone 색 타일 위에 그린다. */
  icon: ReactNode;
  /** 타일 색. 없으면 slate. */
  tone?: IconTone;
  kind: 'work' | 'system';
  adminOnly?: boolean;
  defaultSize: { w: number; h: number };
  menus?: ProgramMenu[];
  component: LazyExoticComponent<ComponentType<ProgramProps>>;
  badge?: 'approvals';
}

const entries = new Map<string, ProgramManifest>();

/** 같은 id 를 다시 등록하면 자리는 그대로 두고 내용만 바꾼다. */
export function register(m: ProgramManifest): void {
  entries.set(m.id, m);
}

/** 등록한 차례대로. 관리자 전용은 관리자에게만. */
export function programs(role: Role): ProgramManifest[] {
  return [...entries.values()].filter((p) => role === 'admin' || !p.adminOnly);
}

export function getProgram(id: string): ProgramManifest | undefined {
  return entries.get(id);
}
