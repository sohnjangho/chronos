// 바탕화면 그림 목록과 고르기. 그림은 frontend/src/assets/wallpapers/<id>-light|dark.svg(코드로 그린 벡터).
// 같은 폴더에 <id>-light|dark.(jpg|jpeg|png|webp) 를 넣으면 그 그림이 SVG 보다 먼저 쓰인다(아이콘과 같은 자동 탐지 —
// customIcons.ts). 한쪽 판만 있으면 두 테마 모두 그 판. 배치 방식은 사진·그림 파일에만, SVG 는 늘 채우기.
import type { CSSProperties } from 'react';
import type { Theme } from './theme';

export type WallpaperId =
  | 'default'
  | 'prism-schedule'
  | 'orbits'
  | 'contours'
  | 'drafting-grid'
  | 'sculpt-mono'
  | 'chronos-sky'
  | 'minimal-warm'
  | 'minimal-cool'
  | 'photo';
export type Fit = 'fill' | 'fit' | 'stretch' | 'tile' | 'center';

/** 서버 schemas(AppearanceState)와 같은 목록·순서. */
export const WALLPAPERS: readonly { id: Exclude<WallpaperId, 'photo'>; name: string }[] = [
  { id: 'default', name: '기본' },
  { id: 'prism-schedule', name: '프리즘 공정' },
  { id: 'orbits', name: '네트워크 궤도' },
  { id: 'contours', name: '지형 등고선' },
  { id: 'drafting-grid', name: '정밀 격자' },
  { id: 'sculpt-mono', name: '스컬프처 모노' },
  { id: 'chronos-sky', name: '크로노스 성좌' },
  { id: 'minimal-warm', name: '미니멀 웜' },
  { id: 'minimal-cool', name: '미니멀 쿨' },
];
export const WALLPAPER_IDS: readonly WallpaperId[] = [...WALLPAPERS.map((w) => w.id), 'photo'];

export const FITS: readonly { id: Fit; name: string }[] = [
  { id: 'fill', name: '채우기' },
  { id: 'fit', name: '맞추기' },
  { id: 'stretch', name: '늘이기' },
  { id: 'tile', name: '바둑판' },
  { id: 'center', name: '가운데' },
];
export const FIT_IDS: readonly Fit[] = FITS.map((f) => f.id);

export interface WallpaperSource {
  url: string;
  /** vector: 코드로 그린 SVG(늘 채우기). image: 사진·그림 파일(배치 방식을 따른다). */
  kind: 'vector' | 'image';
}

// no-inline: 작은 SVG 도 data: 로 넣지 않고 파일로 둔다(브라우저가 한 번 받아 캐시).
const bundled = import.meta.glob<string>('../assets/wallpapers/*.{svg,jpg,jpeg,png,webp,JPG,JPEG,PNG,WEBP}', {
  eager: true,
  import: 'default',
  query: '?no-inline',
});
const BUNDLED: Record<string, string> = {};
for (const [path, url] of Object.entries(bundled)) BUNDLED[path.split('/').pop() ?? path] = url;

let overrides: Record<string, string> | null = null;

/** 시험·미리보기용: 폴더 파일 목록(파일 이름 → 주소)을 바꿔 끼운다. null 이면 폴더 그대로. */
export function setWallpaperFileOverrides(files: Record<string, string> | null): void {
  overrides = files ? { ...files } : null;
}

const IMAGE_EXT = /\.(jpe?g|png|webp)$/i;

/** files(파일 이름 → 주소)에서 id·테마에 맞는 그림. 그림 파일이 하나라도 있으면 그 판들이 SVG 보다 먼저. */
export function pickSource(files: Record<string, string>, id: string, theme: Theme): WallpaperSource | null {
  const other: Theme = theme === 'dark' ? 'light' : 'dark';
  const find = (mode: Theme, image: boolean): string | undefined => {
    const stem = `${id}-${mode}`.toLowerCase();
    for (const [name, url] of Object.entries(files)) {
      const lower = name.toLowerCase();
      if (image ? IMAGE_EXT.test(lower) && lower.replace(IMAGE_EXT, '') === stem : lower === `${stem}.svg`) return url;
    }
    return undefined;
  };
  const image = find(theme, true) ?? find(other, true);
  if (image) return { url: image, kind: 'image' };
  const vector = find(theme, false) ?? find(other, false);
  return vector ? { url: vector, kind: 'vector' } : null;
}

/** 들어 있는 그림 중 id·테마에 맞는 것(기본·내 사진은 null — 기본은 토큰 그라데이션, 사진은 서버에서). */
export function wallpaperSource(id: WallpaperId, theme: Theme): WallpaperSource | null {
  if (id === 'default' || id === 'photo') return null;
  return pickSource(overrides ?? BUNDLED, id, theme);
}

const MATTE = 'var(--bg-wallpaper-matte)';

/** 배경 층의 CSS. null 이면 기본(토큰 --bg-desktop). */
export function backgroundStyle(src: WallpaperSource | null, fit: Fit): CSSProperties | null {
  if (!src) return null;
  const backgroundImage = `url("${src.url.replace(/"/g, '%22')}")`;
  const mode = src.kind === 'vector' ? 'fill' : fit;
  const base = { backgroundImage, backgroundRepeat: 'no-repeat', backgroundPosition: 'center', backgroundColor: MATTE };
  switch (mode) {
    case 'fit':
      return { ...base, backgroundSize: 'contain' };
    case 'stretch':
      return { ...base, backgroundSize: '100% 100%' };
    case 'tile':
      return { ...base, backgroundSize: 'auto', backgroundRepeat: 'repeat', backgroundPosition: '0 0' };
    case 'center':
      return { ...base, backgroundSize: 'auto' };
    default:
      return { ...base, backgroundSize: 'cover' };
  }
}
