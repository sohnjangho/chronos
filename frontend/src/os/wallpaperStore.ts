// 고른 바탕화면 배경·배치 방식(계정별). 화면 상태와 같은 길로 둔다: 이 브라우저(prefs — 첫 그림·오프라인)와
// 서버(/api/me/ui-state 의 appearance — 기기 사이). 서버에 못 보낸 고름(dirty)이 있으면 서버 것으로 덮지 않고 다시 보낸다.
// 내 사진은 /api/me/wallpaper(본인만) 에서 받아 이 탭 안에서만 쓰는 blob 주소로 둔다.
import { create } from 'zustand';
import { api, failure, requestHeaders } from '../shared/api';
import { loadPref, savePref } from './prefs';
import { FIT_IDS, WALLPAPER_IDS, type Fit, type WallpaperId } from './wallpapers';

export const PHOTO_MAX_BYTES = 10 * 1024 * 1024;
export const PHOTO_TOO_BIG = '사진이 너무 큽니다. 10MB 까지 올릴 수 있습니다.';
export const PHOTO_BAD_TYPE = 'JPG·PNG·WebP 사진만 올릴 수 있습니다.';
const PHOTO_TYPES = ['image/jpeg', 'image/png', 'image/webp'];
const PREF = 'wallpaper';

interface Appearance {
  v: 1;
  wallpaper: WallpaperId;
  fit: Fit;
}
interface Cached {
  state: Appearance;
  at: number;
  dirty: boolean;
}
export type Photo = { status: 'unknown' | 'loading' | 'none' } | { status: 'ready'; url: string };

interface WallpaperState {
  userId: number | null;
  wallpaper: WallpaperId;
  fit: Fit;
  photo: Photo;
  load(userId: number | null): void;
  sync(): Promise<void>;
  choose(id: WallpaperId): void;
  setFit(fit: Fit): void;
  loadPhoto(): Promise<void>;
  uploadPhoto(file: File): Promise<void>;
  removePhoto(): Promise<void>;
  reset(): void;
}

const DEFAULTS = { wallpaper: 'default' as WallpaperId, fit: 'fill' as Fit };

function readState(raw: unknown): Appearance | null {
  const r = raw as Partial<Appearance> | null;
  if (!r || typeof r !== 'object' || r.v !== 1) return null;
  if (!WALLPAPER_IDS.includes(r.wallpaper as WallpaperId) || !FIT_IDS.includes(r.fit as Fit)) return null;
  return { v: 1, wallpaper: r.wallpaper as WallpaperId, fit: r.fit as Fit };
}

function readCached(userId: number | null): Cached | null {
  const raw = loadPref(PREF, userId) as Partial<Cached> | null;
  const state = readState(raw?.state);
  if (!raw || !state) return null;
  return { state, at: typeof raw.at === 'number' ? raw.at : 0, dirty: raw.dirty === true };
}

let photoUrl: string | null = null;
function setPhotoUrl(next: string | null) {
  if (photoUrl) URL.revokeObjectURL(photoUrl);
  photoUrl = next;
}

const current = (): Appearance => {
  const { wallpaper, fit } = useWallpaper.getState();
  return { v: 1, wallpaper, fit };
};

/** 한 번에 하나만 보낸다. 보내는 사이 또 바뀌면 끝난 뒤 마지막 것을 한 번 더. 못 보내면 dirty 로 남아 다음에 다시. */
let inflight = false;
let queued = false;
function send(): void {
  const { userId } = useWallpaper.getState();
  if (userId === null) return;
  if (inflight) {
    queued = true;
    return;
  }
  inflight = true;
  const body = current();
  api<{ updated_at: string }>('/api/me/ui-state/appearance', { method: 'PUT', body: JSON.stringify(body), keepalive: true })
    .then((r) => {
      if (useWallpaper.getState().userId !== userId) return;
      const now = current();
      const same = now.wallpaper === body.wallpaper && now.fit === body.fit;
      savePref(PREF, userId, { state: now, at: Date.parse(r.updated_at) || 0, dirty: !same });
    })
    .catch(() => undefined)
    .finally(() => {
      inflight = false;
      if (queued) {
        queued = false;
        send();
      }
    });
}

/** 내 사진 바이트(없으면 null). 연결·서버 오류는 던진다. */
async function fetchPhoto(): Promise<Blob | null> {
  const { headers, token } = requestHeaders({}, true);
  const res = await fetch('/api/me/wallpaper', { headers, cache: 'no-cache' });
  if (res.ok) return res.blob();
  if (res.status === 404) return null;
  throw await failure(res, token);
}

export const useWallpaper = create<WallpaperState>((set, get) => {
  const commit = (patch: Partial<Pick<WallpaperState, 'wallpaper' | 'fit'>>) => {
    set(patch);
    const { userId } = get();
    if (userId === null) return;
    savePref(PREF, userId, { state: current(), at: readCached(userId)?.at ?? 0, dirty: true });
    send();
  };

  const showPhoto = (userId: number | null, blob: Blob | null) => {
    if (get().userId !== userId) return;
    setPhotoUrl(blob ? URL.createObjectURL(blob) : null);
    set({ photo: photoUrl ? { status: 'ready', url: photoUrl } : { status: 'none' } });
  };

  return {
    userId: null,
    ...DEFAULTS,
    photo: { status: 'unknown' },

    load(userId) {
      const cached = readCached(userId);
      setPhotoUrl(null);
      set({ userId, ...(cached ? { wallpaper: cached.state.wallpaper, fit: cached.state.fit } : DEFAULTS), photo: { status: 'unknown' } });
    },

    async sync() {
      const { userId } = get();
      if (userId === null) return;
      let row: { state: unknown; updated_at: string } | undefined;
      try {
        row = (await api<{ appearance?: { state: unknown; updated_at: string } }>('/api/me/ui-state')).appearance;
      } catch {
        return; // 서버를 못 읽으면 이 브라우저 것만
      }
      if (get().userId !== userId) return;
      const cached = readCached(userId);
      if (cached?.dirty) {
        send();
        return;
      }
      const server = readState(row?.state);
      if (!server || !row) return;
      const at = Date.parse(row.updated_at) || 0;
      if (at < (cached?.at ?? 0)) return;
      set({ wallpaper: server.wallpaper, fit: server.fit });
      savePref(PREF, userId, { state: server, at, dirty: false });
    },

    choose(id) {
      commit({ wallpaper: id });
    },

    setFit(fit) {
      commit({ fit });
    },

    async loadPhoto() {
      const { userId } = get();
      if (userId === null || get().photo.status === 'loading') return;
      set({ photo: { status: 'loading' } });
      const blob = await fetchPhoto().catch(() => null); // 못 받으면 기본 바탕으로(다시 들어오면 다시 받는다)
      showPhoto(userId, blob);
    },

    async uploadPhoto(file) {
      if (file.size > PHOTO_MAX_BYTES) throw new Error(PHOTO_TOO_BIG);
      if (!PHOTO_TYPES.includes(file.type)) throw new Error(PHOTO_BAD_TYPE);
      const { userId } = get();
      await api('/api/me/wallpaper', { method: 'PUT', body: file }); // 서버 오류 글(한국어)이 그대로 올라간다
      set({ photo: { status: 'loading' } });
      showPhoto(userId, await fetchPhoto().catch(() => null));
      commit({ wallpaper: 'photo' });
    },

    async removePhoto() {
      await api('/api/me/wallpaper', { method: 'DELETE' });
      setPhotoUrl(null);
      set({ photo: { status: 'none' } });
      if (get().wallpaper === 'photo') commit({ wallpaper: 'default' });
    },

    reset() {
      setPhotoUrl(null);
      inflight = false;
      queued = false;
      set({ userId: null, ...DEFAULTS, photo: { status: 'unknown' } });
    },
  };
});
