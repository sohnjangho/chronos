// 열어 둔 창·탭을 계정에 붙여 둔다(화면 형태마다). 이 브라우저(prefs, 첫 그림·오프라인)와 서버(/api/me/ui-state, 기기 사이).
// - 바뀌면 이 브라우저에는 0.3초 뒤, 서버에는 1초 뒤 쓴다. 숨겨지거나(visibilitychange) 떠날 때(pagehide) 바로 쓴다
//   — 모바일 브라우저가 탭을 버려도 마지막 모양이 남는다. 서버 쓰기는 keepalive, 한 번에 하나, 같은 모양이면 보내지 않는다.
// - 열 때: 이 브라우저 것으로 먼저 그리고, 서버 것이 더 새것이면(그새 손대지 않았으면) 서버 것으로 바꾼다.
//   다른 화면 형태(다른 기기)의 상태가 더 새것이면 그곳 맨 앞 프로그램도 여기서 연다.
// - 사람이 바뀌면(로그아웃·다른 사람) shellReset 이 endLayouts 로 앞 사람 것을 마저 쓰고 끊는다 — 비운 화면을 앞 사람
//   것으로 쓰지 않고, 다음 사람 토큰으로 앞 사람 것을 보내지 않는다.
import { useEffect, useLayoutEffect, useRef } from 'react';
import { api, ApiError } from '../shared/api';
import { desktopLayout, focusOf, readDesktop, savedDesktop, type Focus, type LayoutMode } from './layoutMemory';
import { loadPref, savePref } from './prefs';
import { useSession, type Role } from './session';
import { autoFitting, useWindows } from './windowStore';

export const LOCAL_DELAY_MS = 300;
export const SERVER_DELAY_MS = 1000;
/** 서버 쓰기가 실패하면(연결·5xx) 이만큼 기다려 다시 — 그 뒤로는 다음 변경·숨김 때. */
export const RETRY_MS = [2000, 5000, 15000] as const;
const pref = (mode: LayoutMode) => `layout.${mode}`;

interface Cached {
  state: unknown;
  /** 서버와 맞춘 때(서버 시각 ms). 맞춘 적이 없으면 0. */
  at: number;
  /** 손으로 바꾼 뒤 서버에 아직 보내지 못한 모양이다. */
  dirty: boolean;
}

export function loadCached(mode: LayoutMode, userId: number | null): Cached | null {
  const raw = loadPref(pref(mode), userId) as Partial<Cached> | null;
  if (!raw || typeof raw !== 'object' || typeof raw.at !== 'number' || typeof raw.dirty !== 'boolean' || !('state' in raw)) return null;
  return { state: raw.state, at: raw.at, dirty: raw.dirty };
}

type ServerAll = Partial<Record<LayoutMode, { state: unknown; updated_at: string }>>;

interface Hooks {
  /** 같은 형태의 서버 상태로 바꾼다. 바꾼 뒤 모양(못 쓰면 null). */
  apply(raw: unknown): unknown | null;
  /** 다른 기기에서 맨 앞이던 프로그램을 연다. */
  openFocus(f: Focus): void;
}

const live = new Set<Channel>();

class Channel {
  private json: string;
  private ackedJson: string | null;
  private ackedAt: number;
  private touched = false;
  /** 손으로 바꾼 것이 서버에 아직 닿지 않았다(이 브라우저에 dirty 로 남긴다). */
  private unsent: boolean;
  private ready = false;
  private closed = false;
  private inflight = false;
  private queued = false;
  private localTimer: ReturnType<typeof setTimeout> | null = null;
  private serverTimer: ReturnType<typeof setTimeout> | null = null;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private retries = 0;

  constructor(
    private readonly mode: LayoutMode,
    private readonly userId: number,
    private readonly role: Role,
    current: unknown,
    private readonly hooks: Hooks,
    fresh: boolean,
  ) {
    const cached = loadCached(mode, userId);
    this.json = JSON.stringify(current);
    this.ackedJson = cached && !cached.dirty ? JSON.stringify(cached.state) : null;
    this.ackedAt = cached?.at ?? 0;
    this.unsent = cached?.dirty ?? false;
    // 읽은 것이 틀렸거나 걸러졌으면 바로 덮어쓴다.
    if (JSON.stringify(cached?.state) !== this.json || !cached) this.writeLocal();
    live.add(this);
    void this.start(fresh);
  }

  private async start(fresh: boolean) {
    let all: ServerAll | null;
    try {
      all = await api<ServerAll>('/api/me/ui-state');
    } catch {
      all = null; // 서버를 못 읽으면 이 브라우저 것만 쓴다
    }
    if (this.closed) return;
    const mine = all?.[this.mode];
    const mineAt = mine ? Date.parse(mine.updated_at) : 0;
    const quiet = fresh && !this.touched && !this.unsent;
    if (mine && quiet && mineAt > this.ackedAt) {
      const next = this.hooks.apply(mine.state);
      if (next !== null) this.json = JSON.stringify(next);
    }
    if (mine && (mineAt >= this.ackedAt || this.ackedJson === null)) {
      this.ackedJson = JSON.stringify(mine.state);
      this.ackedAt = mineAt;
    } else if (all && !mine) {
      this.ackedJson = null; // 서버에 없다 — 지금 것을 올린다
    }
    if (all && quiet) this.continueFrom(all, Math.max(mineAt, this.ackedAt));
    this.ready = true;
    this.writeLocal();
    this.send();
  }

  /** 다른 화면 형태의 상태가 더 새것이면 그 맨 앞 프로그램을 연다. */
  private continueFrom(all: ServerAll, since: number) {
    let best: { at: number; focus: Focus } | null = null;
    for (const mode of ['desktop', 'tablet', 'phone'] as const) {
      const row = all[mode];
      if (mode === this.mode || !row) continue;
      const at = Date.parse(row.updated_at);
      const focus = at > since ? focusOf(mode, row.state, this.role) : null;
      if (focus && (!best || at > best.at)) best = { at, focus };
    }
    if (best) this.hooks.openFocus(best.focus);
  }

  update(state: unknown) {
    const json = JSON.stringify(state);
    if (this.closed || json === this.json) return;
    this.json = json;
    this.touched = true;
    this.unsent = true;
    this.retries = 0;
    if (this.localTimer) clearTimeout(this.localTimer);
    this.localTimer = setTimeout(() => this.writeLocal(), LOCAL_DELAY_MS);
    if (this.serverTimer) clearTimeout(this.serverTimer);
    this.serverTimer = setTimeout(() => this.send(), SERVER_DELAY_MS);
  }

  private writeLocal() {
    if (this.localTimer) clearTimeout(this.localTimer);
    this.localTimer = null;
    savePref(pref(this.mode), this.userId, { state: JSON.parse(this.json), at: this.ackedAt, dirty: this.unsent && this.json !== this.ackedJson });
  }

  private send() {
    if (this.serverTimer) clearTimeout(this.serverTimer);
    if (this.retryTimer) clearTimeout(this.retryTimer);
    this.serverTimer = this.retryTimer = null;
    if (!this.ready || this.closed || this.json === this.ackedJson) return;
    if (this.inflight) {
      this.queued = true;
      return;
    }
    const body = this.json;
    this.inflight = true;
    api<{ updated_at: string }>(`/api/me/ui-state/${this.mode}`, { method: 'PUT', body, keepalive: true })
      .then((r) => {
        this.ackedJson = body;
        this.ackedAt = Date.parse(r.updated_at) || this.ackedAt;
        this.retries = 0;
        this.writeLocal();
      })
      .catch((e: unknown) => {
        // 연결 끊김·서버 오류만 다시(모양이 틀린 422·권한 401 은 다시 보내도 같다).
        const again = !(e instanceof ApiError) || e.status === 0 || e.status >= 500;
        if (again && !this.closed && this.retries < RETRY_MS.length) {
          this.retryTimer = setTimeout(() => this.send(), RETRY_MS[this.retries++]);
        }
      })
      .finally(() => {
        this.inflight = false;
        if (this.queued) {
          this.queued = false;
          this.send();
        }
      });
  }

  /** 지금 모양을 바로 쓴다(숨김·떠남). */
  flush() {
    if (this.closed) return;
    this.writeLocal();
    this.send();
  }

  close() {
    this.flush();
    if (this.retryTimer) clearTimeout(this.retryTimer);
    this.closed = true;
    live.delete(this);
  }
}

/** 열어 둔 모든 기억을 바로 쓴다(숨김·떠남). */
export function flushLayouts(): void {
  live.forEach((c) => c.flush());
}

/** 사람이 바뀔 때(shellReset): 앞 사람 것을 마저 쓰고 끊는다. */
export function endLayouts(): void {
  [...live].forEach((c) => c.close());
}

if (typeof window !== 'undefined') {
  window.addEventListener('pagehide', flushLayouts);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') flushLayouts();
  });
}

const signedIn = () => {
  const user = useSession.getState().session?.user;
  return user ? { userId: user.id, role: user.role } : null;
};

/**
 * 데스크톱: 창 배치를 되살리고(창이 하나도 없을 때만) 사람이 바꿀 때마다 기억한다.
 * 화면에 맞춘 자동 조정(되살리며 줄이기·브라우저 크기·패널)은 기억하지 않는다 — 기억하는 자리는 맞추기 전 자리다.
 * 개발 모드(StrictMode)가 효과를 두 번 돌려도 첫 판단(fresh)·첫 모양을 그대로 쓴다(마운트마다 한 번, 사람별).
 */
export function useDesktopLayout(): void {
  const userId = useSession((s) => s.session?.user.id ?? null);
  const role = useSession((s) => s.session?.user.role ?? null);
  const first = useRef<{ userId: number; fresh: boolean; baseline: unknown } | null>(null);
  useLayoutEffect(() => {
    const me = signedIn();
    if (userId === null || !me) return;
    const store = useWindows.getState;
    const restore = (raw: unknown) => {
      const l = readDesktop(raw, me.role);
      if (!l) return null;
      store().restoreLayout(l.wins, l.deactivated);
      return savedDesktop(l);
    };
    if (first.current?.userId !== userId) {
      const fresh = store().wins.length === 0;
      const restored = fresh ? restore(loadCached('desktop', userId)?.state) : null;
      first.current = { userId, fresh, baseline: restored ?? desktopLayout(store()) };
    }
    const { fresh, baseline } = first.current;
    const channel = new Channel('desktop', userId, me.role, baseline, {
      apply: restore,
      openFocus: (f) => void store().open(f.program, f.params),
    }, fresh);
    // 이번 바뀜이 배치를 바꿨을 때만, 그리고 자동 맞춤이 아닐 때만 기억한다(제목·움직임 표시 같은 바뀜에 맞춘 자리가 실려 가지 않게).
    let seen = JSON.stringify(desktopLayout(store()));
    const unsub = useWindows.subscribe((s) => {
      const now = desktopLayout(s);
      const json = JSON.stringify(now);
      if (json === seen) return;
      seen = json;
      if (!autoFitting()) channel.update(now);
    });
    return () => {
      unsub();
      channel.close();
    };
  }, [userId, role]);
}

/**
 * 태블릿·스마트폰: 셸이 가진 상태(layout)를 바뀔 때마다 기억한다. 첫 상태는 셸이 loadCached 로 읽어 정한다.
 * apply·openFocus 는 셸의 상태를 바꾼다.
 */
export function useShellLayout(mode: 'tablet' | 'phone', layout: unknown, hooks: Hooks): void {
  const userId = useSession((s) => s.session?.user.id ?? null);
  const hooksRef = useRef(hooks);
  const layoutRef = useRef(layout);
  const channelRef = useRef<Channel | null>(null);
  const json = JSON.stringify(layout);
  useEffect(() => {
    hooksRef.current = hooks;
    layoutRef.current = layout;
  });
  useEffect(() => {
    const me = signedIn();
    if (userId === null || !me) return;
    const channel = new Channel(mode, userId, me.role, layoutRef.current, {
      apply: (raw) => hooksRef.current.apply(raw),
      openFocus: (f) => hooksRef.current.openFocus(f),
    }, true);
    channelRef.current = channel;
    return () => {
      channelRef.current = null;
      channel.close();
    };
  }, [mode, userId]);
  useEffect(() => {
    channelRef.current?.update(JSON.parse(json));
  }, [json]);
}
