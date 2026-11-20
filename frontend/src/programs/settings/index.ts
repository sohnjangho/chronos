import { lazy } from 'react';
import { glyph } from '../../os/glyph';
import type { ProgramManifest, ProgramMenu } from '../../os/registry';
import { useSession } from '../../os/session';
import { useWindows } from '../../os/windowStore';
import { visibleSections } from './model';

/** 「보기」 메뉴: 지금 역할이 볼 수 있는 구역. 누르면 설정 창에서 그 구역을 연다. */
function sectionMenus(): ProgramMenu[] {
  const role = useSession.getState().session?.user.role ?? 'user';
  const items = visibleSections(role).map((s) => ({
    label: s.label,
    action: () => void useWindows.getState().open('settings', { section: s.id }),
  }));
  return [{ label: '보기', items }];
}

const manifest: ProgramManifest = {
  id: 'settings',
  name: '설정',
  kind: 'system',
  defaultSize: { w: 1300, h: 860 },
  icon: glyph('M4 7h16', 'M4 17h16', 'M9 4v6', 'M15 14v6'),
  component: lazy(() => import('./Settings')),
  // 메뉴바가 그릴 때마다 읽는다. 관리자 구역은 관리자에게만 보인다(역할은 로그인할 때 정해진다).
  get menus() {
    return sectionMenus();
  },
};

export default manifest;
