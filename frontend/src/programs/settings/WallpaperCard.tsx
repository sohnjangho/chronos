import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type RefObject } from 'react';
import { useTheme } from '../../os/theme';
import { useWallpaperBackground } from '../../os/WallpaperLayer';
import { backgroundStyle, FITS, WALLPAPERS, wallpaperSource } from '../../os/wallpapers';
import { useWallpaper } from '../../os/wallpaperStore';
import Button from '../../shared/ui/Button';
import './wallpaper.css';

const ACCEPT = 'image/jpeg,image/png,image/webp';

/** 미리보기: 지금 화면 크기의 바탕을 줄여 그대로 보인다(바둑판·가운데도 실제 크기 비율대로). */
function Preview() {
  const { style } = useWallpaperBackground();
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(360);
  const screenW = Math.max(320, window.innerWidth);
  const screenH = Math.max(240, window.innerHeight);
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    const measure = () => setWidth(el.clientWidth || 360);
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const k = width / screenW;
  return (
    <div className="st-wp-preview" ref={box} style={{ aspectRatio: `${screenW} / ${screenH}`, width: `min(100%, ${Math.round((300 * screenW) / screenH)}px)` }} role="img" aria-label="배경 미리보기">
      <div
        className="st-wp-preview-layer"
        data-testid="wallpaper-preview-layer"
        style={{ width: screenW, height: screenH, transform: `scale(${k})`, ...(style ?? {}) }}
      />
      <span className="st-wp-preview-win" aria-hidden="true" />
      <span className="st-wp-preview-dock" aria-hidden="true" />
    </div>
  );
}

/** 그림 칸들: 기본·8종(지금 테마의 판으로)·내 사진(없으면 누르면 사진 고르기). */
function Tiles({ busy, onPickFile }: { busy: boolean; onPickFile(): void }) {
  const theme = useTheme((s) => s.theme);
  const wallpaper = useWallpaper((s) => s.wallpaper);
  const photo = useWallpaper((s) => s.photo);
  const photoThumb: CSSProperties | undefined =
    photo.status === 'ready' ? (backgroundStyle({ url: photo.url, kind: 'image' }, 'fill') ?? undefined) : undefined;
  return (
    <div className="st-wp-grid" role="group" aria-label="배경 그림">
      {WALLPAPERS.map((w) => (
        <button
          key={w.id}
          type="button"
          className="st-wp-tile"
          aria-pressed={wallpaper === w.id}
          onClick={() => useWallpaper.getState().choose(w.id)}
        >
          <span className="st-wp-thumb" aria-hidden="true" style={backgroundStyle(wallpaperSource(w.id, theme), 'fill') ?? undefined} />
          <span className="st-wp-name">{w.name}</span>
        </button>
      ))}
      <button
        type="button"
        className="st-wp-tile"
        aria-pressed={wallpaper === 'photo'}
        disabled={busy}
        onClick={() => (photoThumb ? useWallpaper.getState().choose('photo') : onPickFile())}
      >
        <span className={photoThumb ? 'st-wp-thumb' : 'st-wp-thumb is-empty'} aria-hidden="true" style={photoThumb}>
          {photoThumb ? null : '+'}
        </span>
        <span className="st-wp-name">내 사진</span>
      </button>
    </div>
  );
}

/** 배치 방식 5가지(사진·그림 파일일 때만). */
function FitControl() {
  const fit = useWallpaper((s) => s.fit);
  return (
    <div className="st-wp-fits" role="radiogroup" aria-label="배치 방식">
      {FITS.map((f) => (
        <button
          key={f.id}
          type="button"
          role="radio"
          aria-checked={fit === f.id}
          className="st-wp-fit"
          onClick={() => useWallpaper.getState().setFit(f.id)}
        >
          {f.name}
        </button>
      ))}
    </div>
  );
}

/** 사진 올리기·바꾸기·지우기와 그 오류(한국어). */
function usePhotoActions(input: RefObject<HTMLInputElement | null>) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async (job: () => Promise<void>, fallback: string) => {
    setError(null);
    setBusy(true);
    try {
      await job();
    } catch (e) {
      setError(e instanceof Error ? e.message : fallback);
    } finally {
      setBusy(false);
      if (input.current) input.current.value = '';
    }
  };
  return {
    error,
    busy,
    clearError: () => setError(null),
    upload: (file: File | undefined) => file && void run(() => useWallpaper.getState().uploadPhoto(file), '사진을 올리지 못했습니다.'),
    remove: () => void run(() => useWallpaper.getState().removePhoto(), '사진을 지우지 못했습니다.'),
  };
}

/** 설정 → 화면의 「배경」: 그림 고르기, 내 사진 올리기·바꾸기·지우기, 사진(그림 파일)일 때 배치 방식, 미리보기. */
export default function WallpaperCard() {
  const wallpaper = useWallpaper((s) => s.wallpaper);
  const hasPhoto = useWallpaper((s) => s.photo.status === 'ready');
  const { source } = useWallpaperBackground();
  const input = useRef<HTMLInputElement>(null);
  const { error, busy, clearError, upload, remove } = usePhotoActions(input);

  useEffect(() => {
    if (useWallpaper.getState().photo.status === 'unknown') void useWallpaper.getState().loadPhoto();
  }, []);
  useEffect(() => clearError(), [wallpaper]); // 다른 그림을 고르면 앞 오류를 걷는다

  const current = wallpaper === 'photo' ? '내 사진' : WALLPAPERS.find((w) => w.id === wallpaper)?.name;
  const label = busy ? '올리는 중…' : hasPhoto ? '사진 바꾸기' : '사진 올리기';
  return (
    <section className="st-card" aria-label="바탕화면 배경">
      <div className="st-card-head">
        <b className="st-card-name">배경</b>
        <span className="st-gap" />
        <span className="st-muted">{`현재: ${current ?? '기본'}`}</span>
      </div>
      <div className="st-wp-body">
        <Preview />
        <div className="st-wp-side">
          <Tiles busy={busy} onPickFile={() => input.current?.click()} />
          <div className="st-wp-actions">
            <label className={busy ? 'st-wp-upload is-busy' : 'st-wp-upload'}>
              <input
                ref={input}
                type="file"
                accept={ACCEPT}
                aria-label={hasPhoto ? '사진 바꾸기' : '사진 올리기'}
                disabled={busy}
                onChange={(e) => upload(e.target.files?.[0])}
              />
              {label}
            </label>
            {hasPhoto && (
              <Button disabled={busy} onClick={remove}>
                사진 지우기
              </Button>
            )}
            <span className="st-muted">JPG·PNG·WebP, 10MB 까지. 이 계정에서만 보입니다.</span>
          </div>
          {source?.kind === 'image' ? (
            <FitControl />
          ) : (
            wallpaper !== 'default' && <p className="st-muted">그림 테마는 늘 화면을 채웁니다. 밝게·어둡게는 테마를 따라 바뀝니다.</p>
          )}
          {error && (
            <p className="st-error" role="alert">
              {error}
            </p>
          )}
        </div>
      </div>
    </section>
  );
}
