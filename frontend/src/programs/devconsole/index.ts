import { lazy } from 'react';
import { glyph } from '../../os/glyph';
import type { ProgramManifest } from '../../os/registry';

// 「개발 콘솔」 자리(화면은 이후 작업이 채운다).
const manifest: ProgramManifest = {
  id: 'devconsole',
  name: '개발 콘솔',
  tone: 'graphite',
  kind: 'system',
  adminOnly: true,
  defaultSize: { w: 1600, h: 900 },
  icon: glyph('M4 5h16v14H4z', 'M7.5 10l2.5 2-2.5 2', 'M12.5 15h4'),
  component: lazy(() => import('../../os/Placeholder')),
};

export default manifest;
