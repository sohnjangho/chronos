// 바탕화면 배경 층 하나(데스크톱·태블릿·스마트폰 셸 맨 뒤). 고정된 한 장이라 창을 옮겨도 그림을 다시 풀지 않는다.
import { useEffect, type CSSProperties } from 'react';
import { useSession } from './session';
import { useTheme } from './theme';
import { backgroundStyle, wallpaperSource, type WallpaperSource } from './wallpapers';
import { useWallpaper } from './wallpaperStore';

/** 지금 고른 배경의 CSS(null 이면 기본 그라데이션). 내 사진을 아직 못 받았거나 없으면 기본. */
export function useWallpaperBackground(): { style: CSSProperties | null; source: WallpaperSource | null } {
  const wallpaper = useWallpaper((s) => s.wallpaper);
  const fit = useWallpaper((s) => s.fit);
  const photo = useWallpaper((s) => s.photo);
  const theme = useTheme((s) => s.theme);
  const source =
    wallpaper === 'photo' ? (photo.status === 'ready' ? { url: photo.url, kind: 'image' as const } : null) : wallpaperSource(wallpaper, theme);
  return { style: backgroundStyle(source, fit), source };
}

export default function WallpaperLayer() {
  const userId = useSession((s) => s.session?.user.id ?? null);
  const wallpaper = useWallpaper((s) => s.wallpaper);
  const photoStatus = useWallpaper((s) => s.photo.status);
  const { style } = useWallpaperBackground();
  useEffect(() => {
    if (userId !== null) void useWallpaper.getState().sync(); // 다른 기기에서 고른 것을 받아 온다
  }, [userId]);
  useEffect(() => {
    if (wallpaper === 'photo' && photoStatus === 'unknown') void useWallpaper.getState().loadPhoto();
  }, [wallpaper, photoStatus]);
  return <div className="os-wallpaper" data-testid="wallpaper-layer" aria-hidden="true" style={style ?? undefined} />;
}
