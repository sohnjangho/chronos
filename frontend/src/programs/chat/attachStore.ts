// 대화 입력창에 붙인 파일 상태(올리기 · 2초 상태 폴링 · 한도 검사 · 자료함에서 붙이기).
import { create } from 'zustand';
import { onUserChange } from '../../os/session';
import { ApiError } from '../../shared/api';
import type { ChipItem } from '../../shared/files/FileChip';
import { getFile, MAX_FILE_BYTES, MAX_FILES, uploadFiles } from '../../shared/files/filesApi';
import { resizeImage } from '../../shared/files/resizeImage';

export const POLL_MS = 2000;
const TERMINAL = new Set(['classified', 'failed']);

let seq = 0;
const nextLocalId = () => `att-${++seq}`;
const pollTimers = new Map<string, ReturnType<typeof setTimeout>>();

function stopPoll(localId: string) {
  const t = pollTimers.get(localId);
  if (t) clearTimeout(t);
  pollTimers.delete(localId);
}

function stopAllPolls() {
  for (const t of pollTimers.values()) clearTimeout(t);
  pollTimers.clear();
}

function revokeThumb(item: ChipItem) {
  if (item.thumbUrl && typeof URL.revokeObjectURL === 'function') URL.revokeObjectURL(item.thumbUrl);
}

function inferKind(file: File): string {
  if (file.type.startsWith('image/')) return 'image';
  const ext = file.name.split('.').pop()?.toLowerCase() ?? '';
  if (ext === 'pdf') return 'pdf';
  if (ext === 'xlsx' || ext === 'xls') return 'sheet';
  if (ext === 'csv') return 'table';
  if (ext === 'docx' || ext === 'doc') return 'doc';
  return 'text';
}

function schedulePoll(localId: string, fileId: number) {
  stopPoll(localId);
  const timer = setTimeout(async () => {
    pollTimers.delete(localId);
    const cur = useAttach.getState().items.find((i) => i.localId === localId);
    if (!cur) return;
    try {
      const info = await getFile(fileId);
      const status = info.status as ChipItem['status'];
      useAttach.setState((s) => ({
        items: s.items.map((i) =>
          i.localId === localId ? { ...i, kind: info.kind, status, reason: info.reason, axes: info.axes } : i,
        ),
      }));
      if (!TERMINAL.has(status)) schedulePoll(localId, fileId);
    } catch {
      // 다음 주기에 다시 시도하지 않고 조용히 멈춘다(사용자가 보내기 가능)
    }
  }, POLL_MS);
  pollTimers.set(localId, timer);
}

interface AttachState {
  items: ChipItem[];
  notice: string | null;
  addFiles(files: File[]): Promise<void>;
  attachExisting(fileId: number): Promise<void>;
  remove(localId: string): void;
  clear(): void;
  readyFileIds(): number[];
}

export const useAttach = create<AttachState>((set, get) => ({
  items: [],
  notice: null,

  async addFiles(rawFiles) {
    if (rawFiles.length === 0) return;
    const current = get().items;
    if (current.length + rawFiles.length > MAX_FILES) {
      set({ notice: `한 번에 ${MAX_FILES}개까지 붙일 수 있습니다.` });
      return;
    }
    const tooBig = rawFiles.find((f) => f.size > MAX_FILE_BYTES);
    if (tooBig) {
      set({ notice: `파일당 50MB까지 올릴 수 있습니다: ${tooBig.name}` });
      return;
    }
    set({ notice: null });

    const prepared = await Promise.all(rawFiles.map((f) => resizeImage(f)));
    const placeholders: ChipItem[] = prepared.map(({ file, resized }) => {
      const kind = inferKind(file);
      const thumbUrl =
        kind === 'image' && typeof URL.createObjectURL === 'function' ? URL.createObjectURL(file) : null;
      return {
        localId: nextLocalId(),
        fileId: null,
        name: file.name,
        kind,
        status: 'uploading',
        reason: null,
        axes: {},
        thumbUrl,
        resized,
      };
    });
    set((s) => ({ items: [...s.items, ...placeholders] }));

    try {
      const uploaded = await uploadFiles(prepared.map((p) => p.file));
      set((s) => ({
        items: s.items.map((item) => {
          const idx = placeholders.findIndex((p) => p.localId === item.localId);
          if (idx === -1) return item;
          const u = uploaded[idx];
          if (!u) return { ...item, status: 'failed', reason: '응답이 비어 있습니다.' };
          const status = u.status as ChipItem['status'];
          if (!TERMINAL.has(status)) schedulePoll(item.localId, u.file_id);
          return { ...item, fileId: u.file_id, kind: u.kind, status, reason: u.reason };
        }),
      }));
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : '파일을 올리지 못했습니다.';
      const ids = new Set(placeholders.map((p) => p.localId));
      set((s) => ({
        items: s.items.map((i) => (ids.has(i.localId) ? { ...i, status: 'failed', reason: msg } : i)),
      }));
    }
  },

  async attachExisting(fileId) {
    if (get().items.some((i) => i.fileId === fileId)) return;
    if (get().items.length >= MAX_FILES) {
      set({ notice: `한 번에 ${MAX_FILES}개까지 붙일 수 있습니다.` });
      return;
    }
    try {
      const info = await getFile(fileId);
      const localId = nextLocalId();
      const status = info.status as ChipItem['status'];
      const chip: ChipItem = {
        localId,
        fileId: info.file_id,
        name: info.name,
        kind: info.kind,
        status,
        reason: info.reason,
        axes: info.axes,
        thumbUrl: null,
        resized: false,
      };
      set((s) => ({ items: [...s.items, chip], notice: null }));
      if (!TERMINAL.has(status)) schedulePoll(localId, info.file_id);
    } catch (e) {
      set({ notice: e instanceof ApiError ? e.message : '파일을 불러올 수 없습니다.' });
    }
  },

  remove(localId) {
    stopPoll(localId);
    const target = get().items.find((i) => i.localId === localId);
    if (target) revokeThumb(target);
    set((s) => ({ items: s.items.filter((i) => i.localId !== localId) }));
  },

  clear() {
    stopAllPolls();
    get().items.forEach(revokeThumb);
    set({ items: [], notice: null });
  },

  readyFileIds() {
    return get()
      .items.filter((i) => i.fileId !== null && i.status !== 'failed' && i.status !== 'uploading')
      .map((i) => i.fileId as number);
  },
}));

onUserChange(() => useAttach.getState().clear());
