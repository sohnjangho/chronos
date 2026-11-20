import type { ComponentType, LazyExoticComponent, ReactNode } from 'react';
import type { Role } from './session';

/** 프로그램 화면이 받는 값. params 는 windowStore.open 으로 넘긴 것. */
export interface ProgramProps {
  windowId: string;
  params?: Record<string, string>;
}

/** 메뉴바에 붙는 프로그램 메뉴. action 은 맨 앞 창의 id 를 받는다. */
export interface ProgramMenu {
  label: string;
  action: (windowId: string) => void;
}

export interface ProgramManifest {
  id: string;
  name: string;
  icon: ReactNode;
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
