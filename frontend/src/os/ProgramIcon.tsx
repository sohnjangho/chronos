import type { CSSProperties } from 'react';
import type { ProgramManifest } from './registry';

/**
 * 프로그램 아이콘 타일: tone 색의 대각선 그라데이션(밝음 → 어두움), 위쪽 빛, 안쪽 테두리, 부드러운 그림자,
 * 가운데 흰 선 그림. size 는 한 변(px). Dock 48 · 앱 서랍 72 · 정보 64 · 목록 20.
 */
export default function ProgramIcon({ program, size = 48 }: { program: Pick<ProgramManifest, 'icon' | 'tone'>; size?: number }) {
  return (
    <span className={`os-icon os-tone-${program.tone ?? 'slate'}`} style={{ '--icon-size': `${size}px` } as CSSProperties} aria-hidden="true">
      {program.icon}
    </span>
  );
}
