// 바탕화면 그림 고르기: 그림 파일 자리(jpg·png·webp)가 SVG 보다 먼저, 한쪽 판만 있으면 둘 다에, 배치 방식별 CSS.
import { describe, expect, test } from 'vitest';
import { backgroundStyle, FITS, pickSource, WALLPAPERS, wallpaperSource } from './wallpapers';

const MATTE = 'var(--bg-wallpaper-matte)';

describe('pickSource', () => {
  test('SVG 두 판이 있으면 테마를 따라간다', () => {
    const files = { 'orbits-light.svg': '/l.svg', 'orbits-dark.svg': '/d.svg' };
    expect(pickSource(files, 'orbits', 'light')).toEqual({ url: '/l.svg', kind: 'vector' });
    expect(pickSource(files, 'orbits', 'dark')).toEqual({ url: '/d.svg', kind: 'vector' });
  });

  test('같은 이름의 그림 파일이 있으면 SVG 보다 먼저 쓴다', () => {
    const files = { 'orbits-light.svg': '/l.svg', 'orbits-dark.svg': '/d.svg', 'orbits-light.webp': '/l.webp', 'orbits-dark.jpg': '/d.jpg' };
    expect(pickSource(files, 'orbits', 'light')).toEqual({ url: '/l.webp', kind: 'image' });
    expect(pickSource(files, 'orbits', 'dark')).toEqual({ url: '/d.jpg', kind: 'image' });
  });

  test('그림 파일이 한쪽 판만 있으면 두 테마 모두 그 그림', () => {
    const files = { 'orbits-light.svg': '/l.svg', 'orbits-dark.svg': '/d.svg', 'orbits-light.png': '/l.png' };
    expect(pickSource(files, 'orbits', 'dark')).toEqual({ url: '/l.png', kind: 'image' });
    expect(pickSource(files, 'orbits', 'light')).toEqual({ url: '/l.png', kind: 'image' });
  });

  test('SVG 도 한쪽만 있으면 둘 다에 쓰고, 아무것도 없으면 null', () => {
    expect(pickSource({ 'contours-dark.svg': '/d.svg' }, 'contours', 'light')).toEqual({ url: '/d.svg', kind: 'vector' });
    expect(pickSource({ 'contours-dark.svg': '/d.svg' }, 'orbits', 'light')).toBeNull();
    expect(pickSource({ 'contours-light.JPEG': '/x.jpeg' }, 'contours', 'dark')).toEqual({ url: '/x.jpeg', kind: 'image' });
  });
});

test('8종 모두 밝은·어두운 SVG 가 들어 있다', () => {
  const ids = WALLPAPERS.map((w) => w.id);
  expect(ids).toEqual(['default', 'prism-schedule', 'orbits', 'contours', 'drafting-grid', 'sculpt-mono', 'chronos-sky', 'minimal-warm', 'minimal-cool']);
  for (const id of ids.slice(1)) {
    for (const theme of ['light', 'dark'] as const) {
      const src = wallpaperSource(id, theme);
      expect(src, `${id}-${theme}`).not.toBeNull();
      expect(src!.url).toContain(`${id}-${theme}`);
    }
  }
  expect(wallpaperSource('default', 'light')).toBeNull();
  expect(WALLPAPERS.find((w) => w.id === 'chronos-sky')?.name).toBe('크로노스 성좌');
});

describe('backgroundStyle', () => {
  const photo = { url: 'blob:http://x/1', kind: 'image' as const };

  test('배치 방식 5가지', () => {
    expect(FITS.map((f) => [f.id, f.name])).toEqual([
      ['fill', '채우기'],
      ['fit', '맞추기'],
      ['stretch', '늘이기'],
      ['tile', '바둑판'],
      ['center', '가운데'],
    ]);
    expect(backgroundStyle(photo, 'fill')).toEqual({
      backgroundImage: 'url("blob:http://x/1")',
      backgroundSize: 'cover',
      backgroundRepeat: 'no-repeat',
      backgroundPosition: 'center',
      backgroundColor: MATTE,
    });
    expect(backgroundStyle(photo, 'fit')).toMatchObject({ backgroundSize: 'contain', backgroundRepeat: 'no-repeat', backgroundPosition: 'center', backgroundColor: MATTE });
    expect(backgroundStyle(photo, 'stretch')).toMatchObject({ backgroundSize: '100% 100%', backgroundRepeat: 'no-repeat' });
    expect(backgroundStyle(photo, 'tile')).toMatchObject({ backgroundSize: 'auto', backgroundRepeat: 'repeat', backgroundPosition: '0 0' });
    expect(backgroundStyle(photo, 'center')).toMatchObject({ backgroundSize: 'auto', backgroundRepeat: 'no-repeat', backgroundPosition: 'center', backgroundColor: MATTE });
  });

  test('SVG 그림은 배치 방식과 상관없이 늘 채우기, 기본은 null(토큰 그라데이션)', () => {
    const svg = { url: '/a.svg', kind: 'vector' as const };
    for (const f of FITS) expect(backgroundStyle(svg, f.id)).toMatchObject({ backgroundSize: 'cover', backgroundRepeat: 'no-repeat' });
    expect(backgroundStyle(null, 'tile')).toBeNull();
  });

  test('주소의 따옴표는 깨지지 않게 바꾼다', () => {
    expect(backgroundStyle({ url: 'data:image/svg+xml,"a"', kind: 'vector' }, 'fill')?.backgroundImage).toBe('url("data:image/svg+xml,%22a%22")');
  });
});
