import { useEffect, useState, type CSSProperties } from 'react';
import { getCustomIconUrl } from './customIcons';
import { AppsIcon, MobileFieldIcon } from './icons';
import type { ProgramManifest } from './registry';

/**
 * 프로그램 아이콘 타일:
 * 1) frontend/src/assets/icons/<id>.{png,webp,svg,jpg} 커스텀 아이콘이 있으면 데스크톱·태블릿·스마트폰 모두 동일 이미지로 표시
 * 2) 없거나 이미지 로드 실패 시 tone 색 그라데이션 타일 + 내장 벡터 SVG 로 안전하게 폴백
 */
export default function ProgramIcon({
  program,
  size = 48,
  iconId,
  className,
}: {
  program: Pick<ProgramManifest, 'id' | 'icon' | 'tone'>;
  size?: number;
  iconId?: string;
  className?: string;
}) {
  const targetId = iconId ?? program.id;
  const customSrc = (iconId ? getCustomIconUrl(iconId) : undefined) ?? getCustomIconUrl(program.id);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setFailed(false);
  }, [customSrc]);

  if (customSrc && !failed) {
    return (
      <span
        className={`os-icon is-custom${className ? ` ${className}` : ''}`}
        data-icon-id={targetId}
        style={{ '--icon-size': `${size}px` } as CSSProperties}
        aria-hidden="true"
      >
        <img src={customSrc} alt="" className="os-icon-img" draggable={false} onError={() => setFailed(true)} />
      </span>
    );
  }

  return (
    <span
      className={`os-icon os-tone-${program.tone ?? 'slate'}${className ? ` ${className}` : ''}`}
      data-icon-id={targetId}
      style={{ '--icon-size': `${size}px` } as CSSProperties}
      aria-hidden="true"
    >
      {program.icon}
    </span>
  );
}

/** 시스템 공통 아이콘(전체 앱 서랍 `apps` · 현장 점검 `field`). 커스텀 파일이 있으면 모든 기기에서 동일하게 교체된다. */
export function SystemIcon({
  id,
  size = 48,
  className,
}: {
  id: 'apps' | 'field';
  size?: number;
  className?: string;
}) {
  const customSrc = getCustomIconUrl(id);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setFailed(false);
  }, [customSrc]);

  if (customSrc && !failed) {
    return (
      <span
        className={`os-icon is-custom${className ? ` ${className}` : ''}`}
        data-icon-id={id}
        style={{ '--icon-size': `${size}px` } as CSSProperties}
        aria-hidden="true"
      >
        <img src={customSrc} alt="" className="os-icon-img" draggable={false} onError={() => setFailed(true)} />
      </span>
    );
  }

  const tone = id === 'field' ? 'rose' : 'slate';
  const glyphSize = Math.round(size * 0.56);
  return (
    <span
      className={`os-icon os-tone-${tone}${className ? ` ${className}` : ''}`}
      data-icon-id={id}
      style={{ '--icon-size': `${size}px` } as CSSProperties}
      aria-hidden="true"
    >
      {id === 'field' ? <MobileFieldIcon /> : <AppsIcon size={glyphSize} />}
    </span>
  );
}
